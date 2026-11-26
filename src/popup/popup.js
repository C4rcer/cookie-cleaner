import { wireSupportLinks, maybeShowMilestone } from "../shared/support.js";
import { graceLabel, KEEP_ALWAYS, KEEP_SESSION } from "../shared/config.js";
import { $, el, send, cookieCount, siteCount, until, debounce, logItem, requestAccess, cleanedText, restoredText } from "../shared/util.js";

const RECENT = 5;
const params = new URLSearchParams(location.search);
// "?tab=<id>" lets the popup be opened in a normal tab against any tab (tests, screenshots).
let tabId = params.has("tab") ? Number(params.get("tab")) : null;
const inTab = params.has("tab");
let state = null;

function openApp(hash = "") {
  browser.tabs.create({ url: browser.runtime.getURL("app/app.html") + hash });
  if (!inTab) window.close();
}

// ------------------------------------------------------------ confirm / notice

let confirmAction = null;

function ask(text, yesLabel, action) {
  $("#notice").hidden = true;
  $("#confirmText").textContent = text;
  $("#confirmYes").textContent = yesLabel;
  confirmAction = action;
  $("#confirm").hidden = false;
}

function closeConfirm() {
  confirmAction = null;
  $("#confirm").hidden = true;
}

function notice(text, actions = []) {
  $("#noticeText").textContent = text;
  $("#noticeActions").replaceChildren(...actions);
  $("#notice").hidden = false;
}

function undoButton(entries) {
  if (!entries.length) return [];
  return [el("button", {
    class: "btn small", type: "button", id: "undo",
    onclick: () => restore(entries.map((e) => e.id)),
  }, "Undo")];
}

async function restore(ids) {
  const res = await send("restore", { ids });
  const done = (res.results || []).filter((r) => r.ok);
  const actions = [];
  if (done.length === 1 && !(state && state.tab && state.tab.site === done[0].site && state.tab.keep)) {
    const site = done[0].site;
    actions.push(el("button", {
      class: "btn small", type: "button", id: "keepRestored",
      onclick: async () => {
        await send("keep:set", { site, level: KEEP_ALWAYS });
        notice(`${site} is on your keep list now.`);
        refresh();
      },
    }, `Keep ${site}`));
  }
  notice(restoredText(res.results || []), actions);
  refresh();
}

// ------------------------------------------------------------ drawing

function drawStatus(s) {
  const box = $("#status");
  const btn = $("#statusBtn");
  btn.className = "btn primary";
  if (!s.access) {
    box.dataset.state = "paused";
    $("#statusTitle").textContent = "Paused: no access to your sites";
    $("#statusText").textContent = "Firefox is not letting Dustpan see cookies, so nothing is cleaned. Site access was switched off in this add-on's permissions.";
    btn.textContent = "Give access back";
    btn.dataset.action = "access";
  } else if (s.settings.enabled) {
    box.dataset.state = "on";
    $("#statusTitle").textContent = "Automatic cleaning is on";
    $("#statusText").textContent = `A site is cleaned ${graceLabel(s.settings.graceSec)} after you close its last tab, unless you keep it.`;
    btn.textContent = "Turn off";
    btn.className = "btn";
    btn.dataset.action = "off";
  } else {
    box.dataset.state = "off";
    $("#statusTitle").textContent = "Automatic cleaning is off";
    $("#statusText").textContent = "Dustpan deletes nothing by itself. It only shows what it would clean.";
    btn.textContent = s.settings.setupDone ? "Turn on" : "Set up automatic cleaning";
    btn.dataset.action = s.settings.setupDone ? "on" : "setup";
  }
}

function drawSite(s) {
  const card = $("#siteCard");
  const tab = s.tab;
  const site = tab && tab.site;
  card.dataset.keep = (tab && tab.keep) || "";
  card.dataset.site = site || "";
  if (!site) {
    $("#siteName").textContent = "This page";
    $("#siteCount").textContent = "";
    $("#siteState").textContent = "This page is not a website, so it has no cookies to clean.";
    $("#siteActions").hidden = true;
    return;
  }
  $("#siteActions").hidden = false;
  $("#siteName").textContent = site;
  $("#siteCount").textContent = s.access ? cookieCount(tab.count) : "";
  const grace = graceLabel(s.settings.graceSec);
  let text;
  if (tab.keep === KEEP_ALWAYS) text = "On your keep list. Dustpan never cleans it.";
  else if (tab.keep === KEEP_SESSION) text = "Kept until Firefox closes. It is cleaned the next time Firefox starts.";
  else if (!s.access) text = "Dustpan can not see this site's cookies right now.";
  else if (s.settings.enabled) text = `Will be cleaned ${grace} after you close its last tab.`;
  else text = `Would be cleaned ${grace} after you close its last tab, if automatic cleaning were on.`;
  $("#siteState").textContent = text;
  $("#keepAlways").hidden = tab.keep === KEEP_ALWAYS;
  $("#keepSession").hidden = tab.keep === KEEP_SESSION;
  $("#unkeep").hidden = !tab.keep;
  const clean = $("#cleanSite");
  clean.hidden = !!tab.keep;
  clean.disabled = !s.access || !tab.count;
  clean.title = tab.count ? "Delete this site's cookies now. You will be asked first." : "This site has no cookies.";
}

function drawPending(s) {
  const list = $("#pendingList");
  $("#pendingBox").hidden = !s.pending.length;
  const anyReal = s.pending.some((p) => !p.preview);
  $("#pendingTitle").textContent = anyReal ? "Waiting to be cleaned" : "Would be cleaned (preview)";
  list.replaceChildren(...s.pending.slice(0, 6).map((p) => el("li", { dataset: { site: p.site, due: String(p.due), preview: p.preview ? "1" : "0" } },
    el("span", { class: "site" }, p.site),
    el("span", { class: "when" }, until(p.due, Date.now())),
    el("button", {
      class: "btn small", type: "button", dataset: { act: "keep" }, title: "Put this site on your keep list",
      onclick: async () => {
        await send("keep:set", { site: p.site, level: KEEP_ALWAYS });
        refresh();
      },
    }, "Keep"),
    p.preview ? null : el("button", {
      class: "btn small", type: "button", dataset: { act: "skip" }, title: "Do not clean it this time",
      onclick: async () => {
        await send("pending:cancel", { site: p.site });
        refresh();
      },
    }, "Not now"),
  )));
}

function drawRecent(s) {
  const now = Date.now();
  const items = s.log.slice(0, RECENT).map((entry) => logItem(entry, now, (e) => restore([e.id])));
  $("#recentList").replaceChildren(...items);
  $("#recentEmpty").hidden = items.length > 0;
}

function drawFooter(s) {
  const btn = $("#cleanAll");
  btn.disabled = !s.access || !s.sweep.sites.length;
  btn.title = s.sweep.sites.length
    ? `${cookieCount(s.sweep.cookies)} from ${siteCount(s.sweep.sites.length)} that are neither open nor kept. You will be asked first.`
    : "Nothing to clean: every site with cookies is open or kept.";
}

function draw(s) {
  state = s;
  drawStatus(s);
  drawSite(s);
  drawPending(s);
  drawRecent(s);
  drawFooter(s);
}

async function refresh() {
  draw(await send("state", { tabId }));
}

function tick() {
  const now = Date.now();
  for (const li of document.querySelectorAll("#pendingList li")) {
    $(".when", li).textContent = until(Number(li.dataset.due), now);
  }
}

// ------------------------------------------------------------ actions

$("#statusBtn").addEventListener("click", async () => {
  const action = $("#statusBtn").dataset.action;
  if (action === "setup") openApp("#setup");
  else if (action === "access") {
    await requestAccess();
    refresh();
  } else {
    const res = await send("enabled:set", { value: action === "on" });
    if (res && res.reason === "setup") openApp("#setup");
    refresh();
  }
});

for (const [id, level] of [["keepAlways", KEEP_ALWAYS], ["keepSession", KEEP_SESSION], ["unkeep", null]]) {
  $("#" + id).addEventListener("click", async () => {
    closeConfirm();
    await send("keep:set", { site: state.tab.site, level });
    refresh();
  });
}

$("#cleanSite").addEventListener("click", () => {
  const { site, count } = state.tab;
  ask(`Delete ${cookieCount(count)} for ${site} now? You will be signed out of it.`, `Delete ${cookieCount(count)}`, async () => {
    const res = await send("clean:site", { site });
    const entries = (res && res.entries) || [];
    notice(res && res.ok ? cleanedText(entries, site) : "Nothing was deleted.", undoButton(entries));
  });
});

$("#cleanAll").addEventListener("click", () => {
  const { sites, cookies, open, kept } = state.sweep;
  const what = `${cookieCount(cookies)} from ${siteCount(sites.length)}`;
  ask(`Delete ${what}? You will be signed out of them. Sites with an open tab (${open}) and sites on your keep list (${kept}) are left alone.`,
    `Delete ${what}`, async () => {
      const res = await send("clean:all", { sites });
      const entries = (res && res.entries) || [];
      notice(res && res.ok ? cleanedText(entries) : "Nothing was deleted.", undoButton(entries));
    });
});

$("#confirmYes").addEventListener("click", async () => {
  const action = confirmAction;
  closeConfirm();
  if (action) await action();
  refresh();
});
$("#confirmNo").addEventListener("click", closeConfirm);

$("#btnOptions").addEventListener("click", () => openApp());
$("#openApp").addEventListener("click", (e) => {
  e.preventDefault();
  openApp();
});

wireSupportLinks();

(async () => {
  if (tabId == null) {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    tabId = tab ? tab.id : null;
  }
  await refresh();
  // Shown once per milestone, only after Dustpan has been of real use.
  maybeShowMilestone($("#supportCard"), state.stats.cookies, [1000, 10000, 50000], (m) =>
    `Dustpan has cleaned up ${m.toLocaleString("en")} cookies for you. It is free and has no ads; if it helps, a coffee keeps it maintained.`);
  const later = debounce(refresh, 150);
  browser.storage.onChanged.addListener((changes, area) => {
    if (area === "local" || "restore" in changes) later();
  });
  setInterval(tick, 500);
  document.body.dataset.ready = "1";
})();
