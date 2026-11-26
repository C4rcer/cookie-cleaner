// Small helpers shared by the popup and the dashboard.

import { RESTORE_MS, KEEP_ALWAYS, KEEP_SESSION, ORIGINS } from "./config.js";

export const $ = (sel, root = document) => root.querySelector(sel);

/** el("button", { class: "btn", onclick: fn }, "Text") */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k in node && k !== "list") node[k] = v;
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null && c !== false));
  return node;
}

export function send(type, data = {}) {
  return browser.runtime.sendMessage({ type, ...data });
}

export function cookieCount(n) {
  if (!n) return "no cookies";
  return n === 1 ? "1 cookie" : `${n.toLocaleString("en")} cookies`;
}

export function siteCount(n) {
  return n === 1 ? "1 site" : `${n.toLocaleString("en")} sites`;
}

export function ago(at, now) {
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function until(due, now) {
  const s = Math.max(0, Math.ceil((due - now) / 1000));
  if (s < 90) return `in ${s} s`;
  return `in ${Math.round(s / 60)} min`;
}

export function clock(at) {
  return new Date(at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function debounce(fn, ms) {
  let t = 0;
  return () => {
    clearTimeout(t);
    t = setTimeout(fn, ms);
  };
}

export const RESTORE_MINUTES = Math.round(RESTORE_MS / 60000);

export const GONE_FOR_GOOD = `Deleted cookies are kept in memory for ${RESTORE_MINUTES} minutes so a clean can be undone. After that, or once Firefox has been closed, they are gone for good.`;

/**
 * One line of the activity list: what was cleaned, how many cookies, when, and
 * either a Restore button or the plain statement that a restore is no longer
 * possible. Only the site and a number are ever shown.
 */
export function logItem(entry, now, onRestore) {
  const li = el("li", { class: "log-item", dataset: { id: entry.id, kind: entry.kind, site: entry.site } });
  const what = el("div", { class: "log-what" });
  if (entry.kind === "preview") {
    what.append(el("span", { class: "tag" }, "Preview"), el("span", { class: "site" }, entry.site));
    li.append(what, el("div", { class: "log-meta muted" }, `would have been cleaned: ${cookieCount(entry.count)} · ${ago(entry.at, now)}`));
    return li;
  }
  what.append(el("span", { class: "site" }, entry.site));
  const how = entry.kind === "manual" ? "cleaned by you" : entry.kind === "start" ? "cleaned when Firefox started" : "cleaned";
  let meta = `${how}: ${cookieCount(entry.count)} · ${ago(entry.at, now)}`;
  if (entry.left) meta += ` · ${entry.left} could not be deleted`;
  li.append(what, el("div", { class: "log-meta muted" }, meta));
  const side = el("div", { class: "log-side" });
  if (entry.restoredAt) {
    side.append(el("span", { class: "tag ok", dataset: { restore: "done" } }, entry.restored === entry.count ? "Restored" : `Restored ${entry.restored} of ${entry.count}`));
  } else if (entry.restoreUntil > now) {
    const left = Math.max(1, Math.ceil((entry.restoreUntil - now) / 60000));
    side.append(el("button", {
      class: "btn small", type: "button", dataset: { restore: "can" },
      title: `Puts the deleted cookies back. Possible for ${left} more ${left === 1 ? "minute" : "minutes"}.`,
      onclick: () => onRestore(entry),
    }, "Restore"));
  } else {
    side.append(el("span", { class: "muted small-text", dataset: { restore: "gone" }, title: GONE_FOR_GOOD }, "Can no longer be restored"));
  }
  li.append(side);
  return li;
}

export function keepLabel(level) {
  if (level === KEEP_ALWAYS) return "Kept always";
  if (level === KEEP_SESSION) return "Kept until Firefox closes";
  return "Not kept";
}

/** Ask Firefox to give site access back. Must be called from a click. */
export async function requestAccess() {
  let ok = false;
  try {
    ok = await browser.permissions.request({ origins: ORIGINS });
  } catch {
    ok = false;
  }
  await send("access:changed");
  return ok;
}

/** "Deleted 14 cookies from 3 sites." for the result of a clean. */
export function cleanedText(entries, site) {
  const total = entries.reduce((n, e) => n + e.count, 0);
  if (!entries.length) return site ? `${site} had no cookies to delete.` : "There was nothing to delete.";
  if (entries.length === 1) return `Deleted ${cookieCount(total)} for ${entries[0].site}.`;
  return `Deleted ${cookieCount(total)} from ${siteCount(entries.length)}.`;
}

export function restoredText(results) {
  const done = results.filter((r) => r.ok);
  if (!done.length) return "These cookies can no longer be restored.";
  const set = done.reduce((n, r) => n + r.set, 0);
  const of = done.reduce((n, r) => n + r.of, 0);
  const where = done.length === 1 ? `for ${done[0].site}` : `for ${siteCount(done.length)}`;
  const base = set === of ? `Put back ${cookieCount(set)} ${where}.` : `Put back ${set} of ${cookieCount(of)} ${where}; the rest had expired.`;
  return `${base} Reload the page to be signed in again.`;
}
