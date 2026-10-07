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
  setTimeout(refresh, 0);
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

// ---- Chief-of-Staff briefing ------------------------------------------------------------
// A tiny, safe Markdown subset: everything is escaped first; only http(s) links become <a>.
function inline(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function mdToHtml(md) {
  const out = [];
  let list = false, open = false;
  const closeList = () => { if (list) { out.push("</ul>"); list = false; } };
  const closeSec = () => { closeList(); if (open) { out.push("</div>"); open = false; } };
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    if (!line) { closeList(); continue; }
    const h = line.match(/^#{1,3}\s+(.*)$/);
    const li = line.match(/^(?:[-*•]|\d+\.)\s+(.*)$/);
    if (h) { closeSec(); out.push(`<h3>${inline(h[1])}</h3><div class="sec">`); open = true; }
    else if (li) { if (!open) { out.push('<div class="sec">'); open = true; } if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(li[1])}</li>`); }
    else { closeList(); if (!open) { out.push('<div class="sec">'); open = true; } out.push(`<p>${inline(line)}</p>`); }
  }
  closeSec();
  return out.join("");
}

let morningTimer = null;
function renderMorning(res) {
  const b = res.briefing;
  $("mstatus").innerHTML = res.running
    ? "Researching and writing your briefing… this takes a few minutes."
    : b ? `Briefing from <strong>${ago(b.created_at)}</strong>${res.schedule ? ` · daily at ${esc(res.schedule)}` : ""}`
      : "No briefing yet. Tap Refresh briefing.";
  const note = res.error ? "Last attempt failed: " + res.error : (b && b.note) || "";
  $("mnote").hidden = !note;
  $("mnote").textContent = note;
  $("mrefresh").disabled = !!res.running;
  $("mbody").innerHTML = b ? mdToHtml(b.markdown) : "";
  const sources = (b && b.sources) || [];
  $("msources").hidden = !sources.length;
  $("msourcelist").innerHTML = sources.map((x) =>
    `<li><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a></li>`).join("");
}

async function loadMorning() {
  try {
    const res = await api("/api/morning");
    store.set("mcache", JSON.stringify(res));
    renderMorning(res);
    clearTimeout(morningTimer);
    if (res.running) morningTimer = setTimeout(loadMorning, 5000);
  } catch (e) {
    if (e.message !== "unauthorized") $("mstatus").textContent = "Can't reach your Mac mini. Is Tailscale on?";
  }
}

$("mrefresh").addEventListener("click", async () => {
  $("mrefresh").disabled = true;
  try { await api("/api/morning/run", { method: "POST" }); } catch (e) { alert(e.message); }
  loadMorning();
});

// ---- Budget (all data stays on the Mac mini) ----------------------------------------------
const usd = (n, cents) => (n == null ? "—" : Number(n).toLocaleString("en-US",
  { style: "currency", currency: "USD", maximumFractionDigits: cents ? 2 : 0, minimumFractionDigits: cents ? 2 : 0 }));
let budgetData = null;

function goalHtml(g) {
  if (!g) {
    return `<div class="summary">Set your target home price to see if you're on track.</div>
      <div class="row"><button id="opengoal">Set target price</button></div>`;
  }
  const verdict = g.on_track == null
    ? `<div class="verdict">Pick your house savings account(s) below to see your monthly pace.</div>`
    : g.on_track
      ? `<div class="verdict good">On track: saving about ${usd(g.saving_per_month)}/mo; you need ${usd(g.needed_per_month)}/mo.</div>`
      : `<div class="verdict bad">Behind by about ${usd(g.gap_per_month)}/mo. Saving ${usd(g.saving_per_month)}/mo; you need ${usd(g.needed_per_month)}/mo.</div>`;
  return `<div class="kind meta">Down payment + closing by ${esc(new Date(g.target_date + "T12:00").toLocaleDateString([], { month: "long", year: "numeric" }))}</div>
    <div class="big">${usd(g.saved)} <span class="meta" style="font-size:16px;font-weight:500">of ${usd(g.goal)}</span></div>
    <div class="bar ok"><span style="width:${Math.min(g.percent, 100)}%"></span></div>
    <div class="goal-grid">
      <div class="stat"><div class="label">Still needed</div><div class="val">${usd(g.remaining)}</div></div>
      <div class="stat"><div class="label">Per month</div><div class="val">${usd(g.needed_per_month)}</div></div>
      <div class="stat"><div class="label">Months left</div><div class="val">${esc(g.months_left)}</div></div>
      <div class="stat"><div class="label">Projected by then</div><div class="val">${usd(g.projected_at_target)}</div></div>
    </div>
    ${verdict}
    <div class="meta" style="margin-top:6px">20% down ${usd(g.down_payment)} · closing ${usd(g.closing_costs)}${g.cushion ? " · cushion " + usd(g.cushion) : ""}</div>`;
}

function renderBudget(d) {
  budgetData = d;
  const note = d.error ? "Sync failed: " + d.error
    : (!d.accounts.length ? "No accounts yet. Connect your banks on the Mac mini (python -m app.secrets set-simplefin), then tap Sync, or import a card CSV below." : "");
  $("bnote").hidden = !note;
  $("bnote").textContent = note;
  $("goal").innerHTML = goalHtml(d.goal);
  const og = $("opengoal");
  if (og) og.onclick = () => { $("goalsettings").open = true; $("gprice").focus(); };

  const rec = d.cuts.recurring, hot = d.cuts.running_hot;
  $("cuts-wrap").hidden = !rec.length && !hot.length;
  $("cuts").innerHTML =
    (rec.length ? `<p class="meta" style="margin:0 4px 8px">Subscriptions and bills that repeat every month.</p><ul class="list">${rec.map((r) => `<li>
      <div class="cut-row"><span class="subject">${esc(r.merchant)}</span><span class="amt">${usd(r.monthly, true)}/mo</span></div>
      <div class="meta">${esc(r.category)} · ${usd(r.yearly)}/yr · cancelling adds ${usd(r.adds_by_target)} by your date</div></li>`).join("")}</ul>` : "") +
    (hot.length ? `<h2>Running hot this month</h2><ul class="list">${hot.map((h) => `<li>
      <div class="cut-row"><span class="subject">${esc(h.category)}</span><span class="amt">+${usd(h.over_by)}</span></div>
      <div class="meta">On pace for ${usd(h.projected)} vs. usual ${usd(h.usual)}</div></li>`).join("")}</ul>` : "");

  $("month-title").textContent = "This month · " + new Date(d.month + "-15").toLocaleDateString([], { month: "long" });
  $("cats").innerHTML = d.categories.length ? d.categories.map((c) => `<li class="cat-row" data-cat="${esc(c.category)}">
      <div class="cat-head"><span class="subject">${esc(c.category)}</span>
        <span>${usd(c.spent)}${c.limit ? ` <span class="meta">/ ${usd(c.limit)}</span>` : ""}</span></div>
      ${c.limit ? `<div class="bar ${esc(c.status)}"><span style="width:${Math.min(c.percent, 100)}%"></span></div>` : ""}
      <div class="meta"><button class="link setlimit" data-cat="${esc(c.category)}">${c.limit ? "Change limit" : "Set a limit"}</button></div>
      <div class="txns" hidden></div></li>`).join("") : '<li class="empty">No spending yet this month.</li>';

  $("uncat-wrap").hidden = !d.uncategorized.length;
  const opts = (sel) => d.category_names.concat(["Income", "Transfer"]).map((c) =>
    `<option ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
  $("uncat").innerHTML = d.uncategorized.map((m) => `<li><div class="acct-row"><span class="subject">${esc(m)}</span>
      <select class="recat" data-merchant="${esc(m)}"><option value="">Choose…</option>${opts("")}</select></div></li>`).join("");

  $("accts").innerHTML = d.accounts.length ? d.accounts.map((a) => `<li>
      <div class="acct-row"><span class="subject">${esc(a.name)}</span><span>${a.balance == null ? "" : usd(a.balance)}</span></div>
      <div class="meta">${esc(a.org)}${a.hidden ? " · hidden from budget" : ""}</div>
      <div class="acct-btns"><button class="toggle secondary ${a.is_house ? "on" : ""}" data-acct="${esc(a.id)}" data-flag="is_house">${a.is_house ? "House savings ✓" : "Count as house savings"}</button>
        <button class="toggle secondary" data-acct="${esc(a.id)}" data-flag="hidden">${a.hidden ? "Show" : "Hide"}</button></div></li>`).join("")
    : '<li class="empty">No accounts connected yet.</li>';

  $("bsync").disabled = !!d.running;
  $("bsync").textContent = d.running ? "Syncing…" : "Sync banks now";
  $("bsyncinfo").textContent = (d.last_sync ? "Last synced " + ago(d.last_sync) + "." : "") +
    (d.sync_errors && d.sync_errors.length ? " Bank messages: " + d.sync_errors.join("; ") : "");

  const s = d.settings || {};
  if (document.activeElement.closest("#goalsettings") == null) {
    $("gprice").value = s.target_price || "";
    $("gdown").value = ((s.down_pct ?? 0.2) * 100).toString();
    $("gclose").value = ((s.closing_pct ?? 0.03) * 100).toString();
    $("gcush").value = s.cushion || "";
    $("gdate").value = s.target_date || "2027-05-01";
  }
  if (d.running) setTimeout(loadBudget, 4000);
}

async function loadBudget() {
  try { renderBudget(await api("/api/budget")); }
  catch (e) { if (e.message !== "unauthorized") { $("bnote").hidden = false; $("bnote").textContent = "Can't load the budget: " + e.message; } }
}

async function budgetPost(path, body) {
  try { renderBudget(await api(path, { method: "POST", body: JSON.stringify(body) })); } catch (e) { alert(e.message); }
}

$("gsave").addEventListener("click", () => {
  const num = (id) => ($(id).value === "" ? null : Number($(id).value));
  budgetPost("/api/budget/settings", {
    target_price: num("gprice"), down_pct: num("gdown") / 100, closing_pct: num("gclose") / 100,
    cushion: num("gcush") ?? 0, target_date: $("gdate").value || null,
  });
  $("goalsettings").open = false;
});

$("view-budget").addEventListener("click", async (ev) => {
  const t = ev.target;
  if (t.matches(".toggle[data-acct]")) {
    const a = budgetData.accounts.find((x) => x.id === t.dataset.acct);
    budgetPost(`/api/budget/accounts/${encodeURIComponent(a.id)}`, { [t.dataset.flag]: !a[t.dataset.flag] });
  } else if (t.matches(".setlimit")) {
    const cur = budgetData.categories.find((c) => c.category === t.dataset.cat);
    const v = prompt(`Monthly limit for ${t.dataset.cat} (leave empty to remove):`, cur && cur.limit ? cur.limit : "");
    if (v !== null) budgetPost("/api/budget/limits", { category: t.dataset.cat, monthly_limit: v === "" ? null : Number(v) });
  } else if (t.closest(".cat-row") && !t.closest("button") && !t.closest(".txns")) {
    const row = t.closest(".cat-row"), box = row.querySelector(".txns");
    if (!box.hidden) { box.hidden = true; return; }
    try {
      const rows = await api(`/api/budget/transactions?month=${budgetData.month}&category=${encodeURIComponent(row.dataset.cat)}`);
      box.innerHTML = rows.map((r) => `<div><span>${esc(r.date.slice(5))} ${esc(r.merchant)}</span><span>${usd(-r.amount, true)}</span></div>`).join("") || "<div>No transactions.</div>";
      box.hidden = false;
    } catch (e) { alert(e.message); }
  }
});
$("view-budget").addEventListener("change", (ev) => {
  if (ev.target.matches(".recat") && ev.target.value)
    budgetPost("/api/budget/merchant", { merchant: ev.target.dataset.merchant, category: ev.target.value });
});
$("bsync").addEventListener("click", async () => {
  try { await api("/api/budget/sync", { method: "POST" }); } catch (e) { alert(e.message); }
  loadBudget();
});
$("csvgo").addEventListener("click", async () => {
  const file = $("csvfile").files[0];
  if (!file) { alert("Choose a CSV file first."); return; }
  const text = await file.text();
  try {
    const res = await api("/api/budget/import", { method: "POST", body: JSON.stringify({ account_name: $("csvname").value || file.name, csv: text }) });
    alert(`Imported ${res.imported.new_transactions} new transactions.`);
    renderBudget(res);
  } catch (e) { alert("Import failed: " + e.message); }
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
  $("view-morning").hidden = name !== "morning";
  $("view-budget").hidden = name !== "budget";
  $("view-inbox").hidden = name !== "inbox";
  $("title").textContent = { chat: "Chat", morning: "Briefing", budget: "Budget", inbox: "Inbox" }[name];
  if (name === "chat") loadChat();
  if (name === "morning") loadMorning();
  if (name === "budget") loadBudget();
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  store.set("tab", name);
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

// 1) paint from cache instantly, 2) refresh from the server.
try {
  const c = JSON.parse(store.get("cache") || "null");
  if (c) { renderStatus(c.st); renderActions(c.rows); }
} catch { /* ignore bad cache */ }
const savedTab = store.get("tab");
try {
  const mc = JSON.parse(store.get("mcache") || "null");
  if (mc) renderMorning(mc);
} catch { /* ignore bad cache */ }
showTab(["chat", "morning", "budget", "inbox"].includes(savedTab) ? savedTab : "chat");
if (!store.get("token")) askToken();
refresh();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
