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

// 1) paint from cache instantly, 2) refresh from the server.
try {
  const c = JSON.parse(store.get("cache") || "null");
  if (c) { renderStatus(c.st); renderActions(c.rows); }
} catch { /* ignore bad cache */ }
if (!store.get("token")) askToken();
refresh();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
