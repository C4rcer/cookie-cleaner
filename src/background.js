// Dustpan background: a non-persistent event page.
//
// Firefox stops this page after about 30 seconds without work and starts it
// again for a tab event, an alarm or a message, so nothing is kept in
// variables. What must survive lives in storage:
//
//   storage.local   settings, keep, pending, open, prevOpen, stores, log, stats
//   storage.session boot, visited, restore   (memory only, gone when Firefox closes)
//
// The rules, in the order they are checked before anything is deleted:
//   1. Dustpan must still have access to the sites' cookies.
//   2. The site must not be open in any tab, window or container.
//   3. The site must not be on the keep list.
//   4. Automatic cleaning must be switched on (otherwise it is only a preview).
// A "site" is the registrable domain (see shared/psl.js).

import { loadPsl, siteOfHost, siteOfUrl, siteOfInput } from "./shared/psl.js";
import {
  ORIGINS, DEFAULTS, GRACE_MIN, GRACE_MAX, STARTUP_DELAY_MS, RESTORE_MS, RESTORE_MAX_BYTES,
  RESTORE_MAX_ENTRIES, LOG_MAX, STORES_MAX, VISITED_MAX, KEEP_ALWAYS, KEEP_SESSION,
} from "./shared/config.js";

const ALARM_SWEEP = "sweep";
const ALARM_PURGE = "purge";
const DEFAULT_STORE = "firefox-default";
const EVERY_COOKIE = { firstPartyDomain: null, partitionKey: {} };
const BADGE_KEPT = "#0f766e";
const BADGE_PROBLEM = "#b91c1c";

const local = browser.storage.local;
const session = browser.storage.session;

// Tabs closed while this page is alive. tabs.query can still list a tab inside
// its own onRemoved event, and a closing tab must never count as open.
const closedTabs = new Set();

// One thing at a time: every event and message is handled after the previous
// one has finished, so two of them can not overwrite each other's writes.
let chain = Promise.resolve();
function queue(fn) {
  const run = chain.then(fn);
  chain = run.catch((e) => console.error("Dustpan:", e));
  return run;
}

function withDefaults(settings) {
  return { ...DEFAULTS, ...(settings || {}) };
}

function graceMs(settings) {
  const sec = Math.round(Number(settings.graceSec));
  return (Number.isFinite(sec) ? Math.min(GRACE_MAX, Math.max(GRACE_MIN, sec)) : DEFAULTS.graceSec) * 1000;
}

function newId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

async function hasAccess() {
  try {
    return await browser.permissions.contains({ origins: ORIGINS });
  } catch {
    return false;
  }
}

async function liveTabs() {
  const tabs = await browser.tabs.query({});
  return tabs.filter((t) => !closedTabs.has(t.id));
}

// ------------------------------------------------------------------ start

let booted = false;

/**
 * Runs before anything else in every event. The first time after Firefox
 * started (or after the add-on was installed, updated or switched on again)
 * storage.session is empty: the list of open sites is rebuilt from the tabs,
 * and whatever was still waiting to be cleaned is pushed back by a minute.
 */
async function boot() {
  if (booted) return;
  await loadPsl();
  const mark = await session.get("boot");
  if (!mark.boot) {
    const got = await local.get(["open", "pending"]);
    const tabs = await liveTabs();
    const visited = {};
    const current = new Set();
    for (const tab of tabs) {
      const site = siteOfUrl(tab.url);
      if (!site) continue;
      current.add(site);
      visited[String(tab.id)] = [site];
    }
    const pending = got.pending || {};
    const hold = Date.now() + STARTUP_DELAY_MS;
    for (const site of Object.keys(pending)) {
      if (current.has(site)) delete pending[site];
      else if (pending[site].due < hold) pending[site].due = hold;
    }
    await local.set({ prevOpen: got.open || [], open: [...current].sort(), pending });
    await session.set({ boot: Date.now(), visited });
    await schedule(pending);
  }
  booted = true;
}

// ------------------------------------------------------------ open sites

/**
 * Which sites are in use right now. By default a tab holds on to every site
 * it has shown since it was opened, so going back in the tab or a sign-in that
 * bounces through another site never loses its cookies. With "onNavigate" only
 * the page a tab shows now counts.
 */
function track(tabs, visited, settings, stores) {
  const openIds = new Set();
  const current = new Set();
  let visitedChanged = false;
  let storesChanged = false;
  for (const tab of tabs) {
    const id = String(tab.id);
    openIds.add(id);
    const store = tab.cookieStoreId;
    if (store && store !== DEFAULT_STORE && !tab.incognito && !stores.includes(store)) {
      stores.push(store);
      storesChanged = true;
    }
    const site = siteOfUrl(tab.url);
    if (!site) continue;
    current.add(site);
    const list = visited[id] || (visited[id] = []);
    if (!list.includes(site)) {
      list.push(site);
      if (list.length > VISITED_MAX) list.shift();
      visitedChanged = true;
    }
  }
  for (const id of Object.keys(visited)) {
    if (!openIds.has(id)) {
      delete visited[id];
      visitedChanged = true;
    }
  }
  const inUse = new Set(current);
  if (!settings.onNavigate) {
    for (const list of Object.values(visited)) for (const site of list) inUse.add(site);
  }
  if (stores.length > STORES_MAX) stores.splice(0, stores.length - STORES_MAX);
  return { inUse, current, visitedChanged, storesChanged };
}

/**
 * Compare the sites in use now with the list saved last time. A site that
 * dropped out starts its wait; a site that is back in use stops waiting.
 * "reason" says why sites dropped out: "closed" (a tab was closed or moved on)
 * or "window" (a whole window closed, which is also what quitting Firefox
 * looks like).
 */
async function recompute(reason = "closed") {
  await boot();
  const [tabs, sess, got, access] = await Promise.all([
    liveTabs(),
    session.get("visited"),
    local.get(["settings", "keep", "pending", "open", "stores"]),
    hasAccess(),
  ]);
  const settings = withDefaults(got.settings);
  const keep = got.keep || {};
  const pending = got.pending || {};
  const visited = sess.visited || {};
  const stores = got.stores || [];
  const { inUse, current, visitedChanged, storesChanged } = track(tabs, visited, settings, stores);
  const old = got.open || [];
  const now = Date.now();
  let pendingChanged = false;
  for (const site of old) {
    if (inUse.has(site) || keep[site] || !access) continue;
    pending[site] = { due: now + graceMs(settings), preview: !settings.enabled, reason };
    pendingChanged = true;
  }
  for (const site of Object.keys(pending)) {
    if (inUse.has(site) || !access) {
      delete pending[site];
      pendingChanged = true;
    }
  }
  const writes = {};
  if (old.length !== inUse.size || old.some((s) => !inUse.has(s))) writes.open = [...inUse].sort();
  if (pendingChanged) writes.pending = pending;
  if (storesChanged) writes.stores = stores;
  if (Object.keys(writes).length) await local.set(writes);
  if (visitedChanged) await session.set({ visited });
  if (pendingChanged) await schedule(pending);
  return { tabs, inUse, current, settings, keep, pending, access };
}

async function schedule(pending) {
  const dues = Object.values(pending).map((p) => p.due);
  if (!dues.length) {
    await browser.alarms.clear(ALARM_SWEEP);
    return;
  }
  browser.alarms.create(ALARM_SWEEP, { when: Math.max(Date.now() + 50, Math.min(...dues)) });
}

// ---------------------------------------------------------------- cookies

async function storeIds() {
  const got = await local.get("stores");
  return [DEFAULT_STORE, ...(got.stores || []).filter((s) => s !== DEFAULT_STORE)];
}

/**
 * The site a cookie belongs to. A cookie that Firefox keeps apart per visited
 * site belongs to that visited site: with first-party isolation that is
 * firstPartyDomain, with Total Cookie Protection it is the partition key.
 * Every other cookie belongs to the site of its own domain.
 */
function ownerSite(c) {
  if (c.firstPartyDomain) return siteOfHost(c.firstPartyDomain);
  const top = c.partitionKey && c.partitionKey.topLevelSite;
  if (top) {
    try {
      const site = siteOfHost(new URL(top).hostname);
      if (site) return site;
    } catch {
      // not an address: fall back to the cookie's own domain
    }
  }
  return siteOfHost(c.domain);
}

/** Every cookie Dustpan can see, in every known cookie store, grouped by site. */
async function cookiesBySite() {
  const map = new Map();
  for (const storeId of await storeIds()) {
    let all = [];
    try {
      all = await browser.cookies.getAll({ storeId, ...EVERY_COOKIE });
    } catch {
      continue; // a store that is gone or may not be read is left alone
    }
    for (const c of all) {
      const site = ownerSite(c);
      if (!site) continue;
      if (!map.has(site)) map.set(site, []);
      map.get(site).push(c);
    }
  }
  return map;
}

function cookieUrl(c) {
  let host = c.domain.startsWith(".") ? c.domain.slice(1) : c.domain;
  if (host.includes(":") && !host.startsWith("[")) host = `[${host}]`;
  return `${c.secure ? "https" : "http"}://${host}${c.path || "/"}`;
}

function removeDetails(c) {
  const d = { url: cookieUrl(c), name: c.name, storeId: c.storeId, firstPartyDomain: c.firstPartyDomain || "" };
  if (c.partitionKey) d.partitionKey = c.partitionKey;
  return d;
}

function setDetails(c) {
  const d = {
    url: cookieUrl(c), name: c.name, value: c.value, path: c.path, secure: c.secure, httpOnly: c.httpOnly,
    sameSite: c.sameSite, storeId: c.storeId, firstPartyDomain: c.firstPartyDomain || "",
  };
  if (!c.hostOnly) d.domain = c.domain;
  if (!c.session && c.expirationDate) d.expirationDate = c.expirationDate;
  if (c.partitionKey) d.partitionKey = c.partitionKey;
  return d;
}

/**
 * Delete the cookies of the given sites. The caller has already checked that
 * each of them may be cleaned. Returns the new log entries.
 */
async function cleanSites(list) {
  if (!list.length) return [];
  const map = await cookiesBySite();
  const at = Date.now();
  const entries = [];
  const buffers = [];
  let total = 0;
  for (const { site, kind } of list) {
    const cookies = map.get(site) || [];
    const removed = [];
    for (const c of cookies) {
      try {
        if (await browser.cookies.remove(removeDetails(c))) removed.push(c);
      } catch {
        // counted as not deleted
      }
    }
    if (!removed.length) continue;
    const id = newId();
    const entry = { id, at, kind, site, count: removed.length };
    if (removed.length < cookies.length) entry.left = cookies.length - removed.length;
    entries.push(entry);
    buffers.push({ id, at, site, cookies: removed });
    total += removed.length;
  }
  if (entries.length) {
    await saveRestore(buffers);
    await appendLog(entries);
    const got = await local.get("stats");
    const stats = got.stats || { cookies: 0 };
    stats.cookies += total;
    await local.set({ stats });
  }
  return entries;
}

/** The log holds the site and a number. Never a cookie's name or value. */
async function appendLog(entries) {
  const got = await local.get("log");
  const log = (got.log || []).concat(entries);
  await local.set({ log: log.slice(-LOG_MAX) });
}

// ---------------------------------------------------------------- restore

/**
 * Deleted cookies wait in storage.session for a restore: memory only, never
 * written to disk, dropped after RESTORE_MS, oldest first when they take up
 * too much room.
 */
async function saveRestore(add) {
  const got = await session.get("restore");
  const now = Date.now();
  const list = (got.restore || []).filter((e) => e.at > now - RESTORE_MS);
  for (const e of add) {
    e.bytes = JSON.stringify(e.cookies).length;
    list.push(e);
  }
  let bytes = list.reduce((n, e) => n + e.bytes, 0);
  while (list.length && (bytes > RESTORE_MAX_BYTES || list.length > RESTORE_MAX_ENTRIES)) bytes -= list.shift().bytes;
  try {
    await session.set({ restore: list });
  } catch {
    await session.set({ restore: [] }).catch(() => {});
  }
  schedulePurge(list);
}

function schedulePurge(list) {
  if (!list.length) {
    browser.alarms.clear(ALARM_PURGE);
    return;
  }
  browser.alarms.create(ALARM_PURGE, { when: Math.min(...list.map((e) => e.at)) + RESTORE_MS + 1000 });
}

async function purgeRestore() {
  const got = await session.get("restore");
  const now = Date.now();
  const list = (got.restore || []).filter((e) => e.at > now - RESTORE_MS);
  await session.set({ restore: list });
  schedulePurge(list);
}

async function restoreEntries(ids) {
  await boot();
  const now = Date.now();
  const sess = await session.get("restore");
  const list = sess.restore || [];
  const got = await local.get(["pending", "log"]);
  const pending = got.pending || {};
  const log = got.log || [];
  const results = [];
  for (const id of ids) {
    const i = list.findIndex((e) => e.id === id);
    const e = i >= 0 ? list[i] : null;
    if (!e || e.at <= now - RESTORE_MS) {
      results.push({ id, ok: false });
      continue;
    }
    let set = 0;
    for (const c of e.cookies) {
      try {
        if (await browser.cookies.set(setDetails(c))) set++;
      } catch {
        // an expired or refused cookie is not counted
      }
    }
    list.splice(i, 1);
    delete pending[e.site]; // a restored site is not cleaned again behind the user's back
    const entry = log.find((l) => l.id === id);
    if (entry) {
      entry.restored = set;
      entry.restoredAt = now;
    }
    results.push({ id, ok: true, site: e.site, set, of: e.cookies.length });
  }
  await session.set({ restore: list });
  await local.set({ pending, log });
  await schedule(pending);
  schedulePurge(list);
  return results;
}

// ------------------------------------------------------- the waiting list

async function runDue() {
  const r = await recompute();
  const { pending, keep, settings, inUse, access } = r;
  const now = Date.now();
  const due = Object.entries(pending).filter(([, p]) => p.due <= now + 300);
  if (!due.length) {
    await schedule(pending);
    return;
  }
  // Firefox is asking whether to bring back the last session: those tabs are
  // not open yet, so nothing is cleaned until the question is answered.
  if (r.tabs.some((t) => /^about:(sessionrestore|welcomeback)/.test(t.url || ""))) {
    for (const [, p] of due) p.due = now + STARTUP_DELAY_MS;
    await local.set({ pending });
    await schedule(pending);
    return;
  }
  const clean = [];
  const preview = [];
  for (const [site, p] of due) {
    delete pending[site];
    if (!access || inUse.has(site)) continue;
    const level = keep[site];
    // "Keep until Firefox closes" ends at the next start, and only there.
    if (level === KEEP_ALWAYS || (level === KEEP_SESSION && p.reason !== "session")) continue;
    if (p.preview) preview.push(site);
    else if (settings.enabled) clean.push({ site, kind: p.reason === "session" || p.reason === "quit" ? "start" : "auto" });
  }
  await cleanSites(clean);
  if (preview.length) {
    const map = await cookiesBySite();
    const entries = preview
      .map((site) => ({ id: newId(), at: now, kind: "preview", site, count: (map.get(site) || []).length }))
      .filter((e) => e.count > 0);
    if (entries.length) await appendLog(entries);
  }
  await local.set({ pending });
  await schedule(pending);
}

/** Firefox has just started: the end of "keep until Firefox closes", and of the tabs that were open at the end. */
async function onBrowserStart() {
  await boot();
  const got = await local.get(["settings", "keep", "prevOpen", "pending", "open"]);
  const settings = withDefaults(got.settings);
  const keep = got.keep || {};
  const pending = got.pending || {};
  const open = new Set(got.open || []);
  const due = Date.now() + STARTUP_DELAY_MS;
  const preview = !settings.enabled;
  // Tabs that went away with their window may simply have been open when
  // Firefox quit. Unless the user asked for those to be cleaned, forget them.
  if (!settings.cleanOpenAtQuit) {
    for (const site of Object.keys(pending)) if (pending[site].reason === "window") delete pending[site];
  }
  for (const [site, level] of Object.entries(keep)) {
    if (level === KEEP_SESSION && !open.has(site)) pending[site] = { due, preview, reason: "session" };
  }
  if (settings.cleanOpenAtQuit) {
    for (const site of got.prevOpen || []) {
      if (!open.has(site) && !keep[site] && !pending[site]) pending[site] = { due, preview, reason: "quit" };
    }
  }
  await local.set({ pending });
  await local.remove("prevOpen");
  await schedule(pending);
}

// ------------------------------------------------------- toolbar button

function paintTab(tab, keep) {
  const site = siteOfUrl(tab.url);
  const level = site ? keep[site] : null;
  const tabId = tab.id;
  const quiet = () => {};
  browser.action.setBadgeText({ tabId, text: level ? "✓" : null }).catch(quiet);
  if (level) browser.action.setBadgeBackgroundColor({ tabId, color: BADGE_KEPT }).catch(quiet);
  const title = !level ? null
    : level === KEEP_ALWAYS ? `Dustpan: ${site} is kept`
      : `Dustpan: ${site} is kept until Firefox closes`;
  browser.action.setTitle({ tabId, title }).catch(quiet);
}

async function paintAll(r) {
  await browser.action.setBadgeText({ text: r.access ? "" : "!" });
  await browser.action.setBadgeBackgroundColor({ color: r.access ? BADGE_KEPT : BADGE_PROBLEM });
  await browser.action.setTitle({ title: r.access ? null : "Dustpan: paused, it has no access to your sites" });
  for (const tab of r.tabs) paintTab(tab, r.keep);
}

// ---------------------------------------------------------------- what the pages ask for

async function buildState(tabId) {
  const r = await recompute();
  const map = r.access ? await cookiesBySite() : new Map();
  const now = Date.now();
  const sess = await session.get("restore");
  const until = new Map((sess.restore || []).filter((e) => e.at > now - RESTORE_MS).map((e) => [e.id, e.at + RESTORE_MS]));
  const got = await local.get(["log", "stats"]);
  const log = (got.log || []).map((l) => ({ ...l, restoreUntil: until.get(l.id) || 0 })).reverse();
  let tab = null;
  if (tabId != null) {
    const t = r.tabs.find((x) => x.id === tabId);
    if (t) {
      const site = siteOfUrl(t.url);
      tab = { id: t.id, site, count: site ? (map.get(site) || []).length : 0, keep: site ? r.keep[site] || null : null };
    }
  }
  const sweep = { sites: [], cookies: 0, kept: 0, open: 0 };
  for (const [site, list] of map) {
    if (r.keep[site]) sweep.kept++;
    else if (r.inUse.has(site)) sweep.open++;
    else {
      sweep.sites.push(site);
      sweep.cookies += list.length;
    }
  }
  sweep.sites.sort();
  const pending = Object.entries(r.pending).map(([site, p]) => ({ site, ...p })).sort((a, b) => a.due - b.due);
  return { now, settings: r.settings, access: r.access, tab, pending, log, sweep, stats: got.stats || { cookies: 0 } };
}

async function buildOverview() {
  const r = await recompute();
  const map = r.access ? await cookiesBySite() : new Map();
  const names = new Set([...map.keys(), ...Object.keys(r.keep), ...r.inUse]);
  const sites = [...names].sort().map((site) => ({
    site,
    count: (map.get(site) || []).length,
    keep: r.keep[site] || null,
    open: r.inUse.has(site),
    due: r.pending[site] ? r.pending[site].due : 0,
  }));
  return { now: Date.now(), settings: r.settings, access: r.access, sites };
}

async function setKeep(patch) {
  const r = await recompute();
  const keep = r.keep;
  const pending = r.pending;
  for (const [name, level] of Object.entries(patch)) {
    const site = siteOfHost(name);
    if (!site) continue;
    if (level === KEEP_ALWAYS || level === KEEP_SESSION) {
      keep[site] = level;
      delete pending[site];
    } else {
      delete keep[site];
    }
  }
  await local.set({ keep, pending });
  await schedule(pending);
  await paintAll({ ...r, keep });
}

async function setEnabled(value) {
  const got = await local.get("settings");
  const settings = withDefaults(got.settings);
  if (value && !settings.setupDone) return { ok: false, reason: "setup" };
  settings.enabled = !!value;
  // Whatever was waiting was scheduled under the old mode: start clean.
  await local.set({ settings, pending: {} });
  await schedule({});
  return { ok: true };
}

async function handle(msg) {
  switch (msg && msg.type) {
    case "state":
      return buildState(msg.tabId);
    case "overview":
      return buildOverview();
    case "keep:set": {
      await setKeep({ [msg.site]: msg.level });
      return { ok: true };
    }
    case "keep:add": {
      await boot();
      const site = siteOfInput(msg.input);
      if (!site) return { ok: false };
      await setKeep({ [site]: msg.level === KEEP_SESSION ? KEEP_SESSION : KEEP_ALWAYS });
      return { ok: true, site };
    }
    case "settings:set": {
      const got = await local.get("settings");
      const settings = withDefaults(got.settings);
      const p = msg.patch || {};
      if ("graceSec" in p) {
        const sec = Math.round(Number(p.graceSec));
        if (Number.isFinite(sec)) settings.graceSec = Math.min(GRACE_MAX, Math.max(GRACE_MIN, sec));
      }
      if ("onNavigate" in p) settings.onNavigate = !!p.onNavigate;
      if ("cleanOpenAtQuit" in p) settings.cleanOpenAtQuit = !!p.cleanOpenAtQuit;
      await local.set({ settings });
      await recompute();
      return { ok: true, settings };
    }
    case "setup:finish": {
      await setKeep(msg.keep || {});
      const got = await local.get("settings");
      const settings = withDefaults(got.settings);
      settings.setupDone = true;
      await local.set({ settings });
      return setEnabled(true);
    }
    case "enabled:set":
      return setEnabled(msg.value);
    case "clean:site": {
      const r = await recompute();
      const site = siteOfHost(msg.site);
      if (!r.access) return { ok: false, reason: "access" };
      if (!site || r.keep[site]) return { ok: false, reason: "kept" };
      const entries = await cleanSites([{ site, kind: "manual" }]);
      delete r.pending[site];
      await local.set({ pending: r.pending });
      await schedule(r.pending);
      return { ok: true, entries };
    }
    case "clean:all": {
      const r = await recompute();
      if (!r.access) return { ok: false, reason: "access" };
      // Only what the user confirmed, and of that only what is still neither open nor kept.
      const list = (msg.sites || []).map((s) => siteOfHost(s)).filter((s) => s && !r.keep[s] && !r.inUse.has(s));
      const entries = await cleanSites(list.map((site) => ({ site, kind: "manual" })));
      for (const site of list) delete r.pending[site];
      await local.set({ pending: r.pending });
      await schedule(r.pending);
      return { ok: true, entries };
    }
    case "pending:cancel": {
      const got = await local.get("pending");
      const pending = got.pending || {};
      delete pending[msg.site];
      await local.set({ pending });
      await schedule(pending);
      return { ok: true };
    }
    case "restore":
      return { ok: true, results: await restoreEntries(msg.ids || []) };
    case "log:clear":
      await local.set({ log: [] });
      return { ok: true };
    case "access:changed": {
      const r = await recompute();
      await paintAll(r);
      return { ok: true, access: r.access };
    }
    default:
      return { ok: false, reason: "unknown" };
  }
}

// ---------------------------------------------------------------- events
// All listeners are added right here, before anything is awaited: an event
// that wakes this page must find its listener in place.

function tabsChanged(tab, reason) {
  queue(async () => {
    const r = await recompute(reason);
    if (tab && tab.id != null) {
      const live = r.tabs.find((t) => t.id === tab.id);
      if (live) paintTab(live, r.keep);
    }
  });
}

browser.tabs.onCreated.addListener((tab) => tabsChanged(tab));
browser.tabs.onUpdated.addListener((tabId) => tabsChanged({ id: tabId }), { properties: ["url"] });
browser.tabs.onRemoved.addListener((tabId, info) => {
  closedTabs.add(tabId);
  tabsChanged(null, info && info.isWindowClosing ? "window" : "closed");
});
browser.tabs.onReplaced.addListener((addedId, removedId) => {
  closedTabs.add(removedId);
  queue(async () => {
    // The new tab takes over what the old one had visited.
    const sess = await session.get("visited");
    const visited = sess.visited || {};
    if (visited[String(removedId)]) {
      visited[String(addedId)] = [...new Set([...(visited[String(addedId)] || []), ...visited[String(removedId)]])];
      delete visited[String(removedId)];
      await session.set({ visited });
    }
    await recompute();
  });
});

browser.alarms.onAlarm.addListener((alarm) => {
  queue(async () => {
    await boot();
    if (alarm.name === ALARM_SWEEP) await runDue();
    else if (alarm.name === ALARM_PURGE) await purgeRestore();
  });
});

browser.runtime.onStartup.addListener(() => {
  queue(async () => {
    await onBrowserStart();
    await paintAll(await recompute());
  });
});

browser.runtime.onInstalled.addListener(() => {
  queue(async () => paintAll(await recompute()));
});

function accessChanged() {
  queue(async () => paintAll(await recompute()));
}
browser.permissions.onAdded.addListener(accessChanged);
browser.permissions.onRemoved.addListener(accessChanged);

browser.runtime.onMessage.addListener((msg) => queue(() => handle(msg)));
