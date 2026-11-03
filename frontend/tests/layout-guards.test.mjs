import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

// Разрешения экранов нельзя проверить без браузера, но два правила, которые
// ломали вёрстку, проверяются статически: элемент шире экрана обязан жить в
// собственной прокрутке, а модальное окно — не выше окна браузера.

const SRC = new URL("../src/", import.meta.url).pathname;

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.name.endsWith(".tsx")) yield full;
  }
}

/** Широкие фиксированные ширины (> 320px), у которых нет своей прокрутки. */
test("широкие элементы прокручиваются сами, а не растягивают страницу", async () => {
  const problems = [];
  for await (const file of walk(SRC)) {
    const source = await readFile(file, "utf8");
    const lines = source.split("\n");
    for (const match of source.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
      const classes = match[1] || match[2] || "";
      for (const width of classes.matchAll(/(?<![\w:-])(min-)?w-\[(\d+)px\]/g)) {
        if (Number(width[2]) <= 320) continue;
        const line = source.slice(0, match.index).split("\n").length - 1;
        // `max-w` ограничивает сверху и на телефоне безопасен.
        if (classes.includes(`max-${width[0]}`)) continue;
        const context = lines.slice(Math.max(0, line - 25), line + 3).join("\n");
        if (context.includes("overflow-x-auto") || context.includes("overflow-auto")) continue;
        problems.push(`${path.relative(SRC, file)}:${line + 1} ${width[0]}`);
      }
    }
  }
  assert.deepEqual(problems, [], `эти элементы шире телефона без своей прокрутки:\n${problems.join("\n")}`);
});

/** Каждая таблица должна быть в контейнере с горизонтальной прокруткой. */
test("таблицы не выносят горизонтальный скролл на страницу", async () => {
  const problems = [];
  for await (const file of walk(SRC)) {
    const source = await readFile(file, "utf8");
    const lines = source.split("\n");
    lines.forEach((line, index) => {
      if (!line.includes("<table")) return;
      const before = lines.slice(Math.max(0, index - 4), index).join("\n");
      const inline = line;
      const wrapper = `${before}${inline}`;
      if (wrapper.includes("overflow-x-auto") || wrapper.includes("overflow-auto")) return;
      problems.push(`${path.relative(SRC, file)}:${index + 1}`);
    });
  }
  assert.deepEqual(problems, [], `таблица без overflow-x-auto:\n${problems.join("\n")}`);
});

test("модальное окно не выше и не шире экрана", async () => {
  const source = await readFile(new URL("../src/components/ui/modal.tsx", import.meta.url), "utf8");
  assert.match(source, /max-h-\[calc\(100dvh-/, "высота модалки должна считаться от 100dvh");
  assert.match(source, /max-w-\[min\(96vw/, "ширина модалки должна ограничиваться 96vw");
  assert.match(source, /overflow-auto/, "содержимое модалки должно прокручиваться внутри");
});

test("страница не задаёт фиксированную ширину на весь viewport", async () => {
  const problems = [];
  for await (const file of walk(SRC)) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(/(?<![\w:-])w-screen(?![-\w])/g)) {
      problems.push(`${path.relative(SRC, file)}:${source.slice(0, match.index).split("\n").length}`);
    }
  }
  assert.deepEqual(problems, [], `w-screen даёт горизонтальный скролл из-за полосы прокрутки:\n${problems.join("\n")}`);
});

test("разделы админ-центра переносятся, а не уезжают за экран телефона", async () => {
  const source = await readFile(new URL("../src/components/admin/admin-nav.tsx", import.meta.url), "utf8");
  assert.match(source, /flex flex-wrap/, "четыре раздела должны переноситься на новую строку");
  assert.doesNotMatch(source, /flex-nowrap/, "на 320 px перенос обязателен");
  for (const href of ["/admin/modules", "/admin/users", "/admin/analytics", "/admin/settings"]) {
    assert.ok(source.includes(href), `раздел ${href} пропал из навигации`);
  }
});

test("ссылка «обновить существующий модуль» ведёт прямо на вкладку импорта", async () => {
  const editor = await readFile(new URL("../src/components/admin/module-editor.tsx", import.meta.url), "utf8");
  assert.match(editor, /requestedTab === "import"/, "редактор должен открываться на ?tab=import");
  const admin = await readFile(new URL("../src/components/admin/import-admin.tsx", import.meta.url), "utf8");
  assert.match(admin, /\?tab=import/, "после конфликта названий нужна ссылка на обновление модуля");
  assert.match(admin, /module_already_exists/, "конфликт названий обрабатывается отдельно от прочих ошибок");
});

test("температура и таймаут AI правятся из админки, а не только в .env", async () => {
  const page = await readFile(new URL("../src/app/admin/settings/page.tsx", import.meta.url), "utf8");
  assert.match(page, /Температура/, "поле температуры должно быть на экране настроек");
  assert.match(page, /Таймаут ответа/, "поле таймаута должно быть на экране настроек");
  assert.match(page, /temperature: tempValue/, "PUT /admin/settings/ai должен отправлять температуру");
  assert.match(page, /request_timeout: timeoutValue/, "PUT /admin/settings/ai должен отправлять таймаут");
});
