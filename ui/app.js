"use strict";
// VOTHUB console. All feed text is untrusted (issue titles come from strangers),
// so everything is rendered with textContent, never innerHTML.

const tauri = window.__TAURI__;
const invoke = tauri ? tauri.core.invoke : mockInvoke();
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

let S = null;          // last status from the backend
let F = null;          // decoded feed
let statusAt = 0;      // local clock when S arrived
let expanded = false;
let pollTimer = 0;
const filter = { lane: -1, tiers: new Set(), kinds: new Set(), lang: "", newOnly: false, hideDocs: false };

// ------------------------------------------------------------------ polling
async function poll() {
  clearTimeout(pollTimer);
  try {
    S = await invoke("status");
    statusAt = Date.now();
    if (S.gen !== (F ? F.gen : 0)) {
      F = await invoke("get_feed");
      renderFeed();
    }
    renderStatus();
  } catch (e) {
    console.error(e);
  }
  // halted: barely tick at all
  pollTimer = setTimeout(poll, S && S.paused ? 30000 : 4000);
}

const nowSec = () => (S ? S.now + (Date.now() - statusAt) / 1000 : Date.now() / 1000);
const pad = (n) => String(Math.floor(n)).padStart(2, "0");
const hms = (s) => (s <= 0 ? "00:00:00" : `${pad(s / 3600)}:${pad((s % 3600) / 60)}:${pad(s % 60)}`);
const clock = (t) => new Date(t * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
function ago(sec) {
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))}m`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86400)}d`;
}

// ------------------------------------------------------------------- status
function renderStatus() {
  if (!S) return;
  document.body.classList.toggle("halted", S.paused);
  const state = S.paused ? "HALTED" : S.syncing ? "RECEIVING..." : F ? "LISTENING" : "NO SIGNAL";
  $("m-state").textContent = $("f-state").textContent = state;
  for (const id of ["m-halt", "f-halt"]) {
    $(id).textContent = S.paused ? "RESUME" : "HALT";
    $(id).className = "btn " + (S.paused ? "go" : "danger");
  }
  $("f-sync").disabled = S.paused;
  $("f-rescan").disabled = S.paused || S.rescanning;
  $("f-rescan").textContent = S.rescanning ? "SCANNING..." : "RESCAN";
  $("cfg-token").placeholder = S.has_token ? "stored // set empty to forget" : "github_pat_...";
  $("cfg-token-hint").textContent = S.has_token
    ? "Token is in Windows Credential Manager. RESCAN is armed."
    : "Needed only for RESCAN. Fine-grained token, this repo only, Actions: read and write.";
  $("m-status").textContent = $("f-status").textContent = S.status || (S.repo ? "STANDING BY" : "SET FEED REPO");
  $("cfg-auto").checked = S.autostart;
  if (document.activeElement !== $("cfg-repo")) $("cfg-repo").value = S.repo;
  tick();
}

function tick() {
  if (!S) return;
  let text;
  if (S.paused) {
    text = S.paused_until === -1 ? "HALTED UNTIL RESUMED" : `HALTED ${hms(S.paused_until - nowSec())}`;
  } else if (!S.next_sync) {
    text = "NEXT SCAN --:--:--";
  } else {
    text = `NEXT SCAN ${hms(S.next_sync - nowSec())}`;
  }
  $("m-next").textContent = text;
  $("f-next").textContent = text.replace("NEXT SCAN ", "");
}
setInterval(tick, 1000);

// --------------------------------------------------------------------- feed
function visibleIssues() {
  if (!F) return [];
  return F.issues.filter((it) => {
    const repo = F.repos[it[0]];
    if (filter.lane >= 0 && repo[4] !== filter.lane) return false;
    if (filter.tiers.size && !filter.tiers.has(it[14])) return false;
    if (filter.kinds.size && !filter.kinds.has(it[5])) return false;
    if (filter.lang && repo[3] !== filter.lang) return false;
    if (filter.newOnly && !it[13]) return false;
    if (filter.hideDocs && F.kinds[it[5]] === "docs") return false;
    return true;
  });
}

function renderFeed() {
  const issues = F ? F.issues : [];
  const run = F && F.runs.length ? F.runs[F.runs.length - 1] : null;
  const numbers = {
    signals: F ? issues.length : "--",
    new: F ? (F.tiers ? issues.filter((i) => i[14] === 0).length : issues.filter((i) => i[13]).length) : "--",
    top: F && issues.length ? issues[0][3] : "--",
    repos: run ? run[2] : "--",
  };
  for (const [k, v] of Object.entries(numbers)) $("m-" + k).textContent = $("f-" + k).textContent = v;

  const top = issues[0];
  $("m-ticker").textContent = top ? `> ${F.repos[top[0]][0]}: ${top[2]}` : "NO SIGNAL // OPEN TO CONFIGURE";
  $("f-gen").textContent = F ? clock(F.gen) : "--";
  $("f-scorer").textContent = F ? F.scorer : "--";

  // sweep log: one bar per run, height = issues found
  const runs = $("f-runs");
  runs.replaceChildren();
  if (F) {
    const peak = Math.max(1, ...F.runs.map((r) => r[3]));
    for (const r of F.runs) {
      const bar = el("i");
      bar.style.height = `${Math.max(4, (r[3] / peak) * 100)}%`;
      bar.title = `${clock(r[0] * 3600)} - ${r[3]} signals, ${r[4]} new, ${r[2]}/${r[1]} repos kept`;
      runs.append(bar);
    }
  }
  buildFilters();
  renderList();
}

function chip(parent, label, on, onClick) {
  const c = el("button", "chip" + (on ? " on" : ""), label);
  c.onclick = () => { onClick(); buildFilters(); renderList(); };
  parent.append(c);
}

function buildFilters() {
  const lane = $("flt-lane"), kind = $("flt-kind"), lang = $("flt-lang"), misc = $("flt-misc"), tier = $("flt-tier");
  for (const n of [lane, kind, lang, misc, tier]) n.replaceChildren();
  if (!F) return;
  // ready = maintainers invited help; vetted = triaged or answered; raw = nobody has looked yet
  (F.tiers || []).forEach((name, i) => {
    const count = F.issues.filter((it) => it[14] === i).length;
    if (count) chip(tier, `${name} ${count}`, filter.tiers.has(i), () => (filter.tiers.has(i) ? filter.tiers.delete(i) : filter.tiers.add(i)));
  });
  chip(lane, "all sectors", filter.lane < 0, () => (filter.lane = -1));
  F.lanes.forEach((name, i) => chip(lane, name, filter.lane === i, () => (filter.lane = i)));
  const used = new Set(F.issues.map((i) => i[5]));
  F.kinds.forEach((name, i) => {
    if (used.has(i)) chip(kind, name, filter.kinds.has(i), () => (filter.kinds.has(i) ? filter.kinds.delete(i) : filter.kinds.add(i)));
  });
  const langs = [...new Set(F.issues.map((i) => F.repos[i[0]][3]))].sort();
  for (const l of langs) chip(lang, l, filter.lang === l, () => (filter.lang = filter.lang === l ? "" : l));
  chip(misc, "new only", filter.newOnly, () => (filter.newOnly = !filter.newOnly));
  chip(misc, "hide docs", filter.hideDocs, () => (filter.hideDocs = !filter.hideDocs));
}

function renderList() {
  const list = $("list");
  list.replaceChildren();
  const rows = visibleIssues();
  $("list-count").textContent = `${rows.length} SIGNAL${rows.length === 1 ? "" : "S"}`;
  if (!rows.length) {
    const empty = el("div", "empty");
    empty.append(el("b", "", F ? "NOTHING MATCHES" : "NO SIGNAL"));
    empty.append(document.createTextNode(F
      ? "Loosen the filters on the left."
      : S && S.repo
        ? "Waiting for the first cloud sweep to be published."
        : "Enter the GitHub repo that runs the scan (owner/name) under STATION."));
    list.append(empty);
    return;
  }
  const hoursNow = nowSec() / 3600;
  const frag = document.createDocumentFragment();
  rows.forEach((it, n) => {
    const [ri, num, title, pri, sub, kind, effort, sector, extra, createdH, comments, reactions, why, isNew, tier] = it;
    const repo = F.repos[ri];
    const kindName = F.kinds[kind];
    const row = el("div", "item" + (kindName === "docs" ? " docs" : ""));
    row.title = `Open ${repo[0]}#${num} in the browser`;
    row.onclick = () => invoke("open_issue", { repoIndex: ri, number: num }).catch(console.error);

    row.append(el("div", "rank", String(n + 1).padStart(2, "0")));
    const score = el("div", "score");
    score.append(el("b", "", pri));
    const bar = el("div", "bar"), fill = el("i");
    fill.style.width = pri + "%";
    bar.append(fill);
    score.append(bar);
    row.append(score);

    const body = el("div");
    body.append(el("div", "title", title));
    const meta = el("div", "meta");
    meta.append(el("span", "repo", `${repo[0]}#${num}`));
    meta.append(document.createTextNode(`  *${fmt(repo[1])}  +${(repo[2] / 10).toFixed(repo[2] < 100 ? 1 : 0)}/day  //  ${why}`));
    body.append(meta);
    const tags = el("div", "tags");
    if (F.tiers && F.tiers[tier]) tags.append(el("span", "tag " + F.tiers[tier], F.tiers[tier]));
    if (isNew) tags.append(el("span", "tag new", "new"));
    tags.append(el("span", "tag kind", kindName));
    tags.append(el("span", "tag lang", repo[3]));
    tags.append(el("span", "tag", F.tags[sector]));
    tags.append(el("span", "tag", F.lanes[repo[4]]));
    tags.append(el("span", "tag", `effort ${F.efforts[effort]}`));
    tags.append(el("span", "tag", `substance ${sub}`));
    for (const t of extra) tags.append(el("span", "tag", F.tags[t]));
    body.append(tags);
    row.append(body);

    row.append(el("div", "age", `${ago((hoursNow - createdH) * 3600)} old\n${comments}c ${reactions}r`));
    row.lastChild.style.whiteSpace = "pre";
    frag.append(row);
  });
  list.append(frag);
}

const fmt = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n));

// -------------------------------------------------------------- signal scope
// A cheap 5 fps trace: one peak per top-ranked issue, plus receiver noise.
function drawScope(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
  if (!w || !h) return;
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const g = canvas.getContext("2d");
  const css = getComputedStyle(document.body);
  g.clearRect(0, 0, w, h);
  g.strokeStyle = css.getPropertyValue("--line");
  g.lineWidth = 1;
  g.beginPath();
  for (let i = 1; i < 8; i++) { g.moveTo((w * i) / 8, 0); g.lineTo((w * i) / 8, h); }
  for (let i = 1; i < 3; i++) { g.moveTo(0, (h * i) / 3); g.lineTo(w, (h * i) / 3); }
  g.stroke();

  const peaks = F ? F.issues.slice(0, 22).map((it, n) => [((it[1] * 37 + it[0] * 91 + n * 13) % 97) / 97, it[3] / 100]) : [];
  g.strokeStyle = css.getPropertyValue("--fg");
  g.lineWidth = Math.max(1, dpr);
  g.beginPath();
  const halted = S && S.paused;
  for (let x = 0; x <= w; x += 2 * dpr) {
    const u = x / w;
    let y = halted ? 0 : Math.random() * 0.07;
    for (const [pos, amp] of peaks) {
      const d = (u - pos) * 55;
      y += amp * 0.85 * Math.exp(-d * d) * (halted ? 1 : 0.85 + Math.random() * 0.3);
    }
    const py = h - 3 * dpr - Math.min(1, y) * (h - 8 * dpr);
    x === 0 ? g.moveTo(x, py) : g.lineTo(x, py);
  }
  g.stroke();
}

function scopeFrame() {
  if (document.hidden) return;
  drawScope(expanded ? $("f-scope") : $("m-scope"));
}
let scopeTimer = setInterval(() => { if (!(S && S.paused)) scopeFrame(); }, 200);

// ----------------------------------------------------------- expand/collapse
async function setExpanded(on) {
  expanded = on;
  await invoke("set_mode", { expanded: on });
  document.body.className = (on ? "full" : "mini") + (S && S.paused ? " halted" : "");
  requestAnimationFrame(scopeFrame);
}
$("mini").addEventListener("click", (e) => { if (!e.target.closest("button")) setExpanded(true); });
$("f-collapse").onclick = () => setExpanded(false);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("modal").hidden) closeModal();
  else if (expanded) setExpanded(false);
});

// --------------------------------------------------------------------- halt
function minutesUntilMorning() {
  const d = new Date();
  d.setHours(7, 0, 0, 0);
  if (d <= new Date()) d.setDate(d.getDate() + 1);
  return Math.ceil((d - Date.now()) / 60000);
}
const HALT_OPTIONS = [
  ["1 HOUR", () => 60], ["4 HOURS", () => 240], ["12 HOURS", () => 720],
  ["UNTIL 7 AM", minutesUntilMorning], ["UNTIL I RESUME IT", () => 0],
];
let haltMinutes = 0;

function openHalt() {
  const box = $("halt-choices");
  box.replaceChildren();
  for (const [label, minutes] of HALT_OPTIONS) {
    const b = el("button", "btn danger", label);
    b.onclick = () => {
      haltMinutes = minutes();
      $("halt-summary").textContent = haltMinutes
        ? `Everything stops until ${clock(Date.now() / 1000 + haltMinutes * 60)}.`
        : "Everything stops until you press RESUME.";
      $("halt-step1").hidden = true;
      $("halt-step2").hidden = false;
    };
    box.append(b);
  }
  $("halt-step1").hidden = false;
  $("halt-step2").hidden = true;
  $("modal").hidden = false;
}
function closeModal() { $("modal").hidden = true; }

async function haltOrResume(e) {
  e.stopPropagation();
  if (S && S.paused) { await invoke("resume"); await poll(); scopeFrame(); }
  else openHalt();
}
$("m-halt").onclick = haltOrResume;
$("f-halt").onclick = haltOrResume;
$("halt-confirm").onclick = async () => {
  await invoke("halt", { minutes: haltMinutes });
  closeModal();
  await poll();
  scopeFrame(); // one last still frame
};
for (const b of document.querySelectorAll("[data-close]")) b.onclick = closeModal;
$("modal").addEventListener("click", (e) => { e.stopPropagation(); if (e.target === $("modal")) closeModal(); });

// ------------------------------------------------------------------ station
$("f-sync").onclick = async () => { try { await invoke("sync_now"); } catch (e) { console.error(e); } poll(); };
async function saveRepo() {
  try {
    await invoke("set_repo", { repo: $("cfg-repo").value });
    $("cfg-note").textContent = "FEED SET // CONTACTING...";
    $("cfg-repo").blur();
  } catch (e) {
    $("cfg-note").textContent = String(e).toUpperCase();
  }
  poll();
}
$("f-rescan").onclick = async () => {
  try {
    await invoke("rescan");
  } catch (e) {
    $("cfg-note").textContent = String(e).toUpperCase();
    $("cfg-note").scrollIntoView({ block: "nearest" });
  }
  poll();
};
async function saveToken() {
  try {
    await invoke("set_token", { token: $("cfg-token").value });
    $("cfg-note").textContent = $("cfg-token").value.trim() ? "TOKEN STORED" : "TOKEN FORGOTTEN";
  } catch (e) {
    $("cfg-note").textContent = String(e).toUpperCase();
  }
  $("cfg-token").value = ""; // never keep it in the page
  poll();
}
$("cfg-token-save").onclick = saveToken;
$("cfg-token").addEventListener("keydown", (e) => { if (e.key === "Enter") saveToken(); });
$("cfg-save").onclick = saveRepo;
$("cfg-repo").addEventListener("keydown", (e) => { if (e.key === "Enter") saveRepo(); });
$("cfg-auto").onchange = (e) => invoke("set_autostart", { on: e.target.checked }).catch((err) => {
  $("cfg-note").textContent = String(err).toUpperCase();
  poll();
});
$("cfg-quit").onclick = () => invoke("quit");

document.addEventListener("contextmenu", (e) => e.preventDefault());
renderFeed(); // draw the empty state before the first status arrives
poll();

// ------------------------------------------------- browser-only preview mock
function mockInvoke() {
  const now = () => Math.floor(Date.now() / 1000);
  const st = { paused_until: 0, repo: "you/vothub", autostart: true };
  const titles = [
    "Continuous batching stalls under mixed prompt lengths", "Support speculative decoding with draft models",
    "Implement vectorized hash join from the paper", "Panic in WAL replay after partial write",
    "KV cache transfer over RDMA drops pages under load", "Structured output retries lose tool state",
    "Zero-copy Arrow scan for nested lists", "Async cancellation leaks tasks in scheduler",
    "How do I set the port?", "Typo in README quickstart", "Docs: explain compaction settings",
  ];
  const kinds = ["feature", "perf", "bug", "research", "infra", "refactor", "test", "question", "docs"];
  const pick = [1, 0, 3, 2, 1, 2, 1, 2, 7, 8, 8];
  const feed = {
    v: 1, gen: now() - 2400, scorer: "embed:bge-small-en-v1.5", kinds, efforts: ["S", "M", "L"], lanes: ["agents-memory", "serving-training"], tiers: ["ready", "vetted", "raw"],
    tags: ["inference-serving", "databases", "agents", "runtime", "help wanted"],
    repos: [["demo/fastserve", 9400, 783, "Python", 0, ""], ["demo/oxidb", 3100, 258, "Rust", 1, ""], ["demo/cachemesh", 5200, 91, "C++", 0, ""]],
    issues: titles.map((t, n) => [n % 3, 100 + n, t, Math.max(8, 93 - n * 7 - (n > 7 ? 30 : 0)), 90 - n * 6, pick[n], n < 4 ? 2 : 1,
      n % 4, n === 1 ? [4] : [], Math.floor(now() / 3600) - 20 * (n + 1), n * 2, 22 - n * 2, kinds[pick[n]] + " / 900+ chars", n < 3 ? 1 : 0, n < 2 ? 0 : n < 6 ? 1 : 2]),
    runs: [3, 5, 4, 6, 7, 9, 8, 11].map((v, n) => [Math.floor(now() / 3600) - (7 - n) * 12, 78, 40 + v, v, 2, 90]),
  };
  return async (cmd, args) => {
    if (cmd === "status") {
      const paused = st.paused_until === -1 || st.paused_until > now();
      return { now: now(), repo: st.repo, paused, paused_until: st.paused_until, next_sync: now() + 11400, last_ok: now() - 2400,
        status: paused ? "HALTED BY OPERATOR" : "SIGNAL LOCKED", syncing: false, autostart: st.autostart, gen: feed.gen,
        has_token: !!st.token, rescanning: false };
    }
    if (cmd === "get_feed") return feed;
    if (cmd === "halt") st.paused_until = args.minutes <= 0 ? -1 : now() + args.minutes * 60;
    if (cmd === "resume") st.paused_until = 0;
    if (cmd === "set_token") st.token = args.token.trim();
    if (cmd === "rescan" && !st.token) throw "no token stored // add one under station";
    return null;
  };
}
