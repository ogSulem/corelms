import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

// Конфигурация сборки — такой же код, как и страницы: если её откатят,
// вернётся публичный `/_next/image` (CVE-2026-96889) и уязвимая версия Next.
const require = createRequire(import.meta.url);
const config = require("../next.config.js");

const readJson = async (relative) =>
  JSON.parse(await readFile(new URL(relative, import.meta.url), "utf8"));

const version = (text) =>
  String(text || "")
    .replace(/^[^\d]*/, "")
    .split(".")
    .map((part) => Number.parseInt(part, 10) || 0);

const atLeast = (actual, floor) => {
  const a = version(actual);
  const b = version(floor);
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    const left = a[index] ?? 0;
    const right = b[index] ?? 0;
    if (left !== right) return left > right;
  }
  return true;
};

test("оптимизатор картинок выключен: /_next/image не должен существовать", () => {
  assert.equal(config.images.unoptimized, true);
});

test("сервер не раскрывает версию фреймворка", () => {
  assert.equal(config.poweredByHeader, false);
});

test("next не ниже минимально безопасной версии", async () => {
  const pkg = await readJson("../package.json");
  assert.ok(atLeast(pkg.dependencies.next, "15.5.28"), `next ${pkg.dependencies.next}`);
  assert.ok(
    atLeast(pkg.devDependencies["eslint-config-next"], "15.5.28"),
    `eslint-config-next ${pkg.devDependencies["eslint-config-next"]}`,
  );
});

test("sharp в lockfile не ниже версии без CVE в libvips", async () => {
  const lock = await readFile(new URL("../yarn.lock", import.meta.url), "utf8");
  const matches = [...lock.matchAll(/^"?sharp@[^:\n]*"?:\n {2}version "([^"]+)"/gm)].map((m) => m[1]);
  assert.ok(matches.length > 0, "sharp не найден в yarn.lock");
  for (const found of matches) {
    assert.ok(atLeast(found, "0.35.5"), `sharp ${found}`);
  }
});
