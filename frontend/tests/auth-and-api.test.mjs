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

test("account tab counts match the rows they show (partner is an employee, not an admin)", async () => {
  const { countByTab, isAdminRole, isEmployeeRole } = await loadSource("src/lib/admin-users-filter.ts");
  // Так выглядели рабочие данные: администраторы отдельно, весь штат — партнёры.
  const roles = ["superadmin", "admin", "admin", "admin", "admin", ...Array(88).fill("partner")];

  assert.equal(roles.length, 93);
  assert.equal(countByTab(roles, "all"), 93);
  assert.equal(countByTab(roles, "employees"), 88);
  assert.equal(countByTab(roles, "partner"), 88);
  assert.equal(countByTab(roles, "admins"), 5);

  // Главное: вкладка «Сотрудники» не может быть пустой при счётчике 88.
  assert.ok(countByTab(roles, "employees") > 0);
  assert.equal(isEmployeeRole("partner"), true);
  assert.equal(isAdminRole("partner"), false);
  assert.equal(isAdminRole("employee"), false);
});
