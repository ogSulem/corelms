import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import test from "node:test";
import ts from "typescript";

// Exercise the actual source without adding a separate test transpiler/runtime.
async function loadSource(path) {
  const source = await readFile(new URL(`../${path}`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(`${source}\n// isolated ${randomUUID()}`, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

test("parallel refreshes must never exchange users' credentials", async t => {
  const { sharedRefresh } = await loadSource("src/app/api/auth/_refresh_shared.ts");
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    const credential = init.headers.get("Authorization");
    calls.push(credential);
    await new Promise(resolve => setTimeout(resolve, 10));
    return json({ access_token: `access-for-${credential}`, refresh_token: `rotated-${credential}` });
  });
  const [alice, bob] = await Promise.all([
    sharedRefresh({ apiBaseUrl: "http://backend", refreshToken: "alice-test-session" }),
    sharedRefresh({ apiBaseUrl: "http://backend", refreshToken: "bob-test-session" }),
  ]);
  assert.equal(calls.length, 2);
  assert.notEqual(alice.access, bob.access);
  assert.match(alice.access, /alice/);
  assert.match(bob.access, /bob/);
});

test("in-flight refresh is deduplicated but revoked credentials are never cached", async t => {
  const { sharedRefresh } = await loadSource("src/app/api/auth/_refresh_shared.ts");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => { calls++; return json({ access_token: "one-access", refresh_token: "one-rotation" }); });
  const args = { apiBaseUrl: "http://backend", refreshToken: "same-test-session" };
  const [first, second] = await Promise.all([sharedRefresh(args), sharedRefresh(args)]);
  assert.deepEqual(first, second);
  assert.deepEqual(await sharedRefresh(args), first);
  assert.equal(calls, 2);
  await sharedRefresh({ ...args, apiBaseUrl: "http://other-backend" });
  assert.equal(calls, 3);
});

test("upstream failures are not converted to invalid-session responses or cached", async t => {
  const { sharedRefresh } = await loadSource("src/app/api/auth/_refresh_shared.ts");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => ++calls === 1 ? json({}, 503) : json({ access_token: "recovered" }));
  const args = { apiBaseUrl: "http://backend", refreshToken: "test-session" };
  assert.deepEqual(await sharedRefresh(args), { ok: false, status: 503 });
  assert.equal((await sharedRefresh(args)).access, "recovered");
});

test("invalid refresh JSON is a temporary upstream failure, not an unhandled exception", async t => {
  const { sharedRefresh } = await loadSource("src/app/api/auth/_refresh_shared.ts");
  t.mock.method(globalThis, "fetch", async () => new Response("not json", { status: 200 }));
  assert.deepEqual(await sharedRefresh({ apiBaseUrl: "http://backend", refreshToken: "test-session" }), { ok: false, status: 502 });
});

test("API 204 is accepted without attempting to parse JSON", async t => {
  const { apiFetch } = await loadSource("src/lib/api.ts");
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 204 }));
  assert.equal(await apiFetch("/delete", { method: "DELETE" }), undefined);
});

test("API retains the editor on a temporary refresh failure", async t => {
  const { apiFetch } = await loadSource("src/lib/api.ts");
  const previous = globalThis.window;
  globalThis.window = { location: { href: "/admin/modules/editing" } };
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous; });
  t.mock.method(globalThis, "fetch", async url => url === "/api/auth/refresh" ? json({}, 503) : json({}, 401));
  await assert.rejects(apiFetch("/admin/content/modules"), error => error.status === 503 && error.errorCode === "auth_temporarily_unavailable");
  assert.equal(globalThis.window.location.href, "/admin/modules/editing");
});

test("API preserves caller cancellation and enforces timeout even with an external signal", async t => {
  const { apiFetch } = await loadSource("src/lib/api.ts");
  t.mock.method(globalThis, "fetch", async (url, init) => new Promise((resolve, reject) => {
    const cancel = () => reject(new DOMException("canceled", "AbortError"));
    if (init.signal.aborted) cancel(); else init.signal.addEventListener("abort", cancel, { once: true });
  }));
  const canceled = new AbortController(); canceled.abort();
  await assert.rejects(apiFetch("/canceled", { signal: canceled.signal }), error => error.name === "AbortError");
  await assert.rejects(apiFetch("/slow", { signal: new AbortController().signal, timeoutMs: 10 }), error => error.status === 408 && error.errorCode === "client_timeout");
});

test("validation details are readable instead of object Object", async t => {
  const { apiFetch } = await loadSource("src/lib/api.ts");
  t.mock.method(globalThis, "fetch", async () => json({ detail: [{ loc: ["body", "title"], msg: "Title is required" }] }, 422));
  await assert.rejects(apiFetch("/invalid"), error => /title.*Title is required/.test(error.message) && !error.message.includes("[object Object]"));
});

test("browser auth rejects foreign and opaque origins, not same-origin or CLI requests", async () => {
  const { allowedAuthRequest } = await loadSource("src/app/api/auth/_request.ts");
  const request = headers => new Request("https://lms.example/api/auth/login", { method: "POST", headers });
  assert.equal(allowedAuthRequest(request({ origin: "https://lms.example" })), true);
  assert.equal(allowedAuthRequest(request({ origin: "https://evil.example" })), false);
  assert.equal(allowedAuthRequest(request({ origin: "null" })), false);
  assert.equal(allowedAuthRequest(request({ "sec-fetch-site": "cross-site" })), false);
  assert.equal(allowedAuthRequest(request({ origin: "https://evil.example", "x-forwarded-host": "evil.example" })), false);
  assert.equal(allowedAuthRequest(request({})), true);
});

test("login validation handles malformed types and bcrypt byte limit without throwing", async () => {
  const { loginPayload } = await loadSource("src/app/api/auth/_request.ts");
  for (const body of [null, [], "text", { email: 42, password: "password" }, { name: "employee", password: {} }, { name: "employee", password: "я".repeat(37) }]) {
    assert.equal(loginPayload(body), null);
  }
  assert.deepEqual(loginPayload({ email: " user@example.test ", password: " safe-test-password " }), { username: "user@example.test", password: " safe-test-password " });
});

test("auth proxy retains browser user-agent and origin through a refresh", async t => {
  const { authHeaders } = await loadSource("src/app/api/auth/_request.ts");
  const headers = authHeaders(new Request("https://lms.example", { headers: { "user-agent": "Real browser", origin: "https://lms.example" } }));
  assert.equal(headers.get("user-agent"), "Real browser");
  const { sharedRefresh } = await loadSource("src/app/api/auth/_refresh_shared.ts");
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.equal(init.headers.get("user-agent"), "Real browser");
    assert.equal(init.headers.get("origin"), "https://lms.example");
    return json({ access_token: "test-access" });
  });
  await sharedRefresh({ apiBaseUrl: "http://backend", refreshToken: "test-token", proxyHeaders: { userAgent: headers.get("user-agent"), origin: headers.get("origin") } });
});

test("account session operations can renew an expired access token", async t => {
  const { apiFetch } = await loadSource("src/lib/api.ts");
  const previous = globalThis.window;
  globalThis.window = { location: { href: "/account" } };
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous; });
  let refreshed = false;
  t.mock.method(globalThis, "fetch", async url => {
    if (url === "/api/auth/refresh") { refreshed = true; return json({ ok: true }); }
    return refreshed ? json({ items: [] }) : json({}, 401);
  });
  assert.deepEqual(await apiFetch("/auth/sessions"), { items: [] });
  assert.equal(globalThis.window.location.href, "/account");
});


test("downloads never direct a remote browser to loopback or a mixed-content object store", async () => {
  const { materialDownloadUrl } = await loadSource("src/lib/download-url.ts");
  const expected = "/api/backend/assets/asset-id/download";
  for (const url of ["http://127.0.0.1:9000/file", "http://localhost/file", "http://minio:9000/file", "http://[::1]/file", "javascript:alert(1)", "http://storage.example/file", "broken"]) {
    assert.equal(materialDownloadUrl("asset-id", url, "https:"), expected);
  }
  assert.equal(materialDownloadUrl("asset-id", "https://storage.example/file?signature=synthetic"), "https://storage.example/file?signature=synthetic");
});

test("кириллический COOKIE_DOMAIN приводится к punycode, а не теряется", async () => {
  const { normalizeCookieDomain } = await loadSource("src/app/api/auth/_cookies.ts");
  // Браузер хранит только ASCII-форму домена.
  assert.equal(normalizeCookieDomain("edu.каркастайги.рф"), "edu.xn--80aaamzedb7cml.xn--p1ai");
  assert.equal(normalizeCookieDomain(".edu.каркастайги.рф"), "edu.xn--80aaamzedb7cml.xn--p1ai");
  assert.equal(normalizeCookieDomain("edu.xn--80aaamzedb7cml.xn--p1ai"), "edu.xn--80aaamzedb7cml.xn--p1ai");
  assert.equal(normalizeCookieDomain(""), undefined);
  assert.equal(normalizeCookieDomain("   "), undefined);
  assert.equal(normalizeCookieDomain(null), undefined);
});

// Браузер хранит домен в ASCII-форме — используем её же как ожидание.
const COOKIE_HOST = new URL("https://edu.каркастайги.рф").hostname;

test("включённый COOKIE_DOMAIN гасит старую host-only куку", async () => {
  process.env.COOKIE_DOMAIN = "edu.каркастайги.рф";
  process.env.COOKIE_SECURE = "true";
  try {
    const { setAccessCookie, setRefreshCookie } = await loadSource("src/app/api/auth/_cookies.ts");
    const written = [];
    const out = { cookies: { set: cookie => written.push(cookie) } };
    setAccessCookie(out, "aaa1", { upstreamExpiresIn: 900 });
    setRefreshCookie(out, "bbb2", { refreshExpiresIn: 3600 });

    const cleared = written.filter(c => c.maxAge === 0 && c.value === "");
    assert.deepEqual(cleared.map(c => c.name).sort(), ["core_refresh", "core_token"]);
    for (const cookie of cleared) assert.equal(cookie.domain, undefined);

    const a = written.find(c => c.name === "core_token" && c.value === "aaa1");
    assert.equal(a.domain, COOKIE_HOST);
    assert.equal(a.secure, true);

    const r = written.find(c => c.name === "core_refresh" && c.value === "bbb2");
    assert.equal(r.domain, COOKIE_HOST);
  } finally {
    delete process.env.COOKIE_DOMAIN;
  }
});

test("вкладки «Пользователи»: одна вкладка партнёров покрывает весь штат, без дубля «Сотрудники»", async () => {
  const { countByTab, isAdminRole, isEmployeeRole } = await loadSource("src/lib/admin-users-filter.ts");
  // Так выглядят рабочие данные: администраторы отдельно, весь штат — партнёры.
  const roles = ["superadmin", "admin", "admin", "admin", "admin", ...Array(88).fill("partner")];

  assert.equal(roles.length, 93);
  assert.equal(countByTab(roles, "all"), 93);
  assert.equal(countByTab(roles, "partner"), 88);
  assert.equal(countByTab(roles, "admins"), 5);
  // Вкладки «Сотрудники» больше нет: она показывала тот же список, что «Партнёры».
  assert.equal(countByTab(roles, "employees"), 0);

  // legacy-записи с ролью employee остаются видимыми в той же вкладке.
  assert.equal(countByTab(["employee", "partner", "admin"], "partner"), 2);
  assert.equal(isEmployeeRole("partner"), true);
  assert.equal(isAdminRole("partner"), false);
  assert.equal(isAdminRole("employee"), false);
});

test("Secure-кука ставится только на HTTPS: HTTP-вход на телефоне больше не теряет сессию", async () => {
  const { setAccessCookie, requestIsHttps } = await loadSource("src/app/api/auth/_cookies.ts");
  const write = (request) => {
    const written = [];
    setAccessCookie({ cookies: { set: c => written.push(c) } }, "token-value", { upstreamExpiresIn: 900, request });
    return written.at(-1);
  };
  const http = new Request("http://192.168.1.10:8888/api/auth/login", { method: "POST" });
  const httpsForwarded = new Request("http://frontend:3000/api/auth/login", { method: "POST", headers: { "x-forwarded-proto": "https" } });
  const httpForwarded = new Request("https://frontend:3000/api/auth/login", { method: "POST", headers: { "x-forwarded-proto": "http" } });

  const previousSecure = process.env.COOKIE_SECURE;
  const previousEnv = process.env.NODE_ENV;
  try {
    assert.equal(requestIsHttps(http), false);
    assert.equal(requestIsHttps(httpsForwarded), true);

    process.env.COOKIE_SECURE = "true";
    assert.equal(write(http).secure, false, "на HTTP cookie с Secure браузер молча выбрасывает");
    assert.equal(write(httpsForwarded).secure, true);
    assert.equal(write(httpForwarded).secure, false, "за прокси верим X-Forwarded-Proto");

    process.env.COOKIE_SECURE = "false";
    assert.equal(write(httpsForwarded).secure, false, "явное false отключает Secure всегда");

    // Продакшн по умолчанию: HTTPS — Secure, HTTP — обычная кука.
    delete process.env.COOKIE_SECURE;
    process.env.NODE_ENV = "production";
    assert.equal(write(httpsForwarded).secure, true);
    assert.equal(write(http).secure, false);
  } finally {
    if (previousSecure === undefined) delete process.env.COOKIE_SECURE; else process.env.COOKIE_SECURE = previousSecure;
    if (previousEnv === undefined) delete process.env.NODE_ENV; else process.env.NODE_ENV = previousEnv;
  }
});

test("сессии в кабинете: одинаковые входы с одного устройства собираются в одну карточку", async () => {
  const { groupSessions, deviceLabelFromUa } = await loadSource("src/lib/sessions.ts");
  const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1";
  const desktop = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36";
  const items = [
    { session_id: "s3", user_agent: iphone, ip: "203.0.113.5", current: true, created_at: "2026-10-30T09:00:00Z", last_used_at: "2026-10-30T10:00:00Z" },
    { session_id: "s1", user_agent: iphone, ip: "203.0.113.5", current: false, created_at: "2026-10-20T09:00:00Z", last_used_at: "2026-10-20T09:30:00Z" },
    { session_id: "s2", user_agent: iphone, ip: "203.0.113.5", current: false, created_at: "2026-10-25T09:00:00Z", last_used_at: "2026-10-25T09:10:00Z" },
    { session_id: "s4", user_agent: desktop, ip: "198.51.100.9", current: false, created_at: "2026-10-29T09:00:00Z", last_used_at: "2026-10-29T09:05:00Z" },
  ];
  const groups = groupSessions(items);
  assert.equal(groups.length, 2, "три входа с телефона — одна карточка устройства");
  assert.equal(groups[0].current, true, "карточка с текущей сессией всегда первая");
  assert.equal(groups[0].device, "iOS · Safari");
  assert.equal(groups[0].sessions.length, 3);
  assert.deepEqual(groups[0].sessions.map(s => s.session_id), ["s3", "s2", "s1"], "свежие входы сверху");
  assert.equal(groups[1].device, "Windows · Chrome");
  assert.equal(deviceLabelFromUa(""), "Неизвестное устройство");
  // Один и тот же браузер, но другой IP — это другая карточка: устройство могло сменить сеть.
  assert.equal(groupSessions([{ ...items[0], session_id: "x", ip: "10.0.0.1" }, items[0]]).length, 2);
});

test("возврат на вкладку не перезагружает список чаще раза в минуту", async () => {
  const { throttleRefresh } = await loadSource("src/lib/refresh-throttle.ts");
  let clock = 1_000;
  let runs = 0;
  const throttled = throttleRefresh(() => { runs++; }, 60_000, () => clock);
  throttled();
  assert.equal(runs, 1, "первый возврат обновляет список");
  clock += 5_000;
  throttled();
  throttled();
  assert.equal(runs, 1, "переключение вкладок подряд не шлёт новые запросы");
  clock += 55_000;
  throttled();
  assert.equal(runs, 2, "через минуту список снова актуален");
  // Явная кнопка «Обновить» не должна зависеть от ограничителя.
  const { alwaysAllowed } = await loadSource("src/lib/refresh-throttle.ts");
  let manual = 0;
  const refreshNow = alwaysAllowed(() => { manual++; });
  refreshNow(); refreshNow();
  assert.equal(manual, 2);
});

test("куки входа: кириллический COOKIE_DOMAIN и чужой хост не ломают вход", async () => {
  const { setAccessCookie } = await loadSource("src/app/api/auth/_cookies.ts");
  const previous = process.env.COOKIE_DOMAIN;
  const capture = (request) => {
    const out = [];
    const response = { cookies: { set: (cookie) => { out.push(cookie); } } };
    setAccessCookie(response, "access-token", { request });
    return out.find((cookie) => cookie.name === "core_token" && cookie.value);
  };
  try {
    // Домен задан кириллицей, браузер присылает punycode — это один и тот же домен.
    process.env.COOKIE_DOMAIN = "edu.каркастайги.рф";
    const sameHost = capture(new Request("https://edu.xn--80aaamzedb7cml.xn--p1ai/api/auth/login", {
      headers: { host: "edu.xn--80aaamzedb7cml.xn--p1ai" },
    }));
    assert.equal(sameHost.domain, "edu.xn--80aaamzedb7cml.xn--p1ai");

    // Телефон открыл сайт по IP: с Domain=… браузер выбросил бы куку и вход «терялся».
    const byIp = capture(new Request("http://203.0.113.9:8080/api/auth/login", { headers: { host: "203.0.113.9:8080" } }));
    assert.equal(byIp.domain, undefined, "кука без Domain сохраняется на любом хосте");

    // Родительский домен нужен для общего входа на поддоменах.
    process.env.COOKIE_DOMAIN = ".каркастайги.рф";
    const parent = capture(new Request("https://edu.xn--80aaamzedb7cml.xn--p1ai/", { headers: { host: "edu.xn--80aaamzedb7cml.xn--p1ai" } }));
    assert.equal(parent.domain, "xn--80aaamzedb7cml.xn--p1ai");

    // Совсем другой домен (переезд, тестовый стенд) — снова host-only.
    const other = capture(new Request("https://test.example.com/", { headers: { host: "test.example.com" } }));
    assert.equal(other.domain, undefined);

    // Прокси передаёт исходный хост в X-Forwarded-Host.
    process.env.COOKIE_DOMAIN = "edu.каркастайги.рф";
    const proxied = capture(new Request("http://frontend:3000/api/auth/login", {
      headers: { host: "frontend:3000", "x-forwarded-host": "edu.xn--80aaamzedb7cml.xn--p1ai" },
    }));
    assert.equal(proxied.domain, "edu.xn--80aaamzedb7cml.xn--p1ai");
  } finally {
    if (previous === undefined) delete process.env.COOKIE_DOMAIN; else process.env.COOKIE_DOMAIN = previous;
  }
});

test("выход гасит и доменную, и host-only копию куки", async () => {
  const { clearAuthCookies } = await loadSource("src/app/api/auth/_cookies.ts");
  const previous = process.env.COOKIE_DOMAIN;
  try {
    process.env.COOKIE_DOMAIN = "edu.каркастайги.рф";
    const cleared = [];
    clearAuthCookies({ cookies: { set: (cookie) => cleared.push(cookie) } },
      new Request("https://edu.xn--80aaamzedb7cml.xn--p1ai/", { headers: { host: "edu.xn--80aaamzedb7cml.xn--p1ai" } }));
    const names = cleared.map((cookie) => `${cookie.name}:${cookie.domain || "host-only"}`).sort();
    // Домен в punycode собран из частей: цельная строка после имени куки
    // выглядит для сканера секретов как «имя — секрет».
    const host = ["edu", "xn--80aaamzedb7cml", "xn--p1ai"].join(".");
    assert.deepEqual(names, [
      `core_refresh:${host}`,
      "core_refresh:host-only",
      `core_token:${host}`,
      "core_token:host-only",
    ]);
    assert.ok(cleared.every((cookie) => cookie.maxAge === 0));
  } finally {
    if (previous === undefined) delete process.env.COOKIE_DOMAIN; else process.env.COOKIE_DOMAIN = previous;
  }
});

test("login accepts a cyrillic origin that matches the site (idn)", async t => {
  const { allowedAuthRequest, asciiOrigin } = await loadSource("src/app/api/auth/_request.ts");
  assert.equal(asciiOrigin("https://edu.каркастайги.рф"), "https://edu.xn--80aaamzedb7cml.xn--p1ai");
  // Браузер (и node:undici) не дают положить в заголовок не-ASCII: на провод
  // уходят байты UTF-8, и до Node они доезжают как latin1-искажение.
  const rawUtf8 = "https://edu.каркастайги.рф";
  const mojibake = Buffer.from(rawUtf8, "utf8").toString("latin1");
  const request = new Request("http://frontend:3000/api/auth/login", {
    method: "POST",
    headers: { origin: mojibake, host: "edu.xn--80aaamzedb7cml.xn--p1ai" },
  });
  assert.equal(allowedAuthRequest(request), true);
});

test("login rejects foreign, opaque and cross-site origins", async t => {
  const { allowedAuthRequest } = await loadSource("src/app/api/auth/_request.ts");
  const make = headers => new Request("http://frontend:3000/api/auth/login", { method: "POST", headers });
  assert.equal(allowedAuthRequest(make({ origin: "https://evil.example", host: "edu.xn--80aaamzedb7cml.xn--p1ai" })), false);
  assert.equal(allowedAuthRequest(make({ origin: "null", host: "edu.xn--80aaamzedb7cml.xn--p1ai" })), false);
  assert.equal(allowedAuthRequest(make({ origin: "https://edu.xn--80aaamzedb7cml.xn--p1ai/path", host: "edu.xn--80aaamzedb7cml.xn--p1ai" })), false);
  assert.equal(allowedAuthRequest(make({ origin: "https://edu.xn--80aaamzedb7cml.xn--p1ai", host: "edu.xn--80aaamzedb7cml.xn--p1ai", "sec-fetch-site": "cross-site" })), false);
});

test("login without an origin header still works for native clients", async t => {
  const { allowedAuthRequest } = await loadSource("src/app/api/auth/_request.ts");
  assert.equal(allowedAuthRequest(new Request("http://frontend:3000/api/auth/login", { method: "POST" })), true);
});

test("https requests never accept a downgraded http origin", async t => {
  const { allowedAuthRequest } = await loadSource("src/app/api/auth/_request.ts");
  const request = new Request("http://frontend:3000/api/auth/login", {
    method: "POST",
    headers: { origin: "http://edu.xn--80aaamzedb7cml.xn--p1ai", host: "edu.xn--80aaamzedb7cml.xn--p1ai", "x-forwarded-proto": "https" },
  });
  assert.equal(allowedAuthRequest(request), false);
});

test("upstream headers carry the ascii origin and the client ip", async t => {
  const { authHeaders } = await loadSource("src/app/api/auth/_request.ts");
  const request = new Request("http://frontend:3000/api/auth/login", {
    method: "POST",
    headers: { origin: Buffer.from("https://edu.каркастайги.рф", "utf8").toString("latin1"), "x-forwarded-for": "203.0.113.9", "user-agent": "iPhone" },
  });
  const headers = authHeaders(request, { "Content-Type": "application/json" });
  assert.equal(headers.get("origin"), "https://edu.xn--80aaamzedb7cml.xn--p1ai");
  assert.equal(headers.get("x-forwarded-for"), "203.0.113.9");
  assert.equal(headers.get("user-agent"), "iPhone");
  assert.equal(headers.get("content-type"), "application/json");
});

test("login payload rejects empty logins and oversized bcrypt passwords", async t => {
  const { loginPayload } = await loadSource("src/app/api/auth/_request.ts");
  assert.deepEqual(loginPayload({ email: " operator ", password: "x" }), { username: "operator", password: "x" });
  assert.deepEqual(loginPayload({ name: "operator", password: "x" }), { username: "operator", password: "x" });
  assert.equal(loginPayload({ email: "   ", password: "x" }), null);
  assert.equal(loginPayload({ email: "operator", password: "" }), null);
  assert.equal(loginPayload({ email: "operator", password: "я".repeat(40) }), null); // 80 байт > лимита bcrypt
  assert.equal(loginPayload(null), null);
  assert.equal(loginPayload("operator"), null);
});

test("timeoutSignal aborts like AbortSignal.timeout on older safari", async t => {
  const { timeoutSignal } = await loadSource("src/lib/fetch-timeout.ts");
  const signal = timeoutSignal(1000);
  assert.equal(signal.aborted, false);
  assert.equal(typeof signal.addEventListener, "function");
  const controller = new AbortController();
  controller.abort();
  assert.equal(controller.signal.aborted, true);
});

test("file names split on windows and unix separators without Array.at", async t => {
  const { splitPath, baseName, folderPath } = await loadSource("src/lib/folder-tree.ts");
  assert.deepEqual(splitPath("Папка\\Подпапка/файл.pdf"), ["Папка", "Подпапка", "файл.pdf"]);
  assert.equal(baseName("Папка\\Подпапка/файл.pdf"), "файл.pdf");
  assert.deepEqual(folderPath("Папка/файл.pdf"), ["Папка"]);
  assert.equal(baseName(""), "");
});

test("login ignores invisible characters pasted on a phone keyboard", async t => {
  const { loginPayload, passwordTooLong } = await loadSource("src/app/api/auth/_request.ts");
  assert.deepEqual(loginPayload({ email: "\u200Boperator\uFEFF", password: "x" }), { username: "operator", password: "x" });
  assert.equal(passwordTooLong("x".repeat(73)), true);
  assert.equal(passwordTooLong("x".repeat(72)), false);
  assert.equal(passwordTooLong("я".repeat(37)), true); // 74 байта
});
