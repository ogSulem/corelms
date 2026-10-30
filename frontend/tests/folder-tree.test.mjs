import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import test from "node:test";
import ts from "typescript";

// Тот же приём, что и в auth-and-api: проверяем реальный исходник без отдельного сборщика.
async function loadSource(path) {
  const source = await readFile(new URL(`../${path}`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(`${source}\n// isolated ${randomUUID()}`, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const files = [
  { asset_id: "1", original_filename: "Регламент.pdf" },
  { asset_id: "2", original_filename: "Производство/Инструкция.docx" },
  { asset_id: "3", original_filename: "Производство\\Сварка/Схема.png" },
  { asset_id: "4", original_filename: "Производство/Сварка/ГОСТ.pdf" },
  { asset_id: "5", original_filename: "_module/Шаблон.xlsx" },
];

test("путь файла разбирается одинаково для слэшей и обратных слэшей", async () => {
  const { splitPath, baseName, folderPath } = await loadSource("src/lib/folder-tree.ts");
  assert.deepEqual(splitPath("Производство\\Сварка/Схема.png"), ["Производство", "Сварка", "Схема.png"]);
  assert.equal(baseName("Производство/Сварка/Схема.png"), "Схема.png");
  assert.deepEqual(folderPath("Производство/Сварка/Схема.png"), ["Производство", "Сварка"]);
  assert.deepEqual(folderPath("Регламент.pdf"), []);
  assert.deepEqual(splitPath("//Двойной//Путь//"), ["Двойной", "Путь"]);
});

test("обозреватель показывает каталоги там же, где их видит ученик", async () => {
  const { browseMaterials } = await loadSource("src/lib/folder-tree.ts");
  const root = browseMaterials(files, [], "");
  assert.deepEqual(root.folders, ["_module", "Производство"]);
  assert.deepEqual(root.files.map(f => f.asset_id), ["1"]);

  const production = browseMaterials(files, ["Производство"], "");
  assert.deepEqual(production.folders, ["Сварка"]);
  assert.deepEqual(production.files.map(f => f.asset_id), ["2"]);

  const welding = browseMaterials(files, ["Производство", "Сварка"], "");
  assert.deepEqual(welding.folders, []);
  assert.deepEqual(welding.files.map(f => f.asset_id), ["3", "4"]);

  // Пустой каталог не «протекает» файлами соседних папок.
  assert.deepEqual(browseMaterials(files, ["Производство", "Сварка", "Нет такой"], "").files, []);
});

test("поиск игнорирует дерево и показывает файл с полным путём", async () => {
  const { browseMaterials } = await loadSource("src/lib/folder-tree.ts");
  const found = browseMaterials(files, ["Производство"], "схема");
  assert.deepEqual(found.folders, []);
  assert.deepEqual(found.files.map(f => f.asset_id), ["3"]);
  assert.deepEqual(browseMaterials(files, [], "ГОСТ").files.map(f => f.asset_id), ["4"]);
  assert.deepEqual(browseMaterials(files, [], "ничего").files, []);
});

test("счётчики каталогов учитывают вложенные файлы", async () => {
  const { folderSummary } = await loadSource("src/lib/folder-tree.ts");
  const summary = folderSummary(files);
  assert.deepEqual(summary.map(entry => [entry.path.join("/"), entry.count]), [
    ["_module", 1],
    ["Производство", 3],
    ["Производство/Сварка", 2],
  ]);
});
