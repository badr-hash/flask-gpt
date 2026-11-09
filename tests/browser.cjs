/* Run against `python tests/ui_server.py` using Playwright. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => {
    if (message.type() === "error" && !message.text().includes("Failed to load resource")) errors.push(message.text());
  });
  const base = process.env.TEST_URL || "http://127.0.0.1:5011";
  const screenshotDir = path.resolve("test-results");
  await fs.mkdir(screenshotDir, { recursive: true });
  const results = [];
  async function check(name, action) {
    await action();
    results.push(name);
    console.log("PASS:", name);
  }
  async function ready() { await page.locator("#prompt").waitFor(); await page.waitForFunction(() => !document.querySelector("#prompt").disabled); }
  async function send(text) {
    await page.locator("#prompt").fill(text);
    await page.locator("#send-button").click();
  }
  async function savedAnswers(n) {
    await page.waitForFunction(expected => document.querySelectorAll(".assistant[data-id]").length === expected, n);
  }
  async function clear() {
    await page.locator("#clear-chat").click();
    await page.getByRole("button", { name: "Effacer la conversation", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".message-row").length === 0);
  }
  try {
    await page.goto(base);
    await ready();
    await check("empty state, specialty options, local assets, desktop layout", async () => {
      assert(await page.locator("#welcome").isVisible());
      assert.equal(await page.locator("#specialty option").count(), 6);
      assert(!(await page.locator("#config-banner").isVisible()));
      assert(await page.evaluate(() => typeof window.markdownit === "function" && typeof window.DOMPurify.sanitize === "function"));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(screenshotDir, "desktop-empty.png"), fullPage: true });
    });
    await check("specialty changes and message streaming", async () => {
      await page.locator("#specialty").selectOption("python");
      await page.waitForFunction(() => document.querySelector("#composer-mode").textContent.startsWith("Programmation Python"));
      await send("Explique les listes Python.");
      await savedAnswers(1);
      assert.equal(await page.locator(".assistant .message-content strong").innerText(), "utile");
      assert((await page.locator(".assistant pre code").innerText()).includes("été"));
      assert(await page.locator("#save-status").innerText().then(t => t.includes("enregistrée")));
    });
    await check("explanation level is selectable and persists after reload", async () => {
      assert.equal(await page.locator("#answer-level option").count(), 3);
      await page.locator("#answer-level").selectOption("beginner");
      await page.waitForFunction(() => document.querySelector("#composer-mode").textContent.includes("Débutant"));
      await page.reload(); await ready();
      assert.equal(await page.locator("#answer-level").inputValue(), "beginner");
      await page.locator("#answer-level").selectOption("intermediate");
      await page.waitForFunction(() => document.querySelector("#composer-mode").textContent.includes("Intermédiaire"));
    });
    await check("ratings, optional feedback, and persistence after reload", async () => {
      const answer = page.locator(".assistant").last();
      await answer.getByRole("button", { name: "Cette réponse est utile", exact: true }).click();
      await page.waitForFunction(() => document.querySelector('.assistant button[aria-label="Cette réponse est utile"]').getAttribute("aria-pressed") === "true");
      await answer.locator(".feedback summary").click();
      await answer.getByRole("textbox", { name: "Commentaire sur cette réponse" }).fill("Explication claire, merci.");
      await answer.getByRole("button", { name: "Enregistrer", exact: true }).click();
      await page.waitForFunction(() => document.querySelector(".feedback-status").textContent.includes("Avis enregistré"));
      await page.reload();
      await ready();
      assert.equal(await page.locator("#specialty").inputValue(), "python");
      assert.equal(await page.locator('.assistant button[aria-label="Cette réponse est utile"]').getAttribute("aria-pressed"), "true");
      assert.equal(await page.locator(".feedback textarea").inputValue(), "Explication claire, merci.");
      await page.screenshot({ path: path.join(screenshotDir, "desktop-conversation.png"), fullPage: true });
    });
    await check("specific feedback reasons are saved, restored, and removable", async () => {
      const answer = page.locator(".assistant").last();
      await answer.getByRole("button", { name: "Cette réponse est à améliorer", exact: true }).click();
      await answer.getByLabel("Informations incorrectes", { exact: true }).check();
      await answer.getByLabel("Trop vague", { exact: true }).check();
      const response = page.waitForResponse(r => r.url().includes("/rating") && r.request().method() === "PUT");
      await answer.getByRole("button", { name: "Enregistrer", exact: true }).click();
      assert.equal((await response).status(), 200);
      await page.reload(); await ready();
      assert.equal(await page.locator('.assistant button[aria-label="Cette réponse est à améliorer"]').getAttribute("aria-pressed"), "true");
      assert(await page.locator('.assistant input[value="incorrect"]').isChecked());
      assert(await page.locator('.assistant input[value="too_vague"]').isChecked());
      const positive = page.waitForResponse(r => r.url().includes("/rating") && r.request().method() === "PUT");
      await page.locator('.assistant button[aria-label="Cette réponse est utile"]').click();
      assert.equal((await positive).status(), 200);
      await page.waitForFunction(() => !document.querySelector('.assistant input[value="incorrect"]').checked);
    });
    await check("downloadable Markdown, text, and JSON exports", async () => {
      for (const format of ["md", "txt", "json"]) {
        await page.locator("#export-menu summary").click();
        const downloadPromise = page.waitForEvent("download");
        await page.locator(`#export-menu a[href*="format=${format}"]`).click();
        const download = await downloadPromise;
        assert.equal(download.suggestedFilename(), `flaskgpt-conversation.${format}`);
        const content = await fs.readFile(await download.path(), "utf8");
        assert(content.includes("Explication claire, merci."));
        if (format === "json") assert.equal(JSON.parse(content).messages[1].score, 1);
      }
    });
    await check("upload and summarize a text document", async () => {
      await page.locator("#file-input").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("Le cours présente Flask, SQLite et les réponses progressives.") });
      assert(await page.locator("#attachment").isVisible());
      assert(await page.locator("#web-search").isDisabled());
      await page.locator("#send-button").click();
      await savedAnswers(2);
      assert.equal(await page.locator(".message-file").last().innerText(), "▤ notes.txt");
      assert(!(await page.locator("#attachment").isVisible()));
    });
    await check("clear removes displayed and stored messages and ratings", async () => {
      await clear();
      assert(await page.locator("#welcome").isVisible());
      await page.reload(); await ready();
      assert.equal(await page.locator(".message-row").count(), 0);
    });
    await check("invalid API key shows a safe error and allows retry", async () => {
      await send("test-http-error");
      await page.locator(".message-error").waitFor();
      assert((await page.locator(".message-error").innerText()).includes("Clé API Groq invalide"));
      assert.equal(await page.locator(".assistant[data-id]").count(), 0);
      await send("Une nouvelle question après une erreur.");
      await savedAnswers(1);
      assert.equal(await page.locator(".message-error").count(), 0);
      assert.equal(await page.locator(".message-row").count(), 2);
    });
    await check("mid-stream failure does not corrupt the next request", async () => {
      await send("test-stream-error");
      await page.locator(".message-error").waitFor();
      await send("Réessaie avec une nouvelle réponse.");
      await savedAnswers(2);
      assert.equal(await page.locator(".message-row").count(), 4);
    });
    await check("clear during streaming prevents stale messages returning", async () => {
      await send("test-slow-response");
      await page.waitForFunction(() => document.querySelector(".streaming .message-content")?.textContent.includes("Réponse en cours"));
      await clear();
      await page.waitForTimeout(600);
      await page.reload(); await ready();
      assert.equal(await page.locator(".message-row").count(), 0);
      await send("Après effacement"); await savedAnswers(1);
    });
    await check("stop response and retry", async () => {
      await send("test-slow-response");
      await page.waitForFunction(() => document.querySelector(".streaming .message-content")?.textContent.includes("Réponse en cours"));
      await page.locator("#stop-response").click();
      await page.locator(".message-error").waitFor();
      assert((await page.locator(".message-error").innerText()).includes("arrêtée"));
      // The server observes disconnect when it next writes a chunk.
      await page.waitForTimeout(600);
      await send("Après arrêt"); await savedAnswers(2);
    });
    await check("separate browser sessions cannot see each other's history", async () => {
      const isolated = await browser.newContext();
      const other = await isolated.newPage();
      await other.goto(base);
      await other.waitForFunction(() => !document.querySelector("#prompt").disabled);
      assert.equal(await other.locator(".message-row").count(), 0);
      await isolated.close();
    });
    let firstChat, secondChat, thirdChat;
    function chatItem(id) { return page.locator(`.conversation-item[data-conversation-id="${id}"]`); }
    async function activeChat(id) {
      await page.waitForFunction(expected => document.querySelector(".conversation-item.is-active")?.dataset.conversationId === expected, id);
    }
    async function createChat(expectedCount) {
      await page.locator("#new-chat").click();
      await page.waitForFunction(expected => document.querySelectorAll(".conversation-item").length === expected, expectedCount);
      await page.waitForFunction(() => document.querySelectorAll(".message-row").length === 0);
      return page.locator(".conversation-item.is-active").getAttribute("data-conversation-id");
    }
    async function deleteChat(id) {
      await chatItem(id).locator(".delete-chat").click();
      await page.getByRole("button", { name: "Supprimer la conversation", exact: true }).click();
      await page.waitForFunction(deleted => ![...document.querySelectorAll(".conversation-item")].some(row => row.dataset.conversationId === deleted), id);
    }
    await check("new conversations preserve existing chats and acquire useful titles", async () => {
      firstChat = await page.locator(".conversation-item.is-active").getAttribute("data-conversation-id");
      secondChat = await createChat(2);
      await send("Préparer un entretien Python"); await savedAnswers(1);
      assert.equal(await chatItem(secondChat).locator(".chat-list-title").innerText(), "Préparer un entretien Python");
      thirdChat = await createChat(3);
      await send("Comprendre les bases de SQLite"); await savedAnswers(1);
      assert.equal(await chatItem(thirdChat).locator(".chat-list-title").innerText(), "Comprendre les bases de SQLite");
      await page.screenshot({ path: path.join(screenshotDir, "desktop-history.png"), fullPage: true });
    });
    await check("switching restores the chosen chat and survives a page reload", async () => {
      await chatItem(firstChat).locator(".chat-select").click(); await activeChat(firstChat);
      await savedAnswers(2);
      assert.equal(await page.locator(".user .message-content").first().innerText(), "Après effacement");
      await chatItem(secondChat).locator(".chat-select").click(); await activeChat(secondChat);
      await savedAnswers(1);
      assert.equal(await page.locator(".user .message-content").first().innerText(), "Préparer un entretien Python");
      await page.reload(); await ready();
      await activeChat(secondChat); await savedAnswers(1);
    });
    await check("deletion can be cancelled and deleting another chat preserves the selected one", async () => {
      await chatItem(thirdChat).locator(".delete-chat").click();
      await page.locator("#delete-dialog").getByRole("button", { name: "Annuler", exact: true }).click();
      assert.equal(await page.locator(".conversation-item").count(), 3);
      await deleteChat(thirdChat);
      await activeChat(secondChat); await savedAnswers(1);
      assert.equal(await page.locator(".conversation-item").count(), 2);
      await page.reload(); await ready();
      assert.equal(await chatItem(thirdChat).count(), 0);
    });
    await check("deleting the selected chat opens a remaining chat, then an empty chat", async () => {
      await deleteChat(secondChat); await activeChat(firstChat); await savedAnswers(2);
      await deleteChat(firstChat);
      assert.equal(await page.locator(".conversation-item").count(), 1);
      assert.equal(await page.locator(".message-row").count(), 0);
      await page.reload(); await ready();
      assert.equal(await page.locator(".conversation-item").count(), 1);
      assert.equal(await page.locator(".message-row").count(), 0);
    });
    await check("starting a new chat during streaming never writes into the newly selected chat", async () => {
      firstChat = await page.locator(".conversation-item.is-active").getAttribute("data-conversation-id");
      await send("test-slow-response");
      await page.waitForFunction(() => document.querySelector(".streaming .message-content")?.textContent.includes("Réponse en cours"));
      secondChat = await createChat(2);
      await page.waitForTimeout(500);
      assert.equal(await page.locator(".message-error").count(), 0);
      assert.equal(await page.locator(".message-row").count(), 0);
      await chatItem(firstChat).locator(".chat-select").click(); await activeChat(firstChat);
      assert.equal(await page.locator(".message-row").count(), 0);
      await send("Retour à ma conversation"); await savedAnswers(1);
    });
    await check("deleting an inactive chat leaves an ongoing response intact", async () => {
      await send("test-slow-response");
      await page.waitForFunction(() => document.querySelector(".streaming .message-content")?.textContent.includes("Réponse en cours"));
      await deleteChat(secondChat);
      await activeChat(firstChat);
      assert(await page.locator("#stop-response").isVisible());
      assert.equal(await page.locator(".message-error").count(), 0);
      await page.locator("#stop-response").click();
      await page.locator(".message-error").waitFor();
      await page.waitForTimeout(500);
      await send("Ma réponse suivante"); await savedAnswers(2);
    });
    await check("mobile layout and multiline input", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await createChat(2);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert(await page.locator("#conversation-list").isVisible());
      assert.equal(await page.locator(".conversation-item").count(), 2);
      await page.locator("#prompt").fill("Ligne 1");
      await page.locator("#prompt").press("Shift+Enter");
      await page.locator("#prompt").pressSequentially("Ligne 2");
      assert((await page.locator("#prompt").inputValue()).includes("\n"));
      await page.screenshot({ path: path.join(screenshotDir, "mobile-empty.png"), fullPage: true });
    });
    await check("optional web mode shows clickable sources and resets after sending", async () => {
      await page.locator("#web-search").check();
      await send("Vérifie cette information publique.");
      await savedAnswers(1);
      assert(await page.locator('.assistant .message-content a[href="https://example.com/reference"]').count() > 0);
      assert(!(await page.locator("#web-search").isChecked()));
    });
    assert.deepEqual(errors, []);
    console.log(`\n${results.length} browser checks passed; no JavaScript errors.`);
  } catch (error) {
    await page.screenshot({ path: path.join(screenshotDir, "failure.png"), fullPage: true }).catch(() => {});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
