import { wireSupportLinks } from "../shared/support.js";
import { renderMoreAddons } from "../shared/more-addons.js";
import { GRACE_CHOICES, graceLabel, KEEP_ALWAYS, KEEP_SESSION } from "../shared/config.js";
import {
  $, el, send, cookieCount, siteCount, until, debounce, logItem, requestAccess, cleanedText, restoredText, RESTORE_MINUTES,
} from "../shared/util.js";

const ROWS = 100;
let state = null;
let overview = null;
let filter = "all";
let showAll = false;

// ------------------------------------------------------------ confirm / notice

let confirmAction = null;

function ask(text, yesLabel, action) {
  $("#notice").hidden = true;
  $("#confirmText").textContent = text;
  $("#confirmYes").textContent = yesLabel;
  confirmAction = action;
  $("#confirm").hidden = false;
  $("#confirm").scrollIntoView({ block: "nearest" });
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
  if (done.length === 1) {
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
  $("#notice").scrollIntoView({ block: "nearest" });
  refresh();
}

// ------------------------------------------------------------ status

function drawStatus() {
  const s = state;
  const box = $("#status");
  const btn = $("#statusBtn");
  btn.className = "btn primary";
  $("#rerunSetup").hidden = !s.settings.setupDone || !$("#setup").hidden;
  if (!s.access) {
    box.dataset.state = "paused";
    $("#statusTitle").textContent = "Paused: no access to your sites";
    $("#statusText").textContent = "Firefox is not letting Dustpan see cookies, so nothing is cleaned and the lists below are empty. Site access was switched off in this add-on's permissions (Add-ons and themes, Dustpan, Permissions).";
    btn.textContent = "Give access back";
    btn.dataset.action = "access";
  } else if (s.settings.enabled) {
    box.dataset.state = "on";
    $("#statusTitle").textContent = "Automatic cleaning is on";
    $("#statusText").textContent = `A site is cleaned ${graceLabel(s.settings.graceSec)} after you close its last tab, unless it is on your keep list.`;
    btn.textContent = "Turn off";
    btn.className = "btn";
    btn.dataset.action = "off";
  } else {
    box.dataset.state = "off";
    $("#statusTitle").textContent = "Automatic cleaning is off";
    $("#statusText").textContent = "Dustpan deletes nothing by itself. It only shows what it would clean: look for Preview in the activity list.";
    btn.textContent = s.settings.setupDone ? "Turn on" : "Set up automatic cleaning";
    btn.dataset.action = s.settings.setupDone ? "on" : "setup";
  }
}

// ------------------------------------------------------------ setup

const picks = new Map(); // site -> true / false, only while the setup is open

function openSetup() {
  picks.clear();
  for (const s of overview.sites) if (s.keep) picks.set(s.site, true);
  $("#setup").hidden = false;
  $("#step1").hidden = false;
  $("#step2").hidden = true;
  $("#setupFilter").value = "";
  drawStatus();
  drawSetup();
  $("#setup").scrollIntoView({ block: "start" });
}

function closeSetup() {
  $("#setup").hidden = true;
  if (location.hash === "#setup") history.replaceState(null, "", location.pathname);
  drawStatus();
}

function pickRow(s) {
  const box = el("input", {
    type: "checkbox", checked: !!picks.get(s.site),
    onchange: () => {
      picks.set(s.site, box.checked);
      drawSummary();
    },
  });
  return el("li", { dataset: { site: s.site } }, el("label", {},
    box,
    el("span", { class: "site" }, s.site),
    s.keep === KEEP_SESSION ? el("span", { class: "tag" }, "until Firefox closes") : null,
    el("span", { class: "muted small-text" }, cookieCount(s.count)),
  ));
}

function setupSites() {
  // Sites worth asking about: they have cookies, or a tab, or are kept already.
  return overview.sites.filter((s) => s.count || s.open || s.keep);
}

function drawSetup() {
  if ($("#setup").hidden) return;
  for (const node of document.querySelectorAll("[data-grace]")) node.textContent = graceLabel(state.settings.graceSec);
  const q = $("#setupFilter").value.trim().toLowerCase();
  const all = setupSites().filter((s) => !q || s.site.includes(q));
  const byCount = (a, b) => b.count - a.count || a.site.localeCompare(b.site);
  const open = all.filter((s) => s.open).sort(byCount);
  const other = all.filter((s) => !s.open).sort(byCount);
  $("#setupOpen").replaceChildren(...open.map(pickRow));
  $("#setupOther").replaceChildren(...other.map(pickRow));
  $("#openGroup").hidden = !open.length;
  $("#otherGroup").hidden = !other.length;
  $("#setupNone").hidden = all.length > 0;
  drawSummary();
}

function drawSummary() {
  const all = setupSites();
  const kept = all.filter((s) => picks.get(s.site)).length;
  const rest = all.length - kept;
  let text;
  if (!kept) text = "You are keeping no sites. Every site will be signed out after you close it.";
  else if (!rest) text = `You are keeping ${siteCount(kept)}. Sites you visit later will be signed out after you close them.`;
  else text = `You are keeping ${siteCount(kept)}. The other ${siteCount(rest)}, and sites you visit later, will be signed out after you close them.`;
  $("#setupSummary").textContent = text;
  $("#setupFinish").textContent = kept ? `Turn on automatic cleaning, keeping ${siteCount(kept)}` : "Turn on automatic cleaning, keeping no sites";
}

async function finishSetup() {
  const patch = {};
  for (const s of setupSites()) {
    if (picks.get(s.site)) patch[s.site] = s.keep || KEEP_ALWAYS;
    else if (s.keep) patch[s.site] = null;
  }
  await send("setup:finish", { keep: patch });
  closeSetup();
  await refresh();
  $("#status").scrollIntoView({ block: "start" });
}

// ------------------------------------------------------------ sites

function matches(s) {
  if (filter === "kept") return !!s.keep;
  if (filter === "open") return s.open;
  if (filter === "clean") return !s.keep && !s.open && s.count > 0;
  return true;
}

function siteRow(s, now) {
  const select = el("select", {
    "aria-label": `Keep ${s.site}`,
    onchange: async () => {
      await send("keep:set", { site: s.site, level: select.value || null });
      refresh();
    },
  },
  el("option", { value: "" }, "Not kept"),
  el("option", { value: KEEP_ALWAYS }, "Keep always"),
  el("option", { value: KEEP_SESSION }, "Keep until Firefox closes"));
  select.value = s.keep || "";
  let status;
  if (s.open) status = el("span", { class: "tag ok" }, "Open");
  else if (s.due) status = el("span", { class: "tag warn", dataset: { due: String(s.due) } }, `${state.settings.enabled ? "Cleaning" : "Preview"} ${until(s.due, now)}`);
  else status = el("span", { class: "muted" }, "Not open");
  const canClean = !s.keep && s.count > 0 && state.access;
  return el("tr", { dataset: { site: s.site, keep: s.keep || "", open: s.open ? "1" : "0" } },
    el("td", { class: "site" }, s.site),
    el("td", { class: "num" }, s.count ? s.count.toLocaleString("en") : "0"),
    el("td", {}, status),
    el("td", {}, select),
    el("td", {}, canClean ? el("button", {
      class: "btn small danger", type: "button", dataset: { act: "clean" },
      onclick: () => ask(
        `Delete ${cookieCount(s.count)} for ${s.site} now? You will be signed out of it.${s.open ? " It is open in a tab right now." : ""}`,
        `Delete ${cookieCount(s.count)}`,
        async () => {
          const res = await send("clean:site", { site: s.site });
          const entries = (res && res.entries) || [];
          notice(res && res.ok ? cleanedText(entries, s.site) : "Nothing was deleted.", undoButton(entries));
        }),
    }, "Clean now") : null));
}

function drawSites() {
  const now = Date.now();
  const q = $("#siteFilter").value.trim().toLowerCase();
  const rows = overview.sites
    .filter((s) => matches(s) && (!q || s.site.includes(q)))
    .sort((a, b) => Number(b.open) - Number(a.open) || b.count - a.count || a.site.localeCompare(b.site));
  const shown = showAll ? rows : rows.slice(0, ROWS);
  $("#siteTable tbody").replaceChildren(...shown.map((s) => siteRow(s, now)));
  $("#siteTable").hidden = !rows.length;
  $("#sitesEmpty").hidden = rows.length > 0;
  $("#showAll").hidden = showAll || rows.length <= ROWS;
  $("#showAll").textContent = `Show all ${rows.length} sites`;
  for (const chip of document.querySelectorAll(".chip")) chip.setAttribute("aria-pressed", String(chip.dataset.filter === filter));
  const btn = $("#cleanAll");
  btn.disabled = !state.access || !state.sweep.sites.length;
  btn.title = state.sweep.sites.length
    ? `${cookieCount(state.sweep.cookies)} from ${siteCount(state.sweep.sites.length)} that are neither open nor kept. You will be asked first.`
    : "Nothing to clean: every site with cookies is open or kept.";
}

// ------------------------------------------------------------ activity / settings

function drawLog() {
  const now = Date.now();
  const items = state.log.map((entry) => logItem(entry, now, (e) => restore([e.id])));
  $("#logList").replaceChildren(...items);
  $("#logEmpty").hidden = items.length > 0;
  $("#clearLog").hidden = !items.length;
}

function drawSettings() {
  const s = state.settings;
  const grace = $("#grace");
  const choices = GRACE_CHOICES.includes(s.graceSec) ? GRACE_CHOICES : [...GRACE_CHOICES, s.graceSec].sort((a, b) => a - b);
  if (document.activeElement !== grace) {
    grace.replaceChildren(...choices.map((sec) => el("option", { value: String(sec) }, graceLabel(sec))));
    grace.value = String(s.graceSec);
  }
  $("#onNavigate").checked = s.onNavigate;
  $("#cleanOpenAtQuit").checked = s.cleanOpenAtQuit;
}

// ------------------------------------------------------------ refresh

async function refresh() {
  [state, overview] = await Promise.all([send("state", { tabId: null }), send("overview")]);
  drawStatus();
  drawSetup();
  drawSites();
  drawLog();
  drawSettings();
}

function tick() {
  const now = Date.now();
  for (const node of document.querySelectorAll("#siteTable [data-due]")) {
    node.textContent = `${state.settings.enabled ? "Cleaning" : "Preview"} ${until(Number(node.dataset.due), now)}`;
  }
}

// ------------------------------------------------------------ wiring

$("#statusBtn").addEventListener("click", async () => {
  const action = $("#statusBtn").dataset.action;
  if (action === "setup") openSetup();
  else if (action === "access") {
    await requestAccess();
    refresh();
  } else {
    const res = await send("enabled:set", { value: action === "on" });
    if (res && res.reason === "setup") openSetup();
    refresh();
  }
});
$("#rerunSetup").addEventListener("click", openSetup);
$("#toStep2").addEventListener("click", () => {
  $("#step1").hidden = true;
  $("#step2").hidden = false;
  drawSetup();
});
$("#setupBack").addEventListener("click", () => {
  $("#step1").hidden = false;
  $("#step2").hidden = true;
});
$("#setupCancel").addEventListener("click", closeSetup);
$("#setupFinish").addEventListener("click", finishSetup);
$("#setupFilter").addEventListener("input", drawSetup);

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

$("#addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#addInput");
  const res = await send("keep:add", { input: input.value, level: $("#addLevel").value });
  if (res && res.ok) {
    $("#addMsg").textContent = `${res.site} is on your keep list.`;
    input.value = "";
  } else {
    $("#addMsg").textContent = "That is not a site address. Try something like example.com.";
  }
  refresh();
});

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    filter = chip.dataset.filter;
    showAll = false;
    drawSites();
  });
}
$("#siteFilter").addEventListener("input", drawSites);
$("#showAll").addEventListener("click", () => {
  showAll = true;
  drawSites();
});

$("#clearLog").addEventListener("click", async () => {
  await send("log:clear");
  refresh();
});

$("#grace").addEventListener("change", async () => {
  await send("settings:set", { patch: { graceSec: Number($("#grace").value) } });
  refresh();
});
for (const key of ["onNavigate", "cleanOpenAtQuit"]) {
  $("#" + key).addEventListener("change", async () => {
    await send("settings:set", { patch: { [key]: $("#" + key).checked } });
    refresh();
  });
}

window.addEventListener("hashchange", () => {
  if (location.hash === "#setup" && $("#setup").hidden && overview) openSetup();
});

for (const node of document.querySelectorAll("[data-restore-min]")) node.textContent = String(RESTORE_MINUTES);
wireSupportLinks();
renderMoreAddons(document.getElementById("moreAddons")).catch(() => {});

(async () => {
  await refresh();
  if (location.hash === "#setup") openSetup();
  const later = debounce(refresh, 200);
  browser.storage.onChanged.addListener((changes, area) => {
    if (area === "local" || "restore" in changes) later();
  });
  setInterval(tick, 500);
  document.body.dataset.ready = "1";
})();
