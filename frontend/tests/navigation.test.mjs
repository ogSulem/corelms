import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import test from "node:test";
import ts from "typescript";

// Навигация — обычный модуль без React, поэтому проверяем её напрямую.
async function loadNavigation() {
  const source = await readFile(new URL("../src/lib/navigation.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(`${source}\n// ${randomUUID()}`, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

test("меню на телефоне: все пункты и короткие подписи", async () => {
  const { navItemsFor, ADMIN_NAV_ITEM, MOBILE_LABEL_MAX, NAV_ITEMS } = await loadNavigation();

  // Партнёр и админ видят ровно те пункты, которые есть на телефоне.
  assert.equal(navItemsFor("partner").length, 4);
  assert.equal(navItemsFor("admin").length, 5);
  assert.equal(navItemsFor("superadmin").length, 5);
  assert.ok(navItemsFor("admin").some((item) => item.href === ADMIN_NAV_ITEM.href));

  // Раньше «Админ‑центр» не помещался в шапку и уезжал за край экрана.
  for (const item of [...NAV_ITEMS, ADMIN_NAV_ITEM]) {
    assert.ok(
      item.short.length <= MOBILE_LABEL_MAX,
      `подпись «${item.short}» длиннее ${MOBILE_LABEL_MAX} символов и не влезет в ячейку нижней панели`
    );
    assert.ok(item.label.length > 0);
  }

  const hrefs = [...NAV_ITEMS, ADMIN_NAV_ITEM].map((item) => item.href);
  assert.equal(new Set(hrefs).size, hrefs.length, "пункты меню не должны повторяться");
});

test("подсветка активного пункта меню", async () => {
  const { isNavItemActive } = await loadNavigation();

  assert.equal(isNavItemActive("/dashboard", "/dashboard"), true);
  assert.equal(isNavItemActive("/dashboard/extra", "/dashboard"), true);
  assert.equal(isNavItemActive("/modules", "/dashboard"), false);
  // «Обучение» не должно загораться на странице урока другого раздела.
  assert.equal(isNavItemActive("/submodules/abc", "/modules"), false);
  // «Админ‑центр» активен во всех админ-разделах, включая редактор модуля.
  assert.equal(isNavItemActive("/admin/users", "/admin/modules"), true);
  assert.equal(isNavItemActive("/admin/settings", "/admin/modules"), true);
  assert.equal(isNavItemActive("/admin", "/admin/modules"), true);
  assert.equal(isNavItemActive("/modules/123", "/admin/modules"), false);
});
