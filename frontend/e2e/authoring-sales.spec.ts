import { test, expect, type BrowserContext } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import { createHash } from "node:crypto";

const enabled = process.env.E2E_ALLOW_MUTATIONS === "1" && !!process.env.E2E_PASSWORD && !!process.env.E2E_ADMIN_EMAIL && !!process.env.E2E_LEARNER_EMAIL;
test.skip(!enabled, "Run only on an explicitly disposable LMS; admin must be a test superadmin for Sales.");
let admin: BrowserContext, student: BrowserContext;
let moduleId: string, lessonId: string, errors: string[];
const base = () => `/admin/content/modules/${moduleId}`;
const file = (name: string) => path.join(__dirname, "fixtures", name);
async function api(method: string, url: string, data?: object, context = admin) {
  const response = await context.request.fetch(`/api/backend${url}`, { method, maxRetries: method === "GET" ? 2 : 0, ...(data ? { data } : {}) });
  expect(response.ok(), `${method} ${url}: ${await response.text()}`).toBeTruthy();
  return response.json();
}
async function state() { return api("GET", base()); }

test.beforeEach(async ({ browser, baseURL }) => {
  errors = []; admin = await browser.newContext({ baseURL }); student = await browser.newContext({ baseURL });
  for (const [context, email] of [[admin, process.env.E2E_ADMIN_EMAIL], [student, process.env.E2E_LEARNER_EMAIL]] as const) {
    expect((await context.request.post("/api/auth/login", { data: { email, password: process.env.E2E_PASSWORD } })).ok()).toBe(true);
  }
  const created = await api("POST", "/admin/content/modules", { title: `E2E Автор ${Date.now()}` }); moduleId = created.module.id;
  const added = await api("POST", `${base()}/lessons`, { revision: created.module.content_revision, title: "Консультация", content: "Сначала уточните задачу клиента, затем подготовьте предложение." });
  lessonId = added.lessons[0].id;
  await api("PATCH", base(), { revision: added.module.content_revision, is_active: true });
});
test.afterEach(async () => {
  if (moduleId && admin) { const current = await state(); await api("PATCH", base(), { revision: current.module.content_revision, is_archived: true }); }
  await admin?.close(); await student?.close(); expect(errors).toEqual([]);
});

test("one editor: legacy redirect, structured test, unsaved guard, learner grading and review", async () => {
  const page = await admin.newPage(); page.on("pageerror", e => errors.push(e.message));
  await page.goto(`/admin/modules?mid=${moduleId}&sid=${lessonId}`);
  await expect(page).toHaveURL(new RegExp(`/admin/modules/${moduleId}\\?tab=tests&lesson=`));
  await expect(page.getByRole("heading", { name: "Проверка знаний", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Добавить вопрос", exact: true }).click();
  await page.getByLabel("Формулировка вопроса 1", { exact: true }).fill("Что сначала уточняет консультант?");
  await page.getByLabel("Вопрос 1: вариант A", { exact: true }).fill("Задачу клиента");
  await page.getByLabel("Вопрос 1: вариант B", { exact: true }).fill("Цвет папки");
  await page.getByLabel("Вопрос 1: правильный вариант A", { exact: true }).check();
  await page.getByLabel(/^Объяснение/).fill("Сначала выясняют задачу, чтобы подобрать подходящий продукт.");
  await page.getByLabel(/^Требовать прохождение теста этого урока/).check();
  await page.getByLabel(/^Попытки/).fill("0");
  page.once("dialog", d => d.dismiss());
  await page.getByRole("button", { name: "Материалы", exact: true }).click();
  await expect(page.getByLabel("Формулировка вопроса 1", { exact: true })).toHaveValue("Что сначала уточняет консультант?");
  await page.getByRole("button", { name: "Сохранить тест", exact: true }).click();
  await expect.poll(async () => (await state()).lessons[0].requires_quiz).toBe(true);
  await expect(page.getByRole("button", { name: "Сохранить тест", exact: true })).toBeDisabled();
  const quizId = (await state()).lessons[0].quiz_id;
  const learner = await student.newPage(); learner.on("pageerror", e => errors.push(e.message));
  await learner.goto(`/modules/${moduleId}?lesson=${lessonId}`);
  await learner.getByRole("button", { name: "Я изучил материал", exact: true }).click();
  await learner.getByRole("button", { name: "Перейти к тесту", exact: true }).click();
  await learner.getByRole("button", { name: "Начать тест", exact: true }).click();
  await learner.getByRole("radio", { name: "A. Задачу клиента", exact: true }).check();
  await learner.getByRole("button", { name: "Завершить тест", exact: true }).first().click();
  await expect(learner.getByRole("heading", { name: "Тест пройден!", exact: true })).toBeVisible();
  await learner.getByRole("button", { name: "Посмотреть ответы", exact: true }).click();
  await expect(learner.getByText("Сначала выясняют задачу, чтобы подобрать подходящий продукт.", { exact: true })).toBeVisible();
  const latest = await api("GET", `/quizzes/${quizId}/attempts/latest`, undefined, student);
  expect(latest.can_review).toBe(true);
  await page.setViewportSize({ width: 320, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await learner.setViewportSize({ width: 320, height: 844 });
  expect(await learner.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("presentation: author and learner share material/text/files tabs and primary-file selection", async () => {
  const page = await admin.newPage(); page.on("pageerror", e => errors.push(e.message));
  await page.goto(`/admin/modules/${moduleId}?lesson=${lessonId}`);
  await page.getByLabel("Добавить файлы", { exact: true }).setInputFiles([file("guide.pdf"), file("calculation.xlsx")]);
  await expect.poll(async () => (await state()).assets.length).toBe(2);
  const assets = (await state()).assets;
  const excel = assets.find((a: { original_filename: string }) => a.original_filename === "calculation.xlsx");
  await page.getByRole("button", { name: "Редактировать", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Основной файл", { exact: true }).selectOption(excel.asset_id);
  await page.getByRole("dialog").getByRole("button", { name: "Предпросмотр урока", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("tab", { name: "Материал", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("dialog").getByRole("cell", { name: "=A2*B2", exact: true })).toBeVisible();
  await page.getByRole("dialog").getByLabel("Что открывать первым", { exact: true }).selectOption("text");
  await expect(page.getByRole("dialog").getByRole("tab", { name: "Текст урока", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("dialog").getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const learner = await student.newPage(); learner.on("pageerror", e => errors.push(e.message));
  await learner.goto(`/modules/${moduleId}?lesson=${lessonId}`);
  await expect(learner.getByRole("tab", { name: "Текст урока", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(learner.getByText("Сначала уточните задачу клиента, затем подготовьте предложение.", { exact: true })).toBeVisible();
  await learner.getByRole("tab", { name: "Материал", exact: true }).click();
  await expect(learner.getByLabel("Выбрать материал урока")).toHaveValue(excel.asset_id);
  await expect(learner.getByRole("cell", { name: "=A2*B2", exact: true })).toBeVisible();
  await expect(learner.getByText("Сначала уточните задачу клиента, затем подготовьте предложение.", { exact: true })).toBeHidden();
  await learner.getByRole("tab", { name: /^Все файлы/ }).click();
  await learner.getByRole("button", { name: /^guide.pdf/ }).click();
  await expect(learner.getByLabel("Выбрать материал урока")).not.toHaveValue(excel.asset_id);
  await learner.setViewportSize({ width: 320, height: 844 });
  expect(await learner.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("Sales: independent Sheets status, folders, immutable replacement, history and archive ACL", async () => {
  const page = await admin.newPage(); page.on("pageerror", e => errors.push(e.message));
  await page.goto("/sales");
  await expect(page.getByRole("heading", { name: "Материалы для продаж", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Фото", exact: true }).click();
  const folder = `E2E ${Date.now()}`;
  await page.getByRole("button", { name: "Новая папка", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Название", { exact: true }).fill(folder);
  await page.getByRole("dialog").getByRole("button", { name: "Сохранить", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(`^${folder}`) }).click();
  await expect(page).toHaveURL(new RegExp(`path=${encodeURIComponent(folder).replace(/%20/g, "(?:%20|\\+)")}`));
  await expect(page.getByLabel("Добавить файлы продаж", { exact: true })).toBeEnabled();
  const one = Buffer.from("Исходная версия документа"); const two = Buffer.from("Новая версия документа");
  await page.getByLabel("Добавить файлы продаж", { exact: true }).setInputFiles({ name: "инструкция.txt", mimeType: "text/plain", buffer: one });
  await expect(page.getByLabel("Действия с инструкция.txt", { exact: true })).toBeVisible();
  let listing = await api("GET", `/sales-files/list?section=photos&path=${encodeURIComponent(folder)}`);
  const entry = listing.entries[0]; const asset = entry.asset.asset_id;
  await page.getByLabel("Действия с инструкция.txt", { exact: true }).click();
  const choose = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Заменить файл", exact: true }).click();
  await (await choose).setFiles({ name: "other.txt", mimeType: "text/plain", buffer: two });
  await expect.poll(async () => (await api("GET", `/sales-files/list?section=photos&path=${encodeURIComponent(folder)}`)).entries[0].asset.version).toBe(2);
  await page.getByLabel("Действия с инструкция.txt", { exact: true }).click();
  await page.getByRole("button", { name: "История версий", exact: true }).click();
  await expect(page.getByRole("dialog").getByText("Версия 1", { exact: true })).toBeVisible();
  page.once("dialog", d => d.accept());
  await page.getByRole("dialog").getByRole("button", { name: "Восстановить", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const download = await student.request.get(`/api/backend/assets/${asset}/download`);
  expect(download.ok()).toBe(true); expect(await download.body()).toEqual(one);
  await page.getByLabel("Действия с инструкция.txt", { exact: true }).click(); page.once("dialog", d => d.accept());
  await page.getByRole("button", { name: "Переместить в архив", exact: true }).click();
  await expect(page.getByLabel("Действия с инструкция.txt", { exact: true })).toBeHidden();
  expect((await student.request.get(`/api/backend/assets/${asset}/download`)).status()).toBe(404);
  await page.getByLabel("Показывать архив", { exact: true }).check();
  page.once("dialog", d => d.accept()); await page.getByRole("button", { name: "Восстановить", exact: true }).click();
  await expect(page.getByLabel("Действия с инструкция.txt", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^инструкция.txt/ }).click();
  await expect(page.getByText("Исходная версия документа", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // Archive only the synthetic folder created by this test.
  listing = await api("GET", "/sales-files/list?section=photos");
  const parent = listing.entries.find((e: { name: string }) => e.name === folder);
  await api("PATCH", `/sales-files/entries/${parent.id}`, { revision: listing.revision, is_archived: true });
  expect((await student.request.get(`/api/backend/assets/${asset}/download`)).status()).toBe(404);
});

test("video: real worker creates a playable browser copy without changing original or module revision", async () => {
  test.setTimeout(120_000);
  const raw = fs.readFileSync(file("clip.avi"));
  const page = await admin.newPage(); page.on("pageerror", e => errors.push(e.message));
  await page.goto(`/admin/modules/${moduleId}?lesson=${lessonId}`);
  await page.getByLabel("Добавить файлы", { exact: true }).setInputFiles(file("clip.avi"));
  await expect.poll(async () => (await state()).assets.length).toBe(1);
  const workspace = await state(), asset = workspace.assets[0];
  await expect.poll(async () => (await api("GET", `/assets/${asset.asset_id}/viewer`)).state, { timeout: 75_000, intervals: [1000, 2000, 4000] }).toBe("ready");
  const learner = await student.newPage(); learner.on("pageerror", e => errors.push(e.message));
  await learner.goto(`/modules/${moduleId}?lesson=${lessonId}`);
  await expect(learner.locator("video")).toBeVisible();
  await expect.poll(() => learner.locator("video").evaluate((el: HTMLVideoElement) => el.readyState)).toBeGreaterThanOrEqual(2);
  await learner.locator("video").evaluate(async (el: HTMLVideoElement) => { el.muted = true; await el.play(); });
  await expect.poll(() => learner.locator("video").evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThan(0.1);
  const original = await student.request.get(`/api/backend/assets/${asset.asset_id}/download`);
  expect(createHash("sha256").update(await original.body()).digest("hex")).toBe(createHash("sha256").update(raw).digest("hex"));
  const after = await state();
  expect(after.assets[0].version).toBe(1); expect(after.assets[0].original_filename).toBe("clip.avi");
  expect(after.module.content_revision).toBe(workspace.module.content_revision);
});


test("Word: no public Office iframe, source download and explicit text fallback", async () => {
  const page = await admin.newPage(); page.on("pageerror", e => errors.push(e.message));
  await page.goto(`/admin/modules/${moduleId}?lesson=${lessonId}`);
  await page.getByLabel("Добавить файлы", { exact: true }).setInputFiles(file("guide.docx"));
  await expect.poll(async () => (await state()).assets.length).toBe(1);
  const asset = (await state()).assets[0];
  const learner = await student.newPage(); learner.on("pageerror", e => errors.push(e.message));
  await learner.goto(`/modules/${moduleId}?lesson=${lessonId}`);
  const text = learner.getByRole("button", { name: "Быстрый просмотр текста", exact: true });
  // A missing renderer remains usable; with LibreOffice a PDF can finish first.
  if (await text.isVisible()) {
    await text.click();
    await expect(learner.getByText("Инструкция с оформлением", { exact: true })).toBeVisible();
  } else {
    await expect(learner.getByRole("region", { name: "Просмотр: guide.docx", exact: true })).toBeVisible();
  }
  await expect(learner.locator('iframe[src*="officeapps"]')).toHaveCount(0);
  expect((await student.request.get(`/api/backend/assets/${asset.asset_id}/download`)).ok()).toBe(true);
  const downloading = learner.waitForEvent("download");
  await learner.getByRole("button", { name: "Скачать оригинал", exact: true }).click();
  const downloaded = await downloading;
  expect(downloaded.suggestedFilename()).toBe("guide.docx");
  expect(await downloaded.failure()).toBeNull();
  expect(fs.readFileSync((await downloaded.path())!)).toEqual(fs.readFileSync(file("guide.docx")));
});

test("Sheets UI: stale snapshot and source link are explicit, search also finds video categories", async () => {
  const page = await admin.newPage(); page.on("pageerror", e => errors.push(e.message));
  await page.route("**/api/backend/sales-links*", route => route.fulfill({ json: {
    status: "stale", last_success_at: "2026-10-20T12:00:00+00:00", warnings: ["Пропущена небезопасная ссылка."],
    source_url: "https://docs.google.com/spreadsheets/d/test/edit", message: "Показана последняя успешная копия.",
    blocks: [
      { id: "docs", title: "Документы", kind: "links", links: [{ title: "Каталог", url: "https://example.test/catalog" }] },
      { id: "video", title: "Обучающие видео", kind: "video", tabs: [{ id: "product", label: "Продукт", links: [{ title: "Знакомство", url: "https://example.test/video" }] }] },
    ],
  } }));
  await page.goto("/sales");
  await expect(page.getByText("Сохранённая копия Google Sheets", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Редактировать таблицу", exact: true })).toHaveAttribute("target", "_blank");
  await page.getByLabel("Поиск ссылок продаж", { exact: true }).fill("Продукт");
  await expect(page.getByRole("link", { name: /^Знакомство/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Каталог/ })).toBeHidden();
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
