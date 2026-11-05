import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Проверяем реальный исходник: модуль собирается тем же способом, что и
// остальные тесты фронтенда (TypeScript → data:-URL).
async function load(path) {
  const source = await readFile(new URL(`../${path}`, import.meta.url), "utf8");
  const js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}

const headers = (values) => ({
  get(name) {
    const key = String(name || "").toLowerCase();
    for (const [k, v] of Object.entries(values)) {
      if (k.toLowerCase() === key) return v;
    }
    return null;
  },
});

const mod = await load("src/lib/request-origin.ts");

test("за прокси origin берётся из X-Forwarded-Host и X-Forwarded-Proto", () => {
  const url = mod.loginRedirectUrl({
    headers: headers({ "x-forwarded-host": "edu.каркастайги.рф", "x-forwarded-proto": "https", host: "frontend:3000" }),
    fallbackOrigin: "http://frontend:3000",
    next: "/admin/users?tab=partner",
  });
  // URL нормализует кириллический домен в punycode — для браузера это тот же адрес.
  assert.equal(url.origin, new URL("https://edu.каркастайги.рф").origin);
  assert.equal(url.pathname, "/login");
  assert.equal(url.searchParams.get("redirect"), "/admin/users?tab=partner");
});

test("без заголовков прокси остаётся собственный origin приложения", () => {
  const url = mod.loginRedirectUrl({
    headers: headers({ host: "lms.local" }),
    fallbackOrigin: "http://lms.local:3000",
    next: "/dashboard",
  });
  assert.equal(url.origin, "http://lms.local");
});

test("список из нескольких хостов и мусорные значения не уводят на чужой домен", () => {
  // Первое значение — то, что добавил прокси; остальное подделал клиент.
  const url = mod.loginRedirectUrl({
    headers: headers({ "x-forwarded-host": "edu.example.ru, evil.example", "x-forwarded-proto": "https" }),
    fallbackOrigin: "http://frontend:3000",
    next: "/modules",
  });
  assert.equal(url.origin, "https://edu.example.ru");

  for (const bad of ["https://evil.example/", "evil.example/path", "evil example", "javascript:alert(1)"]) {
    const guarded = mod.loginRedirectUrl({
      headers: headers({ "x-forwarded-host": bad, "x-forwarded-proto": "https" }),
      fallbackOrigin: "http://frontend:3000",
      next: "/modules",
    });
    assert.equal(guarded.origin, "https://frontend:3000", bad);
  }
});

test("недопустимая схема игнорируется", () => {
  const url = mod.loginRedirectUrl({
    headers: headers({ "x-forwarded-host": "edu.example.ru", "x-forwarded-proto": "javascript" }),
    fallbackOrigin: "https://edu.example.ru",
    next: "",
  });
  assert.equal(url.protocol, "https:");
  assert.equal(url.searchParams.get("redirect"), null);
});
