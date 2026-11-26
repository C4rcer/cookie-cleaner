// Which "site" does a host name belong to?
//
// A site is the registrable domain: the public suffix plus one label, so
// mail.example.com and accounts.example.com are both example.com, while
// shop.example.co.uk is example.co.uk and alice.github.io stays apart from
// bob.github.io. The public suffixes come from the Public Suffix List, shipped
// unmodified in vendor/public_suffix_list.dat (see the README for its source,
// date and license). Both of its sections are used, ICANN and private, the same
// as Firefox does when it decides which host may set a cookie for which domain.

let rules = null;

function isAscii(s) {
  for (let i = 0; i < s.length; i++) if (s.charCodeAt(i) > 127) return false;
  return true;
}

// The list is written in Unicode; cookies and tab addresses use the ASCII
// (punycode) form. URL does the conversion.
function toAscii(name) {
  if (isAscii(name)) return name;
  try {
    return new URL("http://" + name).hostname;
  } catch {
    return name;
  }
}

export function parsePsl(text) {
  const exact = new Set();
  const wildcard = new Set();   // "*.ck" is stored as "ck"
  const exception = new Set();  // "!www.ck" is stored as "www.ck"
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("//")) continue;
    let rule = line.split(/\s/)[0].toLowerCase();
    let into = exact;
    if (rule.startsWith("!")) {
      into = exception;
      rule = rule.slice(1);
    } else if (rule.startsWith("*.")) {
      into = wildcard;
      rule = rule.slice(2);
    }
    if (rule) into.add(toAscii(rule));
  }
  return { exact, wildcard, exception };
}

export async function loadPsl() {
  if (!rules) {
    const res = await fetch(browser.runtime.getURL("vendor/public_suffix_list.dat"));
    rules = parsePsl(await res.text());
  }
  return rules;
}

/** For tests of the parser alone. */
export function setPsl(parsed) {
  rules = parsed;
}

export function normalizeHost(host) {
  let h = String(host || "").trim().toLowerCase();
  if (h.startsWith("[") && h.endsWith("]")) h = h.slice(1, -1);
  while (h.startsWith(".")) h = h.slice(1);
  while (h.endsWith(".")) h = h.slice(0, -1);
  return h;
}

function isIp(h) {
  if (h.includes(":")) return true; // IPv6
  const parts = h.split(".");
  return parts.length === 4 && parts.every((p) => /^\d{1,3}$/.test(p));
}

/**
 * The site (registrable domain) of a host name, or "" for an empty host.
 * IP addresses, single-label hosts and hosts that are themselves a public
 * suffix are their own site.
 */
export function siteOfHost(host) {
  const h = normalizeHost(host);
  if (!h) return "";
  if (isIp(h) || !h.includes(".")) return h;
  const labels = h.split(".");
  if (labels.some((l) => !l)) return h;
  const n = labels.length;
  let suffixLabels = 1; // no rule matches: the last label is the suffix
  for (let i = 0; i < n; i++) {
    const candidate = labels.slice(i).join(".");
    if (rules.exception.has(candidate)) {
      suffixLabels = n - i - 1;
      break;
    }
    if (rules.exact.has(candidate) || (i + 1 < n && rules.wildcard.has(labels.slice(i + 1).join(".")))) {
      suffixLabels = n - i;
      break;
    }
  }
  if (suffixLabels >= n) return h;
  return labels.slice(n - suffixLabels - 1).join(".");
}

/**
 * The site a tab address belongs to, or "" when the page is not a website
 * (about:, moz-extension:, file: and so on). Reader view and view-source of a
 * page count as that page's site, so the site stays "open".
 */
export function siteOfUrl(url, depth = 0) {
  if (!url || depth > 3) return "";
  const s = String(url);
  if (s.startsWith("view-source:")) return siteOfUrl(s.slice("view-source:".length), depth + 1);
  if (s.startsWith("blob:")) return siteOfUrl(s.slice("blob:".length), depth + 1);
  let u;
  try {
    u = new URL(s);
  } catch {
    return "";
  }
  if (u.protocol === "about:" && u.pathname === "reader") return siteOfUrl(u.searchParams.get("url"), depth + 1);
  if (u.protocol !== "http:" && u.protocol !== "https:") return "";
  return siteOfHost(u.hostname);
}

/** What the user typed in "add a site": an address or a host name. Returns the site or "". */
export function siteOfInput(text) {
  let t = String(text || "").trim().toLowerCase();
  if (!t) return "";
  if (!/^[a-z][a-z0-9+.-]*:\/\//.test(t)) t = "http://" + t;
  let u;
  try {
    u = new URL(t);
  } catch {
    return "";
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return "";
  const site = siteOfHost(u.hostname);
  return /^[a-z0-9.:-]+$/.test(site) ? site : "";
}
