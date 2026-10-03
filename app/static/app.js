// My Saver - front end (no framework). Talks to the FastAPI server with a bearer access code.
"use strict";

const $ = (s) => document.querySelector(s);
const TOKEN_KEY = "saver_token";
const state = { tab: "all", q: "", category: "", draining: false, installEvt: null, config: {} };

// ---------- small helpers ----------
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
  del: (k) => { try { localStorage.removeItem(k); } catch {} },
};
function parseDate(s) { if (!s) return null; const [y, m, d] = s.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); }
function fmtDate(s) { const d = parseDate(s); return d ? d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : ""; }
function daysLeft(s) { const d = parseDate(s); if (!d) return null; const t = new Date(); t.setHours(0, 0, 0, 0); return Math.round((d - t) / 86400000); }
function snippet(s, n = 90) { s = (s || "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n) + "…" : s; }
const KIND_LABEL = { text: "Text", link: "Link", youtube: "YouTube", image: "Image", pdf: "PDF", document: "File", audio: "Audio", video: "Video" };

// ---------- API ----------
const GKEY = "saver_gemini_key";
class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }
async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = store.get(TOKEN_KEY), gkey = store.get(GKEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  if (gkey) headers["X-Gemini-Key"] = gkey;
  const res = await fetch(path, { ...opts, headers });
  let body = null;
  try { body = await res.json(); } catch {}
  if (res.status === 401 && !path.startsWith("/api/auth/")) { logout("Please log in again."); throw new ApiError("Unauthorised", 401); }
  if (!res.ok) throw new ApiError((body && body.detail) || `Server error (${res.status})`, res.status);
  return body;
}
const postJSON = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

// ---------- screens ----------
function show(id) { for (const s of ["login", "main", "settings"]) $("#" + s).hidden = s !== id; window.scrollTo(0, 0); }
function showLogin(msg) {
  show("login");
  $("#login-error").hidden = !msg; $("#login-error").textContent = msg || "";
}
function showMain() { show("main"); }
function logout(msg) { store.del(TOKEN_KEY); showLogin(msg); }

// ---------- log in / create account ----------
let authMode = "login";
function setAuthMode(mode) {
  authMode = mode;
  document.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  const reg = mode === "register";
  $("#f-name").hidden = !reg; $("#f-name").required = reg;
  $("#f-code").hidden = !(reg && state.config.class_code_required); $("#f-code").required = reg && state.config.class_code_required;
  $("#f-password").autocomplete = reg ? "new-password" : "current-password";
  $("#auth-submit").textContent = reg ? "Create account" : "Log in";
  $("#login-error").hidden = true;
}
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => setAuthMode(b.dataset.mode)));
$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#auth-submit"); btn.disabled = true;
  const data = { email: $("#f-email").value.trim(), password: $("#f-password").value };
  if (authMode === "register") Object.assign(data, { name: $("#f-name").value.trim(), class_code: $("#f-code").value.trim() });
  try {
    const res = await postJSON(authMode === "register" ? "/api/auth/register" : "/api/auth/login", data);
    store.set(TOKEN_KEY, res.token);
    $("#auth-form").reset();
    showMain(); await startMain();
  } catch (err) { showLogin(err.message); }
  finally { btn.disabled = false; }
});

// ---------- settings ----------
$("#settings-btn").addEventListener("click", openSettings);
$("#settings-back").addEventListener("click", () => { showMain(); maybeKeyHint(); });
$("#logout-btn").addEventListener("click", () => logout());
async function openSettings() {
  show("settings");
  const k = store.get(GKEY);
  $("#key-input").value = k || "";
  keyStatus(k ? "Key saved on this phone." : state.config.shared_key_available ? "Optional: your teacher's shared key is used if you don't add one." : "No key yet: shares can't be read until you add one.", k ? "ok" : "");
  try { const me = await api("/api/me"); $("#account-info").textContent = `${me.name} · ${me.email}`; } catch {}
}
function keyStatus(text, cls = "") { const el = $("#key-status"); el.textContent = text; el.className = `meta ${cls}`; }
$("#key-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const k = $("#key-input").value.trim();
  if (!k) { store.del(GKEY); keyStatus("Key removed."); return; }
  keyStatus("Checking key…");
  try {
    // Quick validity check straight from the phone to Google (the key is not sent to our server here)
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models?pageSize=1&key=${encodeURIComponent(k)}`);
    if (r.status === 400 || r.status === 403) { keyStatus("Google rejected this key. Copy it again from AI Studio.", "error"); return; }
    store.set(GKEY, k);
    keyStatus(r.ok ? "✓ Key works and is saved on this phone." : "Saved (couldn't verify right now).", "ok");
  } catch {
    store.set(GKEY, k); keyStatus("Saved (couldn't verify: no internet?).", "ok");
  }
});
$("#pw-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await postJSON("/api/me/password", { old_password: $("#pw-old").value, new_password: $("#pw-new").value });
    $("#pw-form").reset(); keyStatus(""); alert("Password updated.");
  } catch (err) { alert(err.message); }
});

// ---------- banner ----------
function banner(content, kind = "info") {
  const b = $("#banner"); b.replaceChildren(...[].concat(content).filter(Boolean)); b.className = `banner ${kind}`; b.hidden = false;
}

// ---------- share queue -> upload -> live status cards ----------
async function drainQueue() {
  if (state.draining) return;
  state.draining = true;
  try {
    const entries = (await SaverQueue.all()).sort((a, b) => a.created - b.created);
    for (const entry of entries) {
      const parts = entry.files && entry.files.length ? entry.files.map((f, i) => ({ file: f, i })) : [{ file: null, i: 0 }];
      let allSent = true;
      for (const p of parts) {
        const label = p.file ? p.file.name || KIND_LABEL.document : snippet(entry.text || entry.url || entry.title, 70);
        const card = pendingCard(label);
        try {
          const res = await uploadWithRetry(entry, p, card);
          watch(res.id, card);
        } catch (err) {
          allSent = false;
          setCard(card, "error", `Not sent: ${err.message}. It's kept on this phone and will be retried next time you open the app.`);
        }
      }
      if (allSent) await SaverQueue.remove(entry.id);
    }
  } finally { state.draining = false; }
}

async function uploadWithRetry(entry, part, card) {
  const delays = [0, 3, 6, 10, 15, 20, 25]; // ~80 s: covers a sleeping free-tier server waking up
  let lastErr;
  for (let n = 0; n < delays.length; n++) {
    if (delays[n]) { setCard(card, "wait", `Server is waking up… retrying (${n}/${delays.length - 1})`); await sleep(delays[n] * 1000); }
    const fd = new FormData();
    fd.append("client_id", `${entry.id}-${part.i}`);
    fd.append("text", entry.text || ""); fd.append("title", entry.title || ""); fd.append("url", entry.url || "");
    if (part.file) fd.append("file", part.file, part.file.name || "shared-file");
    try {
      setCard(card, "wait", part.file ? "Uploading…" : "Sending…");
      return await api("/api/ingest", { method: "POST", body: fd });
    } catch (err) {
      lastErr = err;
      if (err.status && err.status < 500) throw err; // 4xx won't fix itself
    }
  }
  throw lastErr || new Error("network error");
}

function pendingCard(label) {
  const card = h("div", { class: "card pending" },
    h("div", { class: "pending-row" }, h("span", { class: "spinner" }), h("strong", {}, label)),
    h("p", { class: "status-line" }, "Waiting…"));
  $("#inbox").prepend(card);
  return card;
}
function setCard(card, kind, text) {
  card.querySelector(".status-line").textContent = text;
  card.classList.toggle("is-error", kind === "error");
  const sp = card.querySelector(".spinner"); if (sp) sp.hidden = kind === "error";
}

async function watch(messageId, card) {
  setCard(card, "wait", "Reading it… (usually 5–20 seconds)");
  const until = Date.now() + 3 * 60 * 1000;
  while (Date.now() < until) {
    await sleep(2000);
    let res;
    try { res = await api(`/api/messages/${messageId}`); } catch { continue; }
    const st = res.message.status;
    if (st === "processing") continue;
    if (st === "processed" && res.item) {
      card.remove();
      state.freshId = messageId;
      if (state.tab !== "all" || state.q || state.category) { state.q = ""; state.category = ""; $("#search").value = ""; $("#category").value = ""; setTab("all"); }
      else loadList();
      loadReviewCount();
      return;
    } else if (st === "stored") {
      card.replaceWith(messageCard(res.message, "Saved. This type isn't read automatically yet."));
    } else {
      card.replaceWith(messageCard(res.message));
    }
    loadList(); loadReviewCount();
    return;
  }
  setCard(card, "wait", "Still working in the background. Check “Needs review” later.");
}

// ---------- cards ----------
function deadlineBadge(deadline) {
  const n = daysLeft(deadline); if (n == null) return null;
  const cls = n < 0 ? "past" : n <= 3 ? "urgent" : n <= 7 ? "soon" : "later";
  const txt = n < 0 ? `Was due ${fmtDate(deadline)}` : n === 0 ? "Due today" : n === 1 ? "Due tomorrow" : `Due ${fmtDate(deadline)} · ${n} days`;
  return h("span", { class: `badge ${cls}` }, txt);
}

function itemCard(it, { fresh = false } = {}) {
  const keyDates = (it.key_dates || []).filter((d) => d && d.date);
  const actions = it.action_items || [];
  const metaBits = [it.issuing_authority, it.reference_no && `Ref: ${it.reference_no}`, it.issue_date && `Issued ${fmtDate(it.issue_date)}`].filter(Boolean);
  const ytMeta = it.source_meta && it.content_kind === "youtube" ? [it.source_meta.channel].filter(Boolean) : [];

  const card = h("article", { class: `card item${fresh ? " fresh" : ""}` },
    h("div", { class: "card-top" },
      h("span", { class: "chip cat" }, it.category || "other"),
      h("span", { class: "chip kind" }, KIND_LABEL[it.content_kind] || it.content_kind || ""),
      fresh && h("span", { class: "chip saved" }, "✓ Saved"),
      deadlineBadge(it.deadline)),
    h("h2", {}, it.title || "(untitled)"),
    (metaBits.length + ytMeta.length > 0) && h("p", { class: "meta" }, [...metaBits, ...ytMeta].join(" · ")),
    it.summary && h("p", { class: "summary" }, it.summary),
    (keyDates.length + actions.length > 0) && h("details", { class: "more" },
      h("summary", {}, [keyDates.length > 0 && `${keyDates.length} date${keyDates.length > 1 ? "s" : ""}`, actions.length > 0 && `${actions.length} action${actions.length > 1 ? "s" : ""}`].filter(Boolean).join(" · ")),
      keyDates.length > 0 && h("ul", { class: "dates" }, keyDates.map((d) => h("li", {}, h("b", {}, fmtDate(d.date) + (d.time ? ` ${d.time}` : "")), " — ", d.label))),
      actions.length > 0 && h("ul", { class: "actions-list" }, actions.map((a) => h("li", {}, a)))),
    (it.tags || []).length > 0 && h("div", { class: "tags" }, it.tags.map((t) => h("button", { class: "tag", onclick: () => searchFor(t) }, "#" + t))),
    h("div", { class: "card-actions" },
      it.source_url && h("a", { class: "btn", href: it.source_url, target: "_blank", rel: "noopener" }, it.content_kind === "youtube" ? "Watch" : "Open link"),
      it.media_path && h("button", { class: "btn", onclick: () => openOriginal(it.message_id) }, "Original"),
      h("span", { class: "date-added" }, fmtDate(it.created_at)),
      h("button", { class: "btn ghost danger", onclick: (e) => removeMessage(it.message_id, e.target.closest(".card")) }, "Delete")));
  return card;
}

function messageCard(m, note) {
  const label = m.filename || snippet(m.text_content || m.shared_title || "", 120) || KIND_LABEL[m.content_kind];
  const statusTxt = note || (m.status === "failed" ? "Couldn't read this automatically." : m.status === "processing" ? "Still being read…" : "Saved (not read automatically).");
  return h("article", { class: `card msg ${m.status}` },
    h("div", { class: "card-top" },
      h("span", { class: "chip kind" }, KIND_LABEL[m.content_kind] || m.content_kind),
      h("span", { class: `chip st-${m.status}` }, m.status),
      h("span", { class: "date-added" }, fmtDate(m.received_at))),
    h("p", { class: "summary" }, label),
    h("p", { class: "meta" }, statusTxt),
    m.error && h("details", { class: "more" }, h("summary", {}, "Error details"), h("pre", { class: "err" }, m.error)),
    h("div", { class: "card-actions" },
      ["failed", "processing"].includes(m.status) && h("button", { class: "btn", onclick: (e) => retryMessage(m.id, e.target.closest(".card")) }, "Retry"),
      m.media_path && h("button", { class: "btn", onclick: () => openOriginal(m.id) }, "Original"),
      h("button", { class: "btn ghost danger", onclick: (e) => removeMessage(m.id, e.target.closest(".card")) }, "Delete")));
}

async function openOriginal(messageId) {
  const w = window.open("", "_blank"); // open synchronously so pop-up blockers allow it
  try { const r = await api(`/api/file/${messageId}`); if (w) w.location = r.url; else location.href = r.url; }
  catch (err) { if (w) w.close(); banner(`Couldn't open file: ${err.message}`, "error"); }
}
async function removeMessage(messageId, card) {
  if (!confirm("Delete this item and its original file?")) return;
  try { await api(`/api/messages/${messageId}`, { method: "DELETE" }); card.remove(); loadReviewCount(); }
  catch (err) { banner(`Delete failed: ${err.message}`, "error"); }
}
async function retryMessage(messageId, card) {
  try {
    await api(`/api/messages/${messageId}/retry`, { method: "POST" });
    const p = pendingCard("Retrying…"); card.remove(); watch(messageId, p);
  } catch (err) { banner(`Retry failed: ${err.message}`, "error"); }
}

// ---------- lists ----------
let listSeq = 0;
async function loadList() {
  const seq = ++listSeq;
  const list = $("#list"), empty = $("#empty");
  $("#filters").hidden = state.tab === "review";
  try {
    let nodes;
    if (state.tab === "review") {
      const msgs = await api("/api/messages?status=failed,stored,processing");
      nodes = msgs.map((m) => messageCard(m));
      empty.textContent = "Nothing needs review.";
    } else {
      const p = new URLSearchParams({ q: state.q, category: state.category, upcoming: state.tab === "upcoming", limit: 100 });
      const items = await api(`/api/items?${p}`);
      nodes = items.map((it) => itemCard(it, { fresh: it.message_id === state.freshId }));
      empty.textContent = state.q || state.category ? "No matches." : state.tab === "upcoming" ? "No upcoming deadlines." : "Nothing saved yet. Share something from WhatsApp → Saver.";
    }
    if (seq !== listSeq) return;
    list.replaceChildren(...nodes);
    empty.hidden = nodes.length > 0;
    const fresh = list.querySelector(".fresh");
    if (fresh) { state.freshId = null; fresh.scrollIntoView({ behavior: "smooth", block: "center" }); setTimeout(() => fresh.classList.remove("fresh"), 5000); }
  } catch (err) {
    if (seq !== listSeq || err.status === 401) return;
    list.replaceChildren(); empty.hidden = false;
    empty.textContent = `Couldn't load (${err.message}). If the server was asleep, tap ⟳ in a few seconds.`;
  }
}
async function loadReviewCount() {
  try {
    const n = (await api("/api/messages?status=failed")).length;
    const c = $("#review-count"); c.textContent = n; c.hidden = n === 0;
  } catch {}
}
function searchFor(t) { $("#search").value = t; state.q = t; setTab(state.tab === "review" ? "all" : state.tab); }
function setTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  loadList();
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
let searchTimer;
$("#search").addEventListener("input", (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.q = e.target.value.trim(); loadList(); }, 300); });
$("#category").addEventListener("change", (e) => { state.category = e.target.value; loadList(); });
$("#refresh-btn").addEventListener("click", () => { drainQueue(); loadList(); loadReviewCount(); });

// ---------- manual add (also works on iPhone / desktop) ----------
$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#add-text").value.trim(), files = [...$("#add-files").files];
  if (!text && !files.length) return;
  await SaverQueue.add({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, title: "", text, url: "", files, created: Date.now() });
  $("#add-form").reset(); $("#add-box").open = false;
  drainQueue();
});

// ---------- install hint ----------
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); state.installEvt = e; maybeInstallHint(); });
function maybeInstallHint() {
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone || store.get("saver_hide_install")) return;
  const btn = state.installEvt && h("button", { class: "btn primary", onclick: async () => { state.installEvt.prompt(); await state.installEvt.userChoice; $("#banner").hidden = true; } }, "Install app");
  banner([h("span", {}, "Install Saver so it shows up in WhatsApp's Share menu. ", btn ? "" : "Chrome menu ⋮ → Add to Home screen / Install app."),
          btn, h("button", { class: "btn ghost", onclick: () => { store.set("saver_hide_install", "1"); $("#banner").hidden = true; } }, "Hide")]);
}

function maybeKeyHint() {
  if (!store.get(GKEY) && !state.config.shared_key_available) {
    banner([h("span", {}, "One-time setup: add your free Gemini key so Saver can read your shares."),
            h("button", { class: "btn primary", onclick: openSettings }, "Add key")], "info");
  } else { $("#banner").hidden = true; maybeInstallHint(); }
}

// ---------- start ----------
async function startMain() {
  try {
    const cats = await api("/api/categories");
    const sel = $("#category");
    sel.replaceChildren(h("option", { value: "" }, "All categories"), ...cats.map((c) => h("option", { value: c }, c)));
  } catch {}
  maybeKeyHint();
  drainQueue();
  loadList();
  loadReviewCount();
}

(async function boot() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  const params = new URLSearchParams(location.search);
  if ([...params.keys()].length) history.replaceState(null, "", "/");
  try { state.config = await (await fetch("/api/config")).json(); } catch {}
  setAuthMode("login");
  if (!store.get(TOKEN_KEY)) { showLogin(); return; }
  showMain();
  if (params.has("share_missed")) banner("That share arrived before the app was ready. Please share it again.", "error");
  if (params.has("share_error")) banner("Couldn't read that share. Try again, or use “Add manually”.", "error");
  await startMain();
})();

// Re-check queue when the app comes back to the foreground
document.addEventListener("visibilitychange", () => { if (!document.hidden && store.get(TOKEN_KEY)) drainQueue(); });
