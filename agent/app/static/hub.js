// Cardona Family Hub. Everything shown is fetched live from the Mac mini; nothing is cached.
"use strict";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 5 * 60 * 1000;
let data = null;
let week = 0;

// The hub token is the only thing kept on this device. Opening /hub#t=TOKEN once saves it.
const store = {
  get() { try { return localStorage.getItem("hubToken") || ""; } catch { return ""; } },
  set(v) { try { localStorage.setItem("hubToken", v); } catch { /* private mode: ask again next time */ } },
};
(function tokenFromLink() {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) { store.set(decodeURIComponent(m[1])); history.replaceState(null, "", location.pathname); }
})();

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) { return /^https:\/\//.test(u || "") ? u : null; }

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts, cache: "no-store",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${store.get()}` },
  });
  if (res.status === 401) { askToken(); throw new Error("Needs the hub token"); }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

function askToken() {
  const d = $("login");
  if (!d.open) d.showModal();
}
$("loginForm").addEventListener("submit", () => {
  store.set($("tokenInput").value.trim());
  load();
});

// ---- helpers ---------------------------------------------------------------------------
const people = () => Object.fromEntries((data?.people || []).map((p) => [p.key, p]));
const color = (key) => people()[key]?.color || "#6b7280";
const pname = (key) => people()[key]?.name || key;
function dayLabel(iso, opts) { return new Date(iso + "T12:00").toLocaleDateString([], opts); }
function shortDue(iso) { return iso ? dayLabel(iso, { weekday: "short", month: "short", day: "numeric" }) : ""; }

function tick() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("today").textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const h = now.getHours();
  document.body.classList.toggle("night", h >= 21 || h < 6);
}

// ---- render ----------------------------------------------------------------------------
function evHtml(e) {
  const c = color(e.people[0]);
  const icon = { appointment: "🩺 ", flight: "✈️ ", travel: "🧳 " }[e.kind] || "";
  const dog = e.people.includes("gypsy") ? "🐕 " : "";
  const extra = e.people.slice(1).map((k) => `<span class="dot" style="background:${esc(color(k))}" title="${esc(pname(k))}"></span>`).join("");
  return `<div class="ev ${e.untagged ? "untagged" : ""} ${e.kind === "holiday" ? "holiday" : ""}" style="--c:${esc(c)}">
    <div class="bars">${extra}</div>
    <div><div class="name">${icon}${dog}${esc(e.title)}${e.untagged ? ' <span class="q" title="No name in the title">?</span>' : ""}</div>
    <div class="t">${esc(e.time)}${e.days > 1 ? ` · thru ${esc(dayLabel(e.end, { weekday: "short" }))}` : ""}</div></div></div>`;
}

function renderLegend() {
  $("legend").innerHTML = data.people.map((p) =>
    `<span class="who"><span class="dot" style="background:${esc(p.color)}"></span>${esc(p.name)}</span>`).join("");
}

function renderBanner() {
  const out = [];
  const sb = data.sunbasket || {};
  out.push(`<div class="flag" style="border-left-color:${sb.status === "coming" ? "#d97706" : "var(--line)"}">${esc(sb.text || "Sunbasket: no info")}</div>`);
  const seen = new Set();
  for (const t of data.banner.travel) {
    const key = t.title + t.start;
    if (seen.has(key)) continue;
    seen.add(key);
    const when = t.days > 1 ? `${shortDue(t.start)} – ${shortDue(t.end)}` : `${shortDue(t.start)}${t.all_day ? "" : " · " + t.time}`;
    out.push(`<div class="flag" style="border-left-color:${esc(color(t.people[0]))}">${t.kind === "flight" ? "✈️" : "🧳"} ${esc(t.title)}<small>${esc(when)}</small></div>`);
  }
  for (const a of data.banner.appointments_today) {
    out.push(`<div class="flag" style="border-left-color:${esc(color(a.people[0]))}">🩺 Today: ${esc(a.title)}<small>${esc(a.time)}</small></div>`);
  }
  if (data.untagged.length) {
    out.push(`<div class="flag warn">${data.untagged.length} event${data.untagged.length > 1 ? "s" : ""} with no name — add who it's for in the title<small>${esc(data.untagged.slice(0, 3).map((e) => e.title).join(" · "))}</small></div>`);
  }
  $("banner").innerHTML = out.join("");
}

function renderWeek() {
  $("week").innerHTML = data.days.map((d) => {
    const isToday = d.date === data.today;
    const past = d.date < data.today;
    return `<div class="day ${isToday ? "is-today" : ""} ${past ? "past" : ""}">
      <div class="dayhead">${esc(dayLabel(d.date, { weekday: "short" }))} <span>${esc(dayLabel(d.date, { month: "short", day: "numeric" }))}</span></div>
      ${d.events.length ? d.events.map(evHtml).join("") : '<div class="empty">—</div>'}</div>`;
  }).join("");
}

function renderDinners() {
  const sbComing = data.sunbasket?.status === "coming";
  $("dinners").innerHTML = data.days.map((d) => {
    const meals = data.dinners[d.date] || [];
    const txt = meals.length
      ? meals.map((m) => m.sunbasket
        ? `${esc(m.content.replace(/^\s*sunbasket\s*[:\-–]\s*/i, ""))} <span class="sb">📦 Sunbasket</span>`
        : esc(m.content)).join(" / ")
      : '<span class="empty">—</span>';
    return `<li class="${d.date === data.today ? "is-today" : ""}"><span class="d">${esc(dayLabel(d.date, { weekday: "short" }))}</span><span>${txt}</span></li>`;
  }).join("") + (sbComing ? '<li><span class="d"></span><span class="empty">Sunbasket covers 2 dinners this week</span></li>' : "");
}

function renderHomework() {
  const kids = Object.entries(data.homework || {});
  if (!kids.length) { $("homework").innerHTML = '<div class="empty">No homework info</div>'; return; }
  const soon = new Date(Date.now() + 36 * 3600e3).toISOString().slice(0, 10);
  $("homework").innerHTML = kids.map(([key, k]) => {
    const rows = [];
    for (const m of k.missing) rows.push(`<div class="hw missing">⚠️ Missing: ${esc(m.title)}<span class="cls">${esc(m.class)} · was due ${esc(shortDue(m.due))}</span></div>`);
    for (const m of k.due) rows.push(`<div class="hw ${m.due && m.due <= soon ? "soon" : ""}">${esc(m.title)}<span class="cls">${esc(m.class)} · due ${esc(shortDue(m.due))}</span></div>`);
    for (const u of k.updates.slice(0, 4)) {
      const link = safeUrl(u.link);
      rows.push(`<div class="hw">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">✉️ ${esc(u.subject)}</a>` : esc(u.subject)}</div>`);
    }
    if (!rows.length) rows.push(`<div class="empty">Nothing from ${esc(k.school)} this week</div>`);
    return `<div class="kid"><h3><span class="dot" style="background:${esc(color(key))}"></span>${esc(pname(key))}</h3>${rows.join("")}</div>`;
  }).join("");
}

function checkBtn(cls, item, label, extra = "") {
  return `<button class="${cls}" data-id="${esc(item.id)}"><span class="box"></span><span>${esc(label)}</span>${extra}</button>`;
}

function renderGroceries() {
  if (data.errors.todoist) { $("groceries").innerHTML = '<div class="empty">Groceries unavailable (Todoist)</div>'; return; }
  const groups = data.groceries || [];
  $("groceries").innerHTML = groups.length
    ? groups.map((g) => `<h4>${esc(g.section)}</h4>${g.items.map((i) => checkBtn("item", i, i.content)).join("")}`).join("")
    : '<div class="empty">List is empty</div>';
}

function renderTasks() {
  if (data.errors.todoist) { $("tasks").innerHTML = `<div class="empty">${esc(data.errors.todoist)}</div>`; return; }
  const order = [...data.people.map((p) => p.key)];
  $("tasks").innerHTML = order.filter((k) => (data.tasks[k] || []).length || ["taryn", "phillip", "brooks", "elliott", "cece"].includes(k))
    .map((k) => {
      const list = data.tasks[k] || [];
      const items = list.length ? list.map((t) => checkBtn(`task ${t.overdue ? "overdue" : ""}`, t, t.content,
        t.due ? `<span class="due">${esc(t.overdue ? "overdue" : shortDue(t.due))}</span>` : "")).join("")
        : '<div class="empty">All done 🎉</div>';
      return `<div class="col" style="--c:${esc(color(k))}"><h3><span class="dot" style="background:${esc(color(k))}"></span>${esc(pname(k))}</h3>${items}</div>`;
    }).join("");
}

function renderStatus() {
  const errs = Object.entries(data.errors || {}).filter(([k]) => k !== "todoist");
  const when = new Date(data.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("status").innerHTML = `Updated ${esc(when)} · live from Google & Todoist` +
    errs.map(([k, v]) => ` · <span class="err">${esc(k)} unavailable: ${esc(v)}</span>`).join("");
}

function render() {
  renderLegend(); renderBanner(); renderWeek(); renderDinners(); renderHomework(); renderGroceries(); renderTasks(); renderStatus();
}

async function load() {
  if (!store.get()) { askToken(); return; }
  try {
    data = await api(`/api/hub?week=${week}`);
    render();
  } catch (e) {
    $("status").innerHTML = `<span class="err">Can't reach the hub: ${esc(e.message)}. Retrying in a minute.</span>`;
    setTimeout(load, 60 * 1000);
  }
}

// ---- interactions ------------------------------------------------------------------------
// Two taps to check something off, so a passing elbow doesn't clear a task.
document.addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button.item, button.task");
  if (!btn || btn.classList.contains("done")) return;
  if (!btn.classList.contains("confirm")) {
    document.querySelectorAll(".confirm").forEach((b) => b.classList.remove("confirm"));
    btn.classList.add("confirm");
    setTimeout(() => btn.classList.remove("confirm"), 4000);
    return;
  }
  btn.classList.remove("confirm");
  btn.classList.add("done");
  try { await api(`/api/hub/tasks/${encodeURIComponent(btn.dataset.id)}/close`, { method: "POST" }); }
  catch (e) { btn.classList.remove("done"); alert(e.message); }
});

$("addgrocery").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const item = $("groceryInput").value.trim();
  if (!item) return;
  $("groceryInput").value = "";
  try { await api("/api/hub/groceries", { method: "POST", body: JSON.stringify({ item }) }); load(); }
  catch (e) { alert(e.message); $("groceryInput").value = item; }
});

function setWeek(w) {
  week = w;
  $("thisweek").classList.toggle("on", w === 0);
  $("nextweek").classList.toggle("on", w === 1);
  load();
}
$("thisweek").addEventListener("click", () => setWeek(0));
$("nextweek").addEventListener("click", () => setWeek(1));

document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
tick();
setInterval(tick, 20 * 1000);
setInterval(() => { if (week === 1) setWeek(0); else load(); }, REFRESH_MS);   // the screen drifts back to this week
load();
