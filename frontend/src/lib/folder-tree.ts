/**
 * Каталоги материалов не хранятся отдельными записями: ZIP-импорт сохраняет путь файла
 * (`Папка/Подпапка/файл.pdf`), поэтому дерево строится из `original_filename`.
 * Один и тот же код используют и ученик, и редактор модуля — иначе структура «пропадает» в админке.
 */

export type NamedFile = { original_filename: string };

/** Путь файла сегментами: `Папка\\Файл.pdf` и `Папка/Файл.pdf` дают одно дерево. */
export function splitPath(name: string): string[] {
  // Разделитель меняем через split/join: `String.prototype.replaceAll` нет в
  // старых WebView (iOS < 13.4), а путь строится в том числе на телефонах.
  return String(name || "").split("\\").join("/").split("/").filter(Boolean);
}

/** Имя файла без каталогов. */
export function baseName(name: string): string {
  const parts = splitPath(name);
  return (parts.length ? parts[parts.length - 1] : "") || String(name || "");
}

/** Каталоги, в которых лежит файл (пустой массив — корень). */
export function folderPath(name: string): string[] {
  return splitPath(name).slice(0, -1);
}

/** Уникальные каталоги, в которых есть файлы: нужны для навигации и счётчиков. */
export function folderSummary<T extends NamedFile>(materials: T[]): { path: string[]; count: number }[] {
  const counts = new Map<string, { path: string[]; count: number }>();
  for (const asset of materials) {
    const parts = splitPath(asset.original_filename);
    for (let depth = 1; depth < parts.length; depth += 1) {
      const path = parts.slice(0, depth);
      const key = path.join("/");
      const entry = counts.get(key);
      if (entry) entry.count += 1;
      else counts.set(key, { path, count: 1 });
    }
  }
  return [...counts.values()].sort((a, b) => a.path.join("/").localeCompare(b.path.join("/"), "ru", { numeric: true }));
}

/**
 * Содержимое текущего каталога: подпапки и файлы.
 * При поиске дерево игнорируется и показываются все совпадения с полным путём.
 */
export function browseMaterials<T extends NamedFile>(materials: T[], path: string[], query = ""): { folders: string[]; files: T[] } {
  const needle = query.trim().toLocaleLowerCase("ru");
  if (needle) {
    return { folders: [], files: materials.filter(asset => asset.original_filename.toLocaleLowerCase("ru").includes(needle)) };
  }
  const folders = new Set<string>();
  const files: T[] = [];
  for (const asset of materials) {
    const parts = splitPath(asset.original_filename);
    if (!path.every((segment, index) => parts[index] === segment)) continue;
    if (parts.length > path.length + 1) folders.add(parts[path.length]);
    else files.push(asset);
  }
  return { folders: [...folders].sort((a, b) => a.localeCompare(b, "ru", { numeric: true })), files };
}
