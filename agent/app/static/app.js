// Renders cached data immediately (feels instant), then refreshes from the server.
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Authorization": "Bearer " + (store.get("token") || ""), "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (res.status === 401) { askToken(); throw new Error("unauthorized"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function askToken() {
  const dlg = $("login");
  if (!dlg.open) dlg.showModal();
}
$("loginForm").addEventListener("submit", () => {
  store.set("token", $("tokenInput").value.trim());
  setTimeout(() => { refresh(); loadBriefing(); }, 0);
});

function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + " min ago";
  if (s < 129600) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " d ago";
}

function renderStatus(st) {
  const mode = $("mode");
  mode.textContent = st.dry_run_default ? "Preview mode" : "Live";
  mode.classList.toggle("live", !st.dry_run_default);
  $("real").disabled = st.dry_run_default;
  const n = $("notice");
  n.hidden = !st.dry_run_default;
  n.textContent = st.dry_run_default
    ? "Safety: the server is in preview mode, so nothing is trashed. Set TRIAGE_DRY_RUN=false on the Mac mini to go live."
    : "";
  const r = st.last_run;
  $("summary").innerHTML = r
    ? `Last run <strong>${ago(r.finished_at || r.started_at)}</strong> · examined <strong>${r.examined}</strong> · ` +
      `${r.dry_run ? "would trash" : "trashed"} <strong>${r.trashed}</strong>` +
      (r.error ? ` · <span style="color:var(--danger)">error</span>` : "") +
      (st.schedule ? ` · nightly at ${esc(st.schedule)}` : "")
    : "No runs yet. Tap Preview run to see what it would do.";
}

function renderActions(rows) {
  const ul = $("actions");
  if (!rows.length) { ul.innerHTML = '<li class="empty">Nothing yet.</li>'; return; }
  ul.innerHTML = rows.map((a) => {
    const canUndo = a.action === "trash" && !a.dry_run && !a.undone;
    return `<li>
      <div class="subject">${esc(a.subject || "(no subject)")}</div>
      <div class="meta">${esc(a.sender)}</div>
      <div class="meta"><span class="tag ${esc(a.action)}">${a.dry_run ? "would " : ""}${esc(a.action)}${a.undone ? " (restored)" : ""}</span> · ${esc(a.reason)}</div>
      ${canUndo ? `<button class="undo secondary" data-id="${a.id}">Restore</button>` : ""}
    </li>`;
  }).join("");
}

async function refresh() {
  try {
    const [st, rows] = await Promise.all([api("/api/status"), api("/api/actions?limit=60")]);
    store.set("cache", JSON.stringify({ st, rows }));
    renderStatus(st); renderActions(rows);
  } catch (e) {
    if (e.message !== "unauthorized") $("summary").textContent = "Can't reach your Mac mini. Is Tailscale on?";
  }
}

async function run(dry) {
  const btns = [$("dry"), $("real")];
  btns.forEach((b) => (b.disabled = true));
  $("summary").textContent = dry ? "Previewing…" : "Running…";
  try { await api("/api/triage/run", { method: "POST", body: JSON.stringify({ dry_run: dry }) }); }
  catch (e) { $("summary").textContent = "Run failed: " + e.message; }
  await refresh();
  $("dry").disabled = false;
}

$("dry").addEventListener("click", () => run(true));
$("real").addEventListener("click", () => {
  if (confirm("Trash promotions from senders you've never engaged with? You can restore any of them.")) run(false);
});
$("actions").addEventListener("click", async (ev) => {
  const btn = ev.target.closest(".undo");
  if (!btn) return;
  btn.disabled = true;
  try { await api(`/api/actions/${btn.dataset.id}/undo`, { method: "POST" }); } catch (e) { alert(e.message); }
  refresh();
});

// ---- Briefing -----------------------------------------------------------------------------
let pollTimer = null;

const CATEGORY_ORDER = ["Family & kids", "School", "Health", "Legal & money", "Work & jobs",
  "Events & plans", "Orders & deliveries", "News & reading", "Other"];
const LOW_PRIORITY = new Set(["Orders & deliveries", "News & reading", "Other"]);
const privateBadge = (i) => (i.sensitive ? '<span class="badge">private</span>' : "");
const dueBadge = (i) => (i.due ? `<span class="due">${esc(i.due)}</span>` : "");

function digestHtml(i) {
  return `<li>
    <div class="summary-line">${esc(i.summary)}</div>
    <div class="who">${esc(i.sender)}${dueBadge(i)}${privateBadge(i)}</div>
  </li>`;
}

function sectionHtml(title, rows) {
  return `<h2>${esc(title)}</h2><ul class="list digest">${rows.map(digestHtml).join("")}</ul>`;
}

function renderBriefing(res) {
  const b = res.briefing;
  const items = b ? b.items : [];
  const todos = items.filter((i) => i.action || i.needs_reply);

  $("overview").textContent = res.running
    ? "Writing your briefing on the Mac mini… this can take a few minutes."
    : b
      ? b.overview || (items.length ? `${items.length} new messages, ${todos.length} need something from you.` : "Nothing new since your last briefing.")
      : "No briefing yet. Tap Refresh briefing.";
  $("bsummary").innerHTML = b && !res.running
    ? `From ${ago(b.created_at)} · ${items.length} messages · ${todos.length} to do`
    : "";
  const note = res.error ? "Last attempt failed: " + res.error : (b && b.note) || "";
  $("bnote").hidden = !note;
  $("bnote").textContent = note;
  $("brefresh").disabled = !!res.running;

  $("todo-wrap").hidden = !todos.length;
  $("todo").innerHTML = todos.map((i) => `<li class="todo-item">
      <div class="todo-action">${esc(i.action || "Reply to " + i.sender)}${dueBadge(i)}${privateBadge(i)}</div>
      <div class="meta">${esc(i.sender)} · ${esc(i.subject)}</div>
    </li>`).join("");

  const groups = new Map();
  for (const i of items) {
    const c = CATEGORY_ORDER.includes(i.category) ? i.category : "Other";
    if (!groups.has(c)) groups.set(c, []);
    groups.get(c).push(i);
  }
  const main = [], low = [];
  for (const c of CATEGORY_ORDER) {
    if (!groups.has(c)) continue;
    (LOW_PRIORITY.has(c) ? low : main).push(sectionHtml(c, groups.get(c)));
  }
  const lowCount = items.filter((i) => LOW_PRIORITY.has(CATEGORY_ORDER.includes(i.category) ? i.category : "Other")).length;
  $("sections").innerHTML = main.join("") +
    (low.length ? `<details class="more"><summary>Also in your inbox (${lowCount})</summary>${low.join("")}</details>` : "");
}

async function loadBriefing() {
  try {
    const res = await api("/api/briefing");
    store.set("bcache", JSON.stringify(res));
    renderBriefing(res);
    clearTimeout(pollTimer);
    if (res.running) pollTimer = setTimeout(loadBriefing, 4000);
  } catch (e) {
    if (e.message !== "unauthorized") $("overview").textContent = "Can't reach your Mac mini. Is Tailscale on?";
  }
}

$("brefresh").addEventListener("click", async () => {
  $("brefresh").disabled = true;
  try { await api("/api/briefing/run", { method: "POST" }); } catch (e) { alert(e.message); }
  loadBriefing();
});

// ---- Chat ---------------------------------------------------------------------------------
let chatBusy = false;

function fmtWhen(iso) {
  const d = new Date(iso);
  return d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function proposalHtml(p) {
  const pl = p.payload;
  let body, buttons;
  if (p.kind === "email") {
    body = `<div class="kind">Email${pl.reply_to_message_id ? " reply" : ""}</div>
      <div class="field">To <strong>${esc(pl.to.join(", "))}</strong></div>
      <div class="field">Subject <strong>${esc(pl.subject)}</strong></div>
      <div class="body">${esc(pl.body)}</div>
      ${pl.new_recipients && pl.new_recipients.length ? `<div class="warn">You've never emailed ${esc(pl.new_recipients.join(", "))}. Check the address.</div>` : ""}`;
    buttons = `<button class="act" data-id="${p.id}" data-mode="send">Send</button>
      <button class="act secondary" data-id="${p.id}" data-mode="draft">Save draft</button>
      <button class="rej secondary" data-id="${p.id}">Don't send</button>`;
  } else {
    body = `<div class="kind">Calendar event</div>
      <div class="field"><strong>${esc(pl.title)}</strong></div>
      <div class="field">${esc(pl.when || fmtWhen(pl.start) + " – " + fmtWhen(pl.end))}</div>
      ${pl.location ? `<div class="field">${esc(pl.location)}</div>` : ""}
      ${pl.attendees && pl.attendees.length ? `<div class="warn">Invites will be emailed to ${esc(pl.attendees.join(", "))}</div>` : ""}
      ${pl.description ? `<div class="body">${esc(pl.description)}</div>` : ""}`;
    buttons = `<button class="act" data-id="${p.id}" data-mode="send">Add to calendar</button>
      <button class="rej secondary" data-id="${p.id}">Skip</button>`;
  }
  const states = { done: "Done", rejected: "Skipped", failed: "Failed", working: "Working…" };
  const footer = p.status === "pending"
    ? `<div class="row">${buttons}</div>`
    : `<div class="state ${esc(p.status)}">${states[p.status] || esc(p.status)}${p.result ? " · " + esc(p.result) : ""}</div>`;
  return `<div class="proposal">${body}${footer}</div>`;
}

function renderChat(data, typing) {
  const setup = data.setup || "";
  $("chat-setup").hidden = !setup;
  $("chat-setup").textContent = setup;
  const items = data.items || [];
  let html = items.map((i) =>
    i.type === "proposal" ? proposalHtml(i) : `<div class="bubble ${i.type}">${esc(i.text)}</div>`).join("");
  if (typing) html += `<div class="bubble user">${esc(typing)}</div><div class="bubble assistant typing">Thinking…</div>`;
  if (!html) html = '<div class="chat-empty">Try “What’s on my calendar tomorrow?” or “Find the email about Sunday’s game and add it to my calendar.”</div>';
  $("chat-log").innerHTML = html;
  window.scrollTo(0, document.body.scrollHeight);
}

let chatCache = { items: [] };
async function loadChat() {
  try {
    chatCache = await api("/api/chat");
    renderChat(chatCache);
  } catch (e) { /* shown elsewhere */ }
}

async function sendChat(text) {
  if (chatBusy || !text.trim()) return;
  chatBusy = true;
  $("chat-send").disabled = true;
  renderChat(chatCache, text);
  try {
    chatCache = await api("/api/chat", { method: "POST", body: JSON.stringify({ text }) });
    if (chatCache.blocked) alert(chatCache.reply);
    renderChat(chatCache);
  } catch (e) {
    renderChat(chatCache);
    $("chat-input").value = text;   // don't lose what you typed
    alert(e.message);
  } finally {
    chatBusy = false;
    $("chat-send").disabled = false;
  }
}

$("composer").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = $("chat-input").value;
  $("chat-input").value = "";
  $("chat-input").style.height = "";
  sendChat(text);
});
$("chat-input").addEventListener("input", (ev) => {
  ev.target.style.height = "auto";
  ev.target.style.height = Math.min(ev.target.scrollHeight, 140) + "px";
});
$("newchat").addEventListener("click", async () => {
  try { chatCache = await api("/api/chat/new", { method: "POST" }); renderChat(chatCache); } catch (e) { alert(e.message); }
});
$("chat-log").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button.act, button.rej");
  if (!btn) return;
  btn.closest(".row").querySelectorAll("button").forEach((b) => (b.disabled = true));
  const id = btn.dataset.id;
  try {
    if (btn.classList.contains("rej")) await api(`/api/proposals/${id}/reject`, { method: "POST" });
    else await api(`/api/proposals/${id}/approve`, { method: "POST", body: JSON.stringify({ mode: btn.dataset.mode }) });
  } catch (e) { alert(e.message); }
  loadChat();
});

function showTab(name) {
  $("view-chat").hidden = name !== "chat";
  $("view-briefing").hidden = name !== "briefing";
  $("view-inbox").hidden = name !== "inbox";
  $("title").textContent = { chat: "Chat", briefing: "Briefing", inbox: "Inbox" }[name];
  if (name === "chat") loadChat();
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  store.set("tab", name);
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

// 1) paint from cache instantly, 2) refresh from the server.
try {
  const c = JSON.parse(store.get("cache") || "null");
  if (c) { renderStatus(c.st); renderActions(c.rows); }
} catch { /* ignore bad cache */ }
try {
  const bc = JSON.parse(store.get("bcache") || "null");
  if (bc) renderBriefing(bc);
} catch { /* ignore bad cache */ }
const savedTab = store.get("tab");
showTab(["chat", "briefing", "inbox"].includes(savedTab) ? savedTab : "chat");
if (!store.get("token")) askToken();
refresh();
loadBriefing();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
