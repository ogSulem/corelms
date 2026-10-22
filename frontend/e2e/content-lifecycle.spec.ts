import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import path from "node:path";

const allowed = process.env.E2E_ALLOW_MUTATIONS === "1";
const password = process.env.E2E_PASSWORD || "";
const adminEmail = process.env.E2E_ADMIN_EMAIL || "";
const learnerEmail = process.env.E2E_LEARNER_EMAIL || "";
const fixture = (name: string) => path.join(__dirname, "fixtures", name);
const backend = (url: string) => `/api/backend${url}`;

test.skip(!allowed || !password || !adminEmail || !learnerEmail,
  "Only run against a disposable LMS with explicit E2E_ALLOW_MUTATIONS=1 and test accounts.");

let admin: BrowserContext;
let learner: BrowserContext;
let moduleId: string;
let lessonId: string;
let title: string;
let pageErrors: string[];
const base = () => `/admin/content/modules/${moduleId}`;
async function api(method: string, url: string, data?: object, context = admin) {
  const response = await context.request.fetch(backend(url), { method, maxRetries: method === "GET" ? 2 : 0, ...(data ? { data } : {}) });
  expect(response.ok(), `${method} ${url}: ${await response.text()}`).toBeTruthy();
  return response.json();
}
async function workspace() { return api("GET", base()); }
async function editorPage() {
  const page = await admin.newPage();
  page.on("pageerror", e => pageErrors.push(e.message));
  await page.goto("/admin/modules");
  await page.getByRole("link", { name: title, exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  return page;
}
async function lessonPage() {
  const page = await learner.newPage();
  page.on("pageerror", e => pageErrors.push(e.message));
  await page.goto(`/modules/${moduleId}?lesson=${lessonId}`);
  await expect(page.getByRole("heading", { name: "Урок", exact: true })).toBeVisible();
  return page;
}
async function menu(page: Page, filename: string, action: string) {
  await page.getByLabel(`Действия с ${filename}`, { exact: true }).click();
  await page.getByRole("button", { name: action, exact: true }).click();
}

test.beforeEach(async ({ browser, baseURL }) => {
  pageErrors = [];
  admin = await browser.newContext({ baseURL });
  learner = await browser.newContext({ baseURL });
  for (const [context, email] of [[admin, adminEmail], [learner, learnerEmail]] as const) {
    const login = await context.request.post("/api/auth/login", { data: { email, password } });
    expect(login.status()).toBe(200);
  }
  title = `АВТОПРОВЕРКА · ${Date.now()}`;
  const created = await api("POST", "/admin/content/modules", { title, description: "Изолированный браузерный тест" });
  moduleId = created.module.id;
  const state = await api("POST", `${base()}/lessons`, { revision: created.module.content_revision, title: "Урок", content: "Изучите материал и подтвердите прочтение." });
  lessonId = state.lessons[0].id;
  await api("PATCH", base(), { revision: state.module.content_revision, is_active: true });
});

test.afterEach(async () => {
  if (moduleId && admin) {
    const current = await workspace();
    await api("PATCH", base(), { revision: current.module.content_revision, is_archived: true });
  }
  await admin?.close();
  await learner?.close();
  expect(pageErrors).toEqual([]);
});

test("files: XLSX preview, versions, archive, real ZIP job and earned progress", async () => {
  const editor = await editorPage();
  await editor.getByRole("button", { name: "Материал: Урок", exact: true }).click();
  await editor.getByLabel("Добавить файлы", { exact: true }).setInputFiles(fixture("calculation.xlsx"));
  await expect(editor.getByLabel("Действия с calculation.xlsx", { exact: true })).toBeVisible();
  const originalAsset = (await workspace()).assets[0].asset_id;

  const student = await lessonPage();
  await student.getByRole("button", { name: "Я изучил материал", exact: true }).click();
  await expect(student.getByText("Обучение завершено", { exact: true })).toBeVisible();
  await expect(student.getByRole("tab", { name: "Материал", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(student.getByRole("cell", { name: "=A2*B2", exact: true })).toBeVisible();
  await expect(student.locator('iframe[src*="office"]')).toHaveCount(0);
  await student.getByLabel("Лист таблицы").selectOption("1");
  await expect(student.getByRole("cell", { name: "Тестовый файл: только чтение", exact: true })).toBeVisible();
  // A background refresh must not close a file that someone is reading.
  await student.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(student.getByLabel("Лист таблицы")).toHaveValue("1");

  await editor.getByLabel("Действия с calculation.xlsx", { exact: true }).click();
  const choose = editor.waitForEvent("filechooser");
  await editor.getByRole("button", { name: "Заменить файл", exact: true }).click();
  await (await choose).setFiles(fixture("calculation.xlsx"));
  await expect.poll(async () => (await workspace()).assets[0].version).toBe(2);
  await menu(editor, "calculation.xlsx", "История версий");
  await expect(editor.getByRole("dialog").getByText("Версия 1", { exact: true })).toBeVisible();
  editor.once("dialog", dialog => dialog.accept());
  await editor.getByRole("dialog").getByRole("button", { name: "Восстановить", exact: true }).click();
  await expect(editor.getByRole("dialog")).toBeHidden();
  await expect.poll(async () => (await workspace()).assets[0].version).toBe(3);

  await menu(editor, "calculation.xlsx", "Переместить в архив");
  await editor.getByRole("dialog").getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(editor.getByLabel("Действия с calculation.xlsx", { exact: true })).toBeHidden();
  await editor.getByRole("button", { name: /^Архив/ }).click();
  await editor.getByRole("button", { name: "Восстановить calculation.xlsx", exact: true }).click();
  await expect.poll(async () => (await workspace()).assets[0].is_archived).toBe(false);
  await editor.getByRole("button", { name: "Материалы", exact: true }).click();
  await menu(editor, "calculation.xlsx", "Переименовать");
  await editor.getByRole("dialog").getByLabel("Имя файла с расширением").fill("Расчёт.xlsx");
  await editor.getByRole("dialog").getByRole("button", { name: "Сохранить", exact: true }).click();
  await menu(editor, "Расчёт.xlsx", "Переместить");
  await editor.getByLabel("Куда переместить").selectOption("");
  await editor.getByRole("dialog").getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect.poll(async () => (await workspace()).assets[0].submodule_id).toBeNull();
  expect((await workspace()).assets[0].asset_id).toBe(originalAsset);

  // Delay only status delivery, not the actual RQ worker, then type a draft
  // while its successful result is waiting. The draft must survive the refresh.
  const beforeImport = await workspace();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await editor.route(/\/api\/backend\/admin\/jobs\/[a-f0-9-]+$/, async route => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  await editor.getByRole("button", { name: "Обновить из ZIP", exact: true }).click();
  await editor.getByLabel("ZIP для обновления модуля").setInputFiles(fixture("update.zip"));
  await editor.getByRole("button", { name: "Обновить этот модуль", exact: true }).click();
  await expect(editor.getByRole("button", { name: "Настройки и доступ", exact: true })).toBeEnabled();
  await editor.getByRole("button", { name: "Настройки и доступ", exact: true }).click();
  await editor.getByLabel("Название", { exact: true }).fill("Несохранённый черновик");
  release();
  await expect(editor.getByText(new RegExp(`Редакция ${beforeImport.module.content_revision + 1} ·`))).toBeVisible({ timeout: 40_000 });
  await expect(editor.getByLabel("Название", { exact: true })).toHaveValue("Несохранённый черновик");
  const progress = await api("GET", `/progress/modules/${moduleId}`, undefined, learner);
  expect(progress.completed).toBe(true);
  expect(progress.current_completed).toBe(false);
  const after = await workspace();
  expect(after.lessons.find((l: { title: string }) => l.title === "Урок").id).toBe(lessonId);
  expect(after.lessons.find((l: { title: string }) => l.title === "Дополнение").requires_quiz).toBe(false);
  expect(after.assets.some((a: { asset_id: string }) => a.asset_id === originalAsset)).toBe(true);
  expect(after.module.is_active).toBe(true);
  expect(after.module.import_object_key).toMatch(/\/_sources\/[a-f0-9]+\.zip$/);
  // Dismiss a navigation confirmation: the draft and the URL stay intact.
  editor.once("dialog", dialog => dialog.dismiss());
  await editor.getByRole("link", { name: "Все модули", exact: true }).click();
  await expect(editor).toHaveURL(new RegExp(`/admin/modules/${moduleId}$`));
  await expect(editor.getByLabel("Название", { exact: true })).toHaveValue("Несохранённый черновик");
  editor.once("dialog", dialog => dialog.dismiss());
  await editor.goBack();
  await expect(editor).toHaveURL(new RegExp(`/admin/modules/${moduleId}$`));
  await expect(editor.getByLabel("Название", { exact: true })).toHaveValue("Несохранённый черновик");
  let logoutRequests = 0;
  editor.on("request", request => { if (request.url().endsWith("/api/auth/logout")) logoutRequests++; });
  editor.once("dialog", dialog => dialog.dismiss());
  await editor.getByRole("button", { name: "Выйти", exact: true }).click();
  expect(logoutRequests).toBe(0);
  editor.once("dialog", dialog => dialog.accept());
  await editor.getByRole("button", { name: "Обновить данные модуля" }).click();
  await expect(editor.getByLabel("Название", { exact: true })).toHaveValue(title);
});

test("quiz: multiselect, reload/resume and retry after a lost committed response", async () => {
  let state = await workspace();
  let quizId = state.lessons[0].quiz_id;
  for (const question of [
    { type: "single", prompt: "Выберите ответ\nA) Правильно\nB) Неправильно", correct_answer: "A" },
    { type: "multi", prompt: "Выберите оба признака\nA) Первый верный\nB) Неверный\nC) Второй верный", correct_answer: "A,C" },
  ]) {
    const added = await api("POST", "/admin/questions", { quiz_id: quizId, ...question });
    quizId = added.quiz_id;
  }
  state = await workspace();
  await api("PATCH", `${base()}/lessons/${lessonId}`, { revision: state.module.content_revision, requires_quiz: true });
  const page = await lessonPage();
  await page.getByRole("button", { name: "Я изучил материал", exact: true }).click();
  await page.getByRole("button", { name: "Перейти к тесту", exact: true }).click();
  await page.getByRole("button", { name: "Начать тест", exact: true }).click();
  await page.getByRole("radio", { name: "A. Правильно", exact: true }).check();
  await page.getByRole("checkbox", { name: "A. Первый верный", exact: true }).check();
  await page.getByRole("checkbox", { name: "C. Второй верный", exact: true }).check();
  await expect(page.getByRole("button", { name: "Завершить тест", exact: true }).first()).toBeEnabled();
  await page.getByRole("checkbox", { name: "A. Первый верный", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "C. Второй верный", exact: true }).uncheck();
  await expect(page.getByRole("button", { name: "Завершить тест", exact: true }).first()).toBeDisabled();
  await page.getByRole("checkbox", { name: "A. Первый верный", exact: true }).check();
  await page.getByRole("checkbox", { name: "C. Второй верный", exact: true }).check();
  page.once("dialog", dialog => dialog.accept());
  await page.reload();
  await page.getByRole("button", { name: "Продолжить попытку", exact: true }).click();
  await expect(page.getByRole("radio", { name: "A. Правильно", exact: true })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "C. Второй верный", exact: true })).toBeChecked();
  let calls = 0;
  let replayed: boolean | undefined;
  await page.route("**/api/backend/quizzes/*/submit", async route => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    if (++calls === 1) await route.abort("failed");
    else { replayed = (await response.json()).replayed; await route.fulfill({ response }); }
  });
  await page.getByRole("button", { name: "Завершить тест", exact: true }).first().click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Завершить тест", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Тест пройден!", exact: true })).toBeVisible();
  expect(calls).toBe(2);
  expect(replayed).toBe(true);
  expect((await api("GET", `/progress/modules/${moduleId}`, undefined, learner)).completed).toBe(true);
});

test("mobile layout, keyboard dialogs, corrupt-file fallback and private links", async () => {
  const editor = await editorPage();
  await editor.setViewportSize({ width: 390, height: 844 });
  expect(await editor.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await editor.getByRole("button", { name: "Добавить урок", exact: true }).click();
  await editor.getByRole("dialog").getByLabel("Название", { exact: true }).fill("Черновик урока");
  editor.once("dialog", dialog => dialog.dismiss());
  await editor.keyboard.press("Escape");
  await expect(editor.getByRole("dialog").getByLabel("Название", { exact: true })).toHaveValue("Черновик урока");
  await editor.keyboard.press("Tab");
  expect(await editor.getByRole("dialog").evaluate(el => el.contains(document.activeElement))).toBe(true);
  editor.once("dialog", dialog => dialog.accept());
  await editor.getByRole("dialog").getByRole("button", { name: "Отмена", exact: true }).click();
  await editor.getByLabel("Добавить файлы", { exact: true }).setInputFiles({ name: "broken.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("not a workbook") });
  await editor.getByRole("button", { name: /^broken.xlsx/ }).click();
  await expect(editor.getByRole("alert")).toBeVisible();
  await expect(editor.getByRole("button", { name: "Скачать файл", exact: true })).toBeVisible();

  const student = await lessonPage();
  await student.setViewportSize({ width: 390, height: 844 });
  expect(await student.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(student.getByRole("navigation", { name: "Содержание модуля" })).toBeHidden();
  await student.getByRole("button", { name: "Открыть", exact: true }).click();
  await expect(student.getByRole("navigation", { name: "Содержание модуля" })).toBeVisible();
  const state = await workspace();
  await api("PATCH", base(), { revision: state.module.content_revision, is_active: false });
  const denied = await learner.request.get(backend(`/assets/${state.assets[0].asset_id}/preview`));
  expect(denied.status()).toBe(404);
  await student.reload();
  await expect(student.getByRole("heading", { name: "Модуль недоступен", exact: true })).toBeVisible();
});

test("PDF: authenticated stream, byte ranges, native viewer or explicit fallback", async () => {
  const editor = await editorPage();
  await editor.getByLabel("Добавить файлы", { exact: true }).setInputFiles(fixture("guide.pdf"));
  await expect(editor.getByLabel("Действия с guide.pdf", { exact: true })).toBeVisible();
  const asset = (await workspace()).assets[0];
  const range = await learner.request.get(backend(`/assets/${asset.asset_id}/stream`), { headers: { Range: "bytes=0-7" } });
  expect(range.status()).toBe(206);
  expect(range.headers()["content-type"]).toBe("application/pdf");
  expect(range.headers()["x-frame-options"]).toBe("SAMEORIGIN");
  expect(range.headers()["content-security-policy"]).not.toContain("sandbox");
  expect((await range.body()).toString()).toBe("%PDF-1.4");
  const student = await lessonPage();
  await student.goto(`/modules/${moduleId}`);
  await student.getByRole("button", { name: /^guide.pdf/ }).click();
  if (await student.evaluate(() => navigator.pdfViewerEnabled !== false)) {
    await expect(student.getByTitle("PDF: guide.pdf", { exact: true })).toBeVisible();
  } else {
    await expect(student.getByText(/Встроенный просмотр PDF в этом браузере недоступен/)).toBeVisible();
  }
  await expect(student.getByRole("button", { name: "Скачать оригинал", exact: true })).toBeVisible();
  const original = await api("GET", `/assets/${asset.asset_id}/presign-download?action=download`, undefined, learner);
  expect(original.download_url).toContain("response-content-disposition");
});

test("lesson text history restores a new protected version without losing concurrent settings", async () => {
  const initial = await workspace();
  const originalText = initial.lessons[0].content;
  const editor = await editorPage();
  await editor.getByRole("button", { name: "Материал: Урок", exact: true }).click();
  await editor.getByRole("button", { name: "Редактировать", exact: true }).click();
  await editor.getByRole("dialog").getByLabel(/Текст урока/).fill("# Ручная инструкция\n\nНе заменять при ZIP-обновлении.");
  await expect(editor.getByText("Текст защищён от замены при импорте", { exact: true })).toBeVisible();
  await editor.getByRole("dialog").getByRole("button", { name: "Сохранить", exact: true }).click();
  await editor.getByRole("button", { name: "История текста · v2", exact: true }).click();
  await editor.getByRole("button", { name: /Версия 1/ }).click();
  await expect(editor.getByRole("dialog").getByText(originalText, { exact: true })).toHaveText(originalText);
  editor.once("dialog", dialog => dialog.accept());
  await editor.getByRole("button", { name: "Восстановить версию 1", exact: true }).click();
  await expect(editor.getByRole("dialog")).toHaveCount(0);
  const restored = await workspace();
  expect(restored.lessons[0].content).toBe(originalText);
  expect(restored.lessons[0].content_version).toBe(3);
  expect(restored.lessons[0].content_mode).toBe("manual");

  // A save from an old tab must not overwrite the title changed elsewhere.
  await editor.getByRole("button", { name: "Редактировать", exact: true }).click();
  await editor.getByRole("dialog").getByLabel("Название", { exact: true }).fill("Название из старой вкладки");
  await api("PATCH", `${base()}/lessons/${lessonId}`, { revision: restored.module.content_revision, title: "Название из другой вкладки" });
  await editor.getByRole("dialog").getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(editor.getByRole("dialog").getByRole("alert")).toBeVisible();
  expect((await workspace()).lessons[0].title).toBe("Название из другой вкладки");
});

test("library avoids legacy polling; dashboard chooses an actual next step; mobile FAQ is readable", async () => {
  const page = await admin.newPage();
  const requests: string[] = [];
  page.on("request", request => requests.push(new URL(request.url()).pathname));
  await page.goto("/admin/modules");
  await expect(page.getByRole("heading", { name: "Библиотека модулей", exact: true })).toBeVisible();
  await page.getByLabel("Поиск модулей", { exact: true }).fill(title);
  await expect(page.getByRole("link", { name: title, exact: true })).toBeVisible();
  expect(requests.some(path => /\/admin\/(model|jobs|users|runtime)/.test(path))).toBe(false);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto("/faq");
  await page.getByLabel("Поиск по справке", { exact: true }).fill("перезапишет");
  const question = page.locator("summary").filter({ hasText: "Перезапишет ли импорт текст, который я отредактировал?" });
  await question.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("details[open]")).toContainText("защищён");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  await api("POST", `/modules/${moduleId}/open`, {}, learner);
  const student = await learner.newPage();
  await student.goto("/dashboard");
  const next = student.getByRole("region", { name: "Следующий шаг обучения" });
  await expect(next.getByRole("link", { name: "Открыть урок", exact: true })).toHaveAttribute("href", `/modules/${moduleId}?lesson=${lessonId}`);
  await expect(next.getByRole("heading", { name: title, exact: true })).toBeVisible();
  await student.setViewportSize({ width: 390, height: 844 });
  expect(await student.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await student.setViewportSize({ width: 320, height: 844 });
  expect(await student.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await student.goto("/modules");
  await expect(student.getByRole("heading", { name: title.toUpperCase(), exact: true })).toBeVisible();
  await student.getByLabel("Поиск модулей", { exact: true }).fill(title);
  const status = student.getByRole("status", { name: "Статус модуля" });
  await expect(status).toHaveText("НЕ НАЧАТО");
  const box = await status.boundingBox();
  expect(box!.x + box!.width).toBeLessThanOrEqual(320);
  await student.getByLabel("Поиск модулей", { exact: true }).fill("нет-такого-модуля-" + Date.now());
  await expect(student.getByRole("heading", { name: "Ничего не найдено", exact: true })).toBeVisible();
  await student.getByRole("button", { name: "Сбросить поиск", exact: true }).click();
  await expect(student.getByRole("heading", { name: title.toUpperCase(), exact: true })).toBeVisible();
});

test("same-browser sessions remain independent; revoked credentials and foreign-origin logout cannot succeed", async ({ browser }) => {
  const first = await browser.newContext({ baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000", userAgent: "CoreLMS browser regression" });
  const second = await browser.newContext({ baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000", userAgent: "CoreLMS browser regression" });
  try {
    for (const context of [first, second]) {
      expect((await context.request.post("/api/auth/login", { data: { email: process.env.E2E_LEARNER_EMAIL, password: process.env.E2E_PASSWORD } })).ok()).toBe(true);
    }
    const firstSessions = await api("GET", "/auth/sessions", undefined, first);
    const secondSessions = await api("GET", "/auth/sessions", undefined, second);
    const a = firstSessions.items.find((s: { current: boolean }) => s.current);
    const b = secondSessions.items.find((s: { current: boolean }) => s.current);
    expect(a.session_id).not.toBe(b.session_id);
    expect(a.user_agent).toBe("CoreLMS browser regression");
    expect((await first.request.post("/api/auth/logout", { headers: { Origin: "https://untrusted.invalid" } })).status()).toBe(403);
    expect((await first.request.get("/api/auth/me")).ok()).toBe(true);
    await api("POST", "/auth/sessions/revoke", { session_id: b.session_id }, first);
    const revoked = await second.request.get("/api/auth/me");
    expect((await revoked.json()).authenticated).toBe(false);
    expect((await first.request.get("/api/auth/me")).ok()).toBe(true);
    expect((await first.request.post("/api/auth/logout")).ok()).toBe(true);
    expect((await (await first.request.get("/api/auth/me")).json()).authenticated).toBe(false);
  } finally { await first.close(); await second.close(); }
});

test("first-login password change keeps this device, revokes the other device and permits the new password", async ({ browser }) => {
  const email = `e2e-password-${Date.now()}@example.test`;
  const created = await api("POST", "/admin/users", { name: `E2E Password ${Date.now()}`, email, password: process.env.E2E_PASSWORD, must_change_password: true });
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000" });
  const other = await browser.newContext({ baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000" });
  try {
    for (const device of [context, other]) {
      expect((await device.request.post("/api/auth/login", { data: { email, password: process.env.E2E_PASSWORD } })).ok()).toBe(true);
    }
    const page = await context.newPage();
    await page.goto("/force-password-change");
    await page.getByLabel("Текущий пароль", { exact: true }).fill(process.env.E2E_PASSWORD!);
    const newPassword = "E2e-Changed-" + Date.now();
    await page.getByLabel("Новый пароль", { exact: true }).fill(newPassword);
    await page.getByLabel("Подтверждение пароля", { exact: true }).fill(newPassword);
    await page.getByLabel("Номер телефона", { exact: true }).fill("+48123456789");
    await page.getByRole("button", { name: "Сменить пароль", exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("region", { name: "Следующий шаг обучения" })).toBeVisible();
    const welcome = page.getByRole("dialog", { name: "Как начать обучение" });
    await expect(welcome).toContainText("Прогресс сохраняется");
    await expect(welcome).not.toContainText("NEXT_PUBLIC");
    await welcome.getByRole("button", { name: "Понятно", exact: true }).click();
    expect((await (await context.request.get("/api/auth/me")).json()).user.must_change_password).toBe(false);
    expect((await (await other.request.get("/api/auth/me")).json()).authenticated).toBe(false);
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect((await context.request.post("/api/auth/login", { data: { email, password: newPassword } })).ok()).toBe(true);
  } finally {
    // Only this explicitly created test identity is invalidated, never a real account.
    await api("POST", `/admin/users/${created.id}/reset-password`, { password: `closed-${Date.now()}-${Math.random()}`, must_change_password: true });
    await context.close(); await other.close();
  }
});
