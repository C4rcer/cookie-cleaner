// Unit test of shared/psl.js against the vendored Public Suffix List.
//   node tests/psl_test.mjs
// The cases follow the list's own published test vectors (registrable domain
// of a host), plus the hosts Dustpan meets in practice: cookie domains with a
// leading dot, IP addresses, single-label hosts and tab addresses.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parsePsl, setPsl, siteOfHost, siteOfUrl, siteOfInput } from "../src/shared/psl.js";

const dat = fileURLToPath(new URL("../src/vendor/public_suffix_list.dat", import.meta.url));
const rules = parsePsl(readFileSync(dat, "utf8"));
setPsl(rules);

let pass = 0;
const failed = [];
function eq(label, got, want) {
  if (got === want) pass++;
  else failed.push(`${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

const hosts = [
  // plain
  ["example.com", "example.com"],
  ["www.example.com", "example.com"],
  ["a.b.c.example.com", "example.com"],
  ["WWW.Example.COM", "example.com"],
  [".example.com", "example.com"],          // cookie domain
  ["example.com.", "example.com"],          // trailing dot
  // a suffix with two labels
  ["example.co.uk", "example.co.uk"],
  ["shop.example.co.uk", "example.co.uk"],
  ["news.other.co.uk", "other.co.uk"],
  ["b.example.com.au", "example.com.au"],
  // the host is itself a public suffix: it is its own site
  ["co.uk", "co.uk"],
  ["com", "com"],
  ["github.io", "github.io"],
  // wildcard rule *.ck with the exception !www.ck
  ["test.ck", "test.ck"],
  ["b.test.ck", "b.test.ck"],
  ["a.b.test.ck", "b.test.ck"],
  ["www.ck", "www.ck"],
  ["www.www.ck", "www.ck"],
  // wildcard *.kawasaki.jp with the exception !city.kawasaki.jp
  ["c.kawasaki.jp", "c.kawasaki.jp"],
  ["b.c.kawasaki.jp", "b.c.kawasaki.jp"],
  ["a.b.c.kawasaki.jp", "b.c.kawasaki.jp"],
  ["city.kawasaki.jp", "city.kawasaki.jp"],
  ["www.city.kawasaki.jp", "city.kawasaki.jp"],
  // more labels
  ["test.kyoto.jp", "test.kyoto.jp"],
  ["a.b.ide.kyoto.jp", "b.ide.kyoto.jp"],
  ["test.k12.ak.us", "test.k12.ak.us"],
  ["www.test.k12.ak.us", "test.k12.ak.us"],
  // private section
  ["alice.github.io", "alice.github.io"],
  ["www.alice.github.io", "alice.github.io"],
  ["bob.github.io", "bob.github.io"],
  ["myblog.blogspot.com", "myblog.blogspot.com"],
  // a top-level name that is not on the list: the last label is the suffix
  ["example.test", "example.test"],
  ["a.b.example.test", "example.test"],
  ["www.harbourshop.example", "harbourshop.example"],
  // international names: the list is in Unicode, hosts arrive as punycode
  ["xn--55qx5d.cn", "xn--55qx5d.cn"],                         // a public suffix by itself
  ["shop.xn--55qx5d.cn", "shop.xn--55qx5d.cn"],
  ["www.shop.xn--55qx5d.cn", "shop.xn--55qx5d.cn"],
  ["xn--85x722f.xn--fiqs8s", "xn--85x722f.xn--fiqs8s"],
  ["www.xn--85x722f.xn--fiqs8s", "xn--85x722f.xn--fiqs8s"],
  ["xn--bcher-kva.example", "xn--bcher-kva.example"],
  // not domain names
  ["localhost", "localhost"],
  ["192.168.1.20", "192.168.1.20"],
  ["127.0.0.1", "127.0.0.1"],
  ["[::1]", "::1"],
  ["::1", "::1"],
  ["", ""],
];
for (const [host, want] of hosts) eq(`siteOfHost(${host})`, siteOfHost(host), want);

const urls = [
  ["https://mail.example.com/inbox?x=1", "example.com"],
  ["http://shop.example.co.uk:8080/", "example.co.uk"],
  ["https://user:pw@www.example.org/", "example.org"],
  ["view-source:https://www.example.com/page", "example.com"],
  ["about:reader?url=https%3A%2F%2Fnews.example.co.uk%2Fstory", "example.co.uk"],
  ["blob:https://app.example.com/0f7c1b6e", "example.com"],
  ["http://192.168.1.20:3000/", "192.168.1.20"],
  ["http://[::1]:8080/", "::1"],
  ["about:blank", ""],
  ["about:newtab", ""],
  ["moz-extension://0f7c1b6e/app/app.html", ""],
  ["file:///C:/Users/me/page.html", ""],
  ["", ""],
  [undefined, ""],
];
for (const [url, want] of urls) eq(`siteOfUrl(${url})`, siteOfUrl(url), want);

const inputs = [
  ["example.com", "example.com"],
  ["  Mail.Example.com  ", "example.com"],
  ["https://accounts.example.co.uk/login", "example.co.uk"],
  ["not a site !!", ""],
  ["", ""],
  ["ftp://example.com", ""],
];
for (const [text, want] of inputs) eq(`siteOfInput(${text})`, siteOfInput(text), want);

eq("the list has both sections", rules.exact.has("com") && rules.exact.has("github.io"), true);
eq("the list has wildcard and exception rules", rules.wildcard.has("ck") && rules.exception.has("www.ck"), true);
eq("no rule is left in Unicode", [...rules.exact, ...rules.wildcard, ...rules.exception].every((r) => /^[\x21-\x7e]+$/.test(r)), true);

console.log(`${pass}/${pass + failed.length} passed (${rules.exact.size} rules, ${rules.wildcard.size} wildcards, ${rules.exception.size} exceptions)`);
for (const f of failed) console.log("  FAILED:", f);
process.exit(failed.length ? 1 : 0);
