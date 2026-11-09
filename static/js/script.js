/* The database is the conversation source. Display errors never become model context. */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const $ = (selector) => document.querySelector(selector);
  const form = $("#prompt-form");
  const input = $("#prompt");
  const output = $("#gpt-output");
  const specialty = $("#specialty");
  const answerLevel = $("#answer-level");
  const webSearch = $("#web-search");
  const fileInput = $("#file-input");
  const sendButton = $("#send-button");
  const attachButton = $("#attach-file");
  const clearButton = $("#clear-chat");
  const newButton = $("#new-chat");
  const stopButton = $("#stop-response");
  const state = { csrf: "", messages: [], file: null, busy: false, controller: null,
    specialty: "general", ready: false, clearing: false, conversations: [],
    conversationId: null, viewVersion: 0, listBusy: false, deleteTarget: null,
    answerLevel: "intermediate", feedbackReasons: {}, webAvailable: false };
  const markdown = window.markdownit ? window.markdownit({ html: false, linkify: true, breaks: true }) : null;
  const purifier = window.DOMPurify;
  let renderFrame = 0;

  function notice(message = "", error = false) {
    const element = $("#notice");
    element.textContent = message;
    element.hidden = !message;
    element.classList.toggle("is-error", error);
  }

  function status(message, error = false) {
    const element = $("#save-status");
    element.replaceChildren();
    const dot = document.createElement("span");
    dot.className = "online-dot";
    dot.setAttribute("aria-hidden", "true");
    element.append(dot, document.createTextNode(message));
    element.classList.toggle("error", error);
  }

  function controls() {
    const locked = !state.ready || state.busy || state.clearing;
    sendButton.disabled = locked || (!input.value.trim() && !state.file);
    attachButton.disabled = locked;
    input.disabled = !state.ready || state.clearing;
    specialty.disabled = locked;
    answerLevel.disabled = locked;
    webSearch.disabled = locked || Boolean(state.file) || !state.webAvailable;
    clearButton.disabled = !state.ready || state.clearing;
    newButton.disabled = !state.ready || state.clearing || state.listBusy;
    document.querySelectorAll(".chat-select, .delete-chat").forEach(button => {
      button.disabled = !state.ready || state.clearing || state.listBusy;
    });
    $("#remove-file").disabled = state.busy || state.clearing;
    stopButton.hidden = !state.busy;
    sendButton.hidden = state.busy;
    document.querySelectorAll(".suggestion").forEach(button => { button.disabled = locked; });
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
    controls();
  }

  function nearBottom() {
    return document.documentElement.scrollHeight - window.scrollY - window.innerHeight < 230;
  }

  function scrollDown(force = false) {
    if (force || nearBottom()) window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
  }

  function renderMarkdown(element, text) {
    if (!markdown || !purifier) {
      element.textContent = text;
      return;
    }
    element.innerHTML = purifier.sanitize(markdown.render(text), {
      FORBID_TAGS: ["img", "style", "form", "input", "button", "iframe", "svg", "math"],
      FORBID_ATTR: ["style"],
    });
    element.querySelectorAll("a").forEach(link => {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
  }

  function actionButton(text, label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "action-button";
    button.textContent = text;
    button.setAttribute("aria-label", label);
    button.addEventListener("click", onClick);
    return button;
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin", ...options,
      headers: { "X-CSRF-Token": state.csrf,
        ...(state.conversationId ? { "X-Conversation-ID": state.conversationId } : {}), ...options.headers },
    });
    if (!response.ok) {
      let message = `Le serveur a retourné une erreur (${response.status}). Réessayez.`;
      try {
        const data = await response.json();
        if (typeof data.error === "string") message = data.error;
      } catch (_) { /* Keep a safe message instead of displaying a server HTML page. */ }
      throw new Error(message);
    }
    return response;
  }

  function addActions(row, message) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const saved = document.createElement("span");
    saved.className = "feedback-status";
    saved.setAttribute("role", "status");
    let saving = false;

    const positive = actionButton("♡ Utile", "Cette réponse est utile", () => saveRating(message.score === 1 ? null : 1, message.comment || "", []));
    const negative = actionButton("☟ À améliorer", "Cette réponse est à améliorer", () => {
      const score = message.score === -1 ? null : -1;
      saveRating(score, message.comment || "", score === -1 ? message.reasons || [] : []);
      if (score === -1) detail.open = true;
    });
    function updateRatingButtons() {
      positive.setAttribute("aria-pressed", String(message.score === 1));
      negative.setAttribute("aria-pressed", String(message.score === -1));
    }
    updateRatingButtons();
    const copy = actionButton("⧉ Copier", "Copier la réponse", async () => {
      try {
        await navigator.clipboard.writeText(message.content);
        saved.textContent = "Réponse copiée";
      } catch (_) {
        saved.textContent = "Copie indisponible : sélectionnez le texte de la réponse.";
      }
    });
    const detail = document.createElement("details");
    detail.className = "feedback";
    const summary = document.createElement("summary");
    summary.textContent = "✎ Commenter";
    const feedbackForm = document.createElement("form");
    feedbackForm.className = "feedback-form";
    const reasonsGroup = document.createElement("fieldset");
    reasonsGroup.className = "feedback-reasons";
    const legend = document.createElement("legend");
    legend.textContent = "Que peut-on améliorer ?";
    reasonsGroup.append(legend);
    const reasonInputs = [];
    for (const [value, text] of Object.entries(state.feedbackReasons)) {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = value;
      checkbox.checked = (message.reasons || []).includes(value);
      reasonInputs.push(checkbox);
      label.append(checkbox, document.createTextNode(text));
      reasonsGroup.append(label);
    }
    const textarea = document.createElement("textarea");
    textarea.maxLength = 1000;
    textarea.rows = 2;
    textarea.placeholder = "Qu'est-ce qui vous a aidé ? Que pourrait-on améliorer ?";
    textarea.setAttribute("aria-label", "Commentaire sur cette réponse");
    textarea.value = message.comment || "";
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Enregistrer";
    feedbackForm.append(reasonsGroup, textarea, save);
    detail.append(summary, feedbackForm);
    feedbackForm.addEventListener("submit", event => {
      event.preventDefault();
      const reasons = reasonInputs.filter(input => input.checked).map(input => input.value);
      saveRating(reasons.length ? -1 : message.score, textarea.value, reasons);
    });
    async function saveRating(score, comment = message.comment || "", reasons = message.reasons || []) {
      if (saving) return;
      saving = true;
      positive.disabled = negative.disabled = save.disabled = true;
      reasonsGroup.disabled = true;
      saved.textContent = "Enregistrement…";
      try {
        const response = await api(`/api/messages/${message.id}/rating`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ score, comment, reasons }),
        });
        Object.assign(message, await response.json());
        updateRatingButtons();
        reasonInputs.forEach(input => { input.checked = message.reasons.includes(input.value); });
        saved.textContent = "Avis enregistré, merci !";
      } catch (error) {
        saved.textContent = error.message;
      } finally {
        saving = false;
        positive.disabled = negative.disabled = save.disabled = false;
        reasonsGroup.disabled = false;
      }
    }
    actions.append(positive, negative, copy, detail, saved);
    row.append(actions);
  }

  function addMessage(message, temporary = false) {
    $("#welcome").hidden = true;
    const row = document.createElement("article");
    row.className = `message-row ${message.role}`;
    if (message.id) row.dataset.id = message.id;
    const heading = document.createElement("div");
    heading.className = "message-heading";
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = message.role === "user" ? "V" : "✦";
    const name = document.createElement("span");
    name.textContent = message.role === "user" ? "Vous" : "FlaskGPT";
    heading.append(avatar, name);
    if (message.created_at) {
      const time = document.createElement("time");
      time.className = "message-time";
      time.dateTime = message.created_at;
      time.textContent = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(new Date(message.created_at));
      heading.append(time);
    }
    const content = document.createElement("div");
    content.className = "message-content";
    if (message.role === "assistant") renderMarkdown(content, message.content);
    else content.textContent = message.content;
    row.append(heading, content);
    if (message.attachment_name) {
      const attachment = document.createElement("div");
      attachment.className = "message-file";
      attachment.textContent = "▤ " + message.attachment_name;
      row.append(attachment);
    }
    if (message.role === "assistant" && !temporary) addActions(row, message);
    output.append(row);
    return { row, content };
  }

  function drawHistory() {
    output.replaceChildren();
    state.messages.forEach(message => addMessage(message));
    $("#welcome").hidden = state.messages.length > 0;
  }

  function renderConversations() {
    const list = $("#conversation-list");
    list.replaceChildren();
    $("#history-count").textContent = state.conversations.length;
    for (const conversation of state.conversations) {
      const item = document.createElement("div");
      item.className = "conversation-item";
      item.dataset.conversationId = conversation.id;
      item.classList.toggle("is-active", conversation.id === state.conversationId);
      const select = document.createElement("button");
      select.type = "button";
      select.className = "chat-select";
      select.title = conversation.title;
      if (conversation.id === state.conversationId) select.setAttribute("aria-current", "page");
      const icon = document.createElement("span");
      icon.className = "chat-list-icon";
      icon.textContent = "▤";
      icon.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      text.className = "chat-list-text";
      const title = document.createElement("span");
      title.className = "chat-list-title";
      title.textContent = conversation.title;
      const meta = document.createElement("small");
      const date = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" }).format(new Date(conversation.updated_at));
      meta.textContent = conversation.exchange_count
        ? `${conversation.exchange_count} échange${conversation.exchange_count > 1 ? "s" : ""} · ${date}`
        : "Pas encore de message";
      text.append(title, meta);
      select.append(icon, text);
      select.addEventListener("click", () => changeConversation(conversation.id));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "delete-chat";
      remove.setAttribute("aria-label", `Supprimer la conversation : ${conversation.title}`);
      remove.title = "Supprimer cette conversation";
      remove.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/></svg>';
      remove.addEventListener("click", () => {
        state.deleteTarget = conversation;
        $("#delete-chat-name").textContent = conversation.title;
        $("#delete-dialog").showModal();
      });
      item.append(select, remove);
      list.append(item);
    }
    const current = state.conversations.find(chat => chat.id === state.conversationId);
    $("#current-title").textContent = current?.title || "Assistant";
    $("#current-title").title = current?.title || "Assistant";
    $("#export-menu").querySelectorAll("a").forEach(link => {
      const url = new URL(link.href);
      url.searchParams.set("conversation_id", state.conversationId);
      link.href = url.pathname + url.search;
    });
    controls();
  }

  function applyConversation(data) {
    state.csrf = data.csrf_token;
    state.conversationId = data.conversation_id;
    state.conversations = data.conversations;
    state.messages = data.messages;
    state.specialty = data.specialty;
    state.answerLevel = data.answer_level;
    state.feedbackReasons = data.feedback_reasons;
    state.webAvailable = data.web_search_available;
    specialty.replaceChildren();
    data.specialties.forEach(item => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      specialty.append(option);
    });
    specialty.value = state.specialty;
    answerLevel.replaceChildren();
    data.answer_levels.forEach(item => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      answerLevel.append(option);
    });
    answerLevel.value = state.answerLevel;
    updateComposerMode();
    $("#config-banner").hidden = data.configured;
    drawHistory();
    state.ready = true;
    renderConversations();
    controls();
    status(state.messages.length ? "Conversation enregistrée" : "Votre espace est prêt");
  }

  async function loadConversation() {
    const version = state.viewVersion;
    const response = await api("/api/conversation");
    const data = await response.json();
    if (version === state.viewVersion) applyConversation(data);
  }

  async function changeConversation(id = null) {
    if (state.clearing || state.listBusy || !state.ready || id === state.conversationId) return;
    state.clearing = true;
    state.viewVersion++;
    state.controller?.abort();
    controls();
    try {
      const response = await api(id ? `/api/conversations/${id}/select` : "/api/conversations", { method: "POST" });
      input.value = "";
      setFile(null);
      applyConversation(await response.json());
      notice(id ? "Conversation ouverte." : "Nouvelle conversation créée. Vos autres échanges sont conservés.");
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (error) { notice(error.message, true); }
    finally {
      state.clearing = false;
      controls();
      resizeInput();
      input.focus({ preventScroll: true });
    }
  }

  async function setSpecialty(value) {
    return setPreferences({ specialty: value });
  }

  function updateComposerMode() {
    $("#composer-mode").textContent = specialty.selectedOptions[0].textContent + " · " + answerLevel.selectedOptions[0].textContent;
  }

  async function setPreferences(changes) {
    const previous = { specialty: state.specialty, answerLevel: state.answerLevel };
    const version = state.viewVersion;
    specialty.disabled = answerLevel.disabled = true;
    try {
      const response = await api("/api/conversation", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changes),
      });
      if (version !== state.viewVersion) return;
      const data = await response.json();
      state.specialty = data.specialty;
      state.answerLevel = data.answer_level;
      specialty.value = state.specialty;
      answerLevel.value = state.answerLevel;
      updateComposerMode();
      notice();
    } catch (error) {
      if (version !== state.viewVersion) return;
      specialty.value = previous.specialty;
      answerLevel.value = previous.answerLevel;
      notice(error.message, true);
      throw error;
    } finally { controls(); }
  }

  function setFile(file) {
    state.file = file;
    if (file) webSearch.checked = false;
    $("#attachment").hidden = !file;
    $("#attachment-name").textContent = file ? file.name : "";
    if (!file) fileInput.value = "";
    input.placeholder = file ? "Une consigne pour le résumé ? (facultatif)" : "Qu'avez-vous en tête ?";
    controls();
  }

  async function readStream(response, content, controller) {
    if (!response.headers.get("Content-Type")?.includes("application/x-ndjson") || !response.body) {
      throw new Error("Réponse du serveur non reconnue. Actualisez la page et réessayez.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "", answer = "", completed = false;
    function handleLine(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === "error") throw new Error(event.error);
      if (event.type === "delta") {
        if (completed || typeof event.text !== "string") throw new Error("Flux de réponse invalide.");
        answer += event.text;
        if (!renderFrame) {
          renderFrame = requestAnimationFrame(() => {
            const shouldScroll = nearBottom();
            content.textContent = answer;
            renderFrame = 0;
            if (shouldScroll) scrollDown(true);
          });
        }
      } else if (event.type === "done") completed = true;
    }
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) !== -1) {
          handleLine(buffer.slice(0, newline));
          buffer = buffer.slice(newline + 1);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) handleLine(buffer);
      if (!completed || !answer.trim()) throw new Error("La réponse a été interrompue. Réessayez : votre historique enregistré est intact.");
      if (controller.signal.aborted) throw new DOMException("Annulé", "AbortError");
      renderMarkdown(content, answer);
    } finally {
      cancelAnimationFrame(renderFrame);
      renderFrame = 0;
      if (!completed) await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const typed = input.value.trim();
    if ((!typed && !state.file) || state.busy || !state.ready || state.clearing) return;
    notice();
    const file = state.file;
    const useWeb = webSearch.checked && !file;
    const question = typed || "Résume ce document en français : idées principales, points clés et conclusion.";
    const controller = new AbortController();
    const version = state.viewVersion;
    state.controller = controller;
    state.busy = true;
    controls();
    // Redraw from confirmed records to discard any previous transient error blocks.
    drawHistory();
    addMessage({ role: "user", content: question, attachment_name: file?.name }, true);
    const answer = addMessage({ role: "assistant", content: "" }, true);
    answer.row.classList.add("streaming");
    input.value = "";
    resizeInput();
    status(file ? "Lecture du document…" : useWeb ? "Recherche Web en cours…" : "Réponse en cours…");
    scrollDown(true);
    try {
      let body, headers = {};
      if (file) {
        body = new FormData();
        body.append("file", file);
        body.append("message", typed);
      } else {
        body = JSON.stringify({ message: question, web_search: useWeb });
        headers["Content-Type"] = "application/json";
      }
      const response = await api("/api/chat", { method: "POST", headers, body, signal: controller.signal });
      await readStream(response, answer.content, controller);
      if (state.clearing || version !== state.viewVersion) return;
      setFile(null);
      webSearch.checked = false;
      await loadConversation();
      if (version !== state.viewVersion) return;
      status("Conversation enregistrée");
      scrollDown(true);
    } catch (error) {
      if (state.clearing || version !== state.viewVersion) return;
      const message = error.name === "AbortError" ? "Réponse arrêtée. Cet échange n'est pas ajouté à l'historique enregistré." : error.message;
      answer.row.classList.remove("streaming");
      const errorBlock = document.createElement("div");
      errorBlock.className = "message-error";
      errorBlock.setAttribute("role", "alert");
      errorBlock.textContent = message;
      answer.row.append(errorBlock);
      const label = document.createElement("span");
      label.className = "unsaved-label";
      label.textContent = "· non enregistré";
      answer.row.querySelector(".message-heading").append(label);
      if (!input.value) input.value = typed;
      resizeInput();
      status("Vous pouvez réessayer", true);
      scrollDown(true);
    } finally {
      if (state.controller === controller) {
        state.busy = false;
        state.controller = null;
        controls();
        if (!state.clearing && version === state.viewVersion) input.focus({ preventScroll: true });
      }
    }
  });

  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  specialty.addEventListener("change", () => { setSpecialty(specialty.value).catch(() => {}); });
  answerLevel.addEventListener("change", () => { setPreferences({ answer_level: answerLevel.value }).catch(() => {}); });
  attachButton.addEventListener("click", () => fileInput.click());
  $("#summarize-suggestion").addEventListener("click", () => fileInput.click());
  $("#remove-file").addEventListener("click", () => setFile(null));
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { notice("Le fichier dépasse la limite de 5 Mo.", true); fileInput.value = ""; return; }
    if (!/\.(pdf|docx|txt|md|csv)$/i.test(file.name)) { notice("Choisissez un PDF, DOCX, TXT, MD ou CSV.", true); fileInput.value = ""; return; }
    setFile(file);
    notice();
    input.focus();
  });
  stopButton.addEventListener("click", () => {
    state.controller?.abort();
    api("/api/conversation/cancel", { method: "POST" }).catch(error => notice(error.message, true));
  });
  clearButton.addEventListener("click", () => $("#clear-dialog").showModal());
  newButton.addEventListener("click", () => changeConversation());
  $("#delete-dialog").addEventListener("close", async () => {
    const target = state.deleteTarget;
    state.deleteTarget = null;
    if ($("#delete-dialog").returnValue !== "delete" || !target || state.listBusy) return;
    const wasActive = target.id === state.conversationId;
    state.listBusy = true;
    if (wasActive) {
      state.clearing = true;
      state.viewVersion++;
      state.controller?.abort();
    }
    controls();
    try {
      const response = await api(`/api/conversations/${target.id}`, { method: "DELETE" });
      const data = await response.json();
      if (wasActive) {
        input.value = "";
        setFile(null);
        applyConversation(data);
      } else {
        state.conversations = data.conversations;
        renderConversations();
      }
      notice("Conversation supprimée.");
    } catch (error) { notice(error.message, true); }
    finally {
      state.listBusy = false;
      if (wasActive) state.clearing = false;
      controls();
      if (wasActive) { resizeInput(); input.focus({ preventScroll: true }); }
    }
  });
  $("#clear-dialog").addEventListener("close", async () => {
    if ($("#clear-dialog").returnValue !== "clear") return;
    state.clearing = true;
    state.viewVersion++;
    state.controller?.abort();
    controls();
    try {
      await api("/api/conversation", { method: "DELETE" });
      input.value = "";
      setFile(null);
      await loadConversation();
      notice("Conversation effacée. Une nouvelle idée ?");
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (error) { notice(error.message, true); }
    finally { state.clearing = false; controls(); resizeInput(); input.focus({ preventScroll: true }); }
  });
  document.querySelectorAll("[data-prompt]").forEach(button => {
    button.addEventListener("click", async () => {
      if (state.busy || !state.ready) return;
      try {
        if (button.dataset.specialty) await setSpecialty(button.dataset.specialty);
        input.value = button.dataset.prompt;
        resizeInput();
        input.focus();
      } catch (_) { /* The specialty handler already displays the error. */ }
    });
  });
  $("#export-menu").querySelectorAll("a").forEach(link => {
    link.addEventListener("click", () => { $("#export-menu").open = false; });
  });
  document.addEventListener("click", event => {
    if (!$("#export-menu").contains(event.target)) $("#export-menu").open = false;
  });
  loadConversation().catch(error => {
    notice("Impossible de charger la conversation. " + error.message + " Actualisez la page.", true);
    status("Connexion indisponible", true);
  });
});
