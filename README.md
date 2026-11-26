# Dustpan: Auto Cookie Cleaner

Firefox add-on (desktop) that deletes a site's cookies shortly after you close
its last tab, except for the sites you choose to keep. Free, every feature
unlocked, no ads, no tracking, optional Ko-fi tip.

Why this one: the add-on people use for this, Cookie AutoDelete, has about
158k daily users on AMO and has not been updated since 2022-12. The design goal
here is "never surprise the user": a wrong delete signs people out of sites
they care about, so correct behaviour matters more than feature count.

Not part of YouTube/Twitch Enhancer: that add-on only runs on youtube.com and
twitch.tv, has no cookie features at all, and this one needs cookie access for
every site (an "all websites" prompt that YTE's users should never be asked
for in an update).

Desktop only: there is no Android emulator on the build machine, so nothing
could be tested on Firefox for Android. The manifest has no `gecko_android`
block and the listing says so.

## Name

"Dustpan: Auto Cookie Cleaner", slug `dustpan-cookie-cleaner`, gecko id
`dustpan-cookie-cleaner@c4rcer`, MPL-2.0. AMO search on 2026-11-12: "delete
cookies" and "auto delete cookies" both put Cookie AutoDelete first; "cookie
cleaner" is the phrase most other add-ons use in their names, but its top
results are small (CyberGhost Cookie Cleaner 4.9k, 2022; Cookie Cleaner
(Cookie Eraser) 768). "Auto Cookie Cleaner" carries both "auto" and "cookie
cleaner" without echoing "Cookie AutoDelete". No AMO add-on is called Dustpan
(only "Dustman - AutoClose Tabs"), and an unauthenticated GET on the slug and
the guid returned 404 on 2026-11-12.

## What it does

- **Cleans a site after its last tab closes**, after a grace delay (30 s by
  default; 10 s, 30 s, 1 min or 5 min in the settings). Reopen the site within
  the delay and nothing is deleted.
- **Off after install.** Until the setup in the dashboard is finished, nothing
  is deleted: closing a tab only adds a "Preview" line to the activity list
  ("would have been cleaned: 4 cookies"). The setup explains in plain words
  what will happen and lets the user tick sites to keep, with the sites that
  have an open tab listed first. Turning it on deletes nothing; cleaning starts
  with the next tab closed. No tab opens on install.
- **Keep list with two levels**: keep always, and keep until Firefox closes
  (cleaned about a minute after the next start, unless it is open again by
  then). One click in the toolbar popup keeps the current site; a tick on the
  toolbar button shows a kept site.
- **Restore** for recent cleans: the deleted cookies are kept in
  `storage.session` (memory, never written to disk) for 15 minutes, at most
  4 MB and 500 cleans, and put back with `cookies.set`, HttpOnly, session,
  domain-wide, partitioned and first-party-isolated cookies included. After a
  restore the popup offers to keep that site. Once a restore is no longer
  possible the entry says "Can no longer be restored" (the tooltip says why).
- **Activity list**: site, number of cookies, when and how (automatic, by you,
  at start, preview). Never a cookie's name or value. Last 300 entries.
- **Clean now** for the current site and **Clean everything not kept**, both
  with a confirmation that states the number of cookies (and sites), and an
  Undo afterwards.
- **"Not now"** on the waiting list skips one clean; **Keep** on it keeps the
  site.

## The rules

Checked in this order every time before anything is deleted:

1. Dustpan must still have access to the sites' cookies.
2. The site must not be open in any tab, in any window or container.
3. The site must not be on the keep list.
4. Automatic cleaning must be on (otherwise it is only a preview).

**A site** is the registrable domain: the public suffix plus one label, from
the Public Suffix List (both sections, ICANN and private, as Firefox itself
uses them). So `mail.example.com` and `accounts.example.com` are one site,
`shop.example.co.uk` and `news.other.co.uk` are two, and `alice.github.io` and
`bob.github.io` are two. IP addresses and single-label hosts are their own
site. Reader view, view-source and blob: addresses count as their page's site.

**Which site a cookie belongs to**: a cookie that Firefox keeps apart per
visited site belongs to that visited site. With first-party isolation that is
its `firstPartyDomain`; with Total Cookie Protection (Firefox's default, cookie
behaviour 5) it is `partitionKey.topLevelSite`. Every other cookie belongs to
the site of its own domain. So an embedded widget's cookies inside a kept site
are kept with it, and are cleaned with the site that embedded them.

**When is a site open**: by default a tab holds on to every site it has shown
since it was opened, until the tab closes. Going back in the tab, or a sign-in
that bounces through another site, then never loses its cookies. A setting
("Also clean a site when I leave it in the same tab") makes only the page a
tab shows now count.

**Firefox starting and quitting**:

- Nothing is cleaned in the first 60 s after Firefox starts, so session restore
  can bring tabs back first. Whatever is due then waits until that minute is
  over, and is dropped if its tab came back.
- While Firefox's "restore previous session?" page is showing, nothing is
  cleaned; the wait is pushed back.
- Quitting Firefox closes every window, which looks the same as the user
  closing windows. Sites that went away with their window and had not been
  cleaned yet are not cleaned at the next start, unless "When Firefox starts,
  clean the sites that were still open when it closed" is on. A site whose
  single tab was closed a moment before quitting is still cleaned (a minute
  after the start).
- With "clean what was still open" on, the sites that were open when Firefox
  closed and did not come back are cleaned a minute after the start.

**Containers**: every container's cookie store is checked, and a site is
cleaned in all of them at once, only when it is open in none of them.

**Private windows**: `"incognito": "not_allowed"`, so the user can not enable
Dustpan there. It never sees private tabs, and Firefox refuses it the private
cookie store. Firefox deletes private cookies itself when the last private
window closes.

**Site access switched off** (about:addons, Dustpan, Permissions): every event
checks `permissions.contains`. Without access, whatever was waiting is
dropped, nothing new is scheduled, the toolbar button shows "!", and the popup
and the dashboard say "Paused: no access to your sites" with the reason and a
"Give access back" button (`permissions.request`). Getting access back cleans
nothing by itself; only tabs closed after that count.

## Privacy and permissions

- `cookies`, `tabs`, `storage`, `alarms`, and `host_permissions: ["*://*/*"]`.
  Firefox only shows an add-on the cookies of sites it has host access to, so
  the "Access your data for all websites" prompt at install is unavoidable for
  a cookie cleaner. `tabs` is for the addresses of open tabs. No content
  scripts: Dustpan never reads or changes pages.
- `data_collection_permissions: none`, no remote code, no network requests at
  all (the only `fetch` reads the Public Suffix List from the add-on itself).
- `storage.local` holds the settings, the keep list, the waiting list, the
  sites open last time, the container ids seen, the activity list (site and
  count) and a total count of cleaned cookies. It never holds a cookie name or
  value; the E2E checks that.

## Public Suffix List

`src/vendor/public_suffix_list.dat`, unmodified.

| | |
| --- | --- |
| Source | https://publicsuffix.org/list/public_suffix_list.dat |
| Downloaded | 2026-11-12 |
| Version line | `2026-11-11_17-18-20_UTC`, commit `529030148729033bc6c30dbb05753b805a7d2155` |
| SHA-256 | `c0c17430faf1d0edb352e165dd3e5e6dfe890b1305cf548e20a572e8c46ff399` |
| License | Mozilla Public License 2.0 (header of the file) |

To update it, download the file again from the same address (nowhere else, as
its header asks), replace it, update this table and run the tests.
`shared/psl.js` parses it at runtime (exact, wildcard and exception rules;
Unicode rules converted to punycode with `URL`).

## Known limits

- **Cookies only.** localStorage, IndexedDB, cache and service workers are not
  cleaned in v0.1.0. `browsingData.remove` with `hostnames` could do part of
  that, but such data could not be put back with Restore, so a wrong clean
  could not be undone. Left out on purpose until that is solved.
- **Containers used before install**: Dustpan learns a container's cookie
  store from its tabs. Cookies in a container that has had no tab open since
  Dustpan was installed are not cleaned (and not counted by "Clean everything")
  until a tab opens in it. Cookies created after install always come from a tab
  Dustpan has seen. The `contextualIdentities` permission would remove this
  limit; not shipped in v0.1.0.
- **Restore is for 15 minutes and does not survive closing Firefox** (memory
  only, on purpose). Cookies that expired in the meantime are not put back; the
  message says how many were.
- **Restore puts cookies back, not server sessions**: if a site ended the
  session on its own server in the meantime, the restored cookie is refused by
  the site and the user signs in again.
- Sites open only in a private window are never seen or cleaned (Firefox's job).
- Desktop only, see above.

## The background page

`background.js` is a non-persistent event page (an ES module). Firefox stops it
after about 30 s without work and starts it again for a tab event, the alarm or
a message, so no state lives in variables:

| Key | Where | Holds |
| --- | --- | --- |
| `settings` | local | enabled, setup done, grace, the two options |
| `keep` | local | `{ site: "always" \| "session" }` |
| `pending` | local | `{ site: { due, preview, reason } }`, the waiting list; one alarm is set to the earliest `due` |
| `open` | local | the sites in use at the last tab event |
| `prevOpen` | local | `open` as it was when Firefox closed (read once at start) |
| `stores` | local | container cookie store ids seen in tabs |
| `log`, `stats` | local | activity (site and count), total cleaned |
| `boot` | session | set once per Firefox run; empty means Firefox just started |
| `visited` | session | per tab, the sites it has shown |
| `restore` | session | the deleted cookies, for Restore |

Every event and message runs one after another (a promise queue), and each one
first compares the sites in use now with the saved `open`: a site that dropped
out starts its wait, a site that is back stops waiting. The grace delay is an
`alarms` alarm, so a stopped background page is woken on time.

## Layout

```
src/                      everything that ships
  manifest.json
  background.js           tabs -> sites in use, waiting list, cleaning, restore, badge, messages
  popup/                  toolbar popup: status, this site, waiting, recent cleans
  app/                    dashboard (also the options page): setup, sites, activity, settings, support
  shared/psl.js           site of a host / address, from the Public Suffix List
  shared/config.js        defaults and limits
  shared/util.js          small UI helpers, the activity line, texts
  shared/base.css         colors, buttons, lists
  shared/support.*        Ko-fi pill + one-time milestone card (from the template)
  shared/more-addons.*    "More free add-ons" card + rate link (same file in every add-on; set `live: true` as listings are approved)
  vendor/                 public_suffix_list.dat (unmodified)
  icons/icon.svg
store-assets/listing.json AMO listing text, category, Ko-fi contributions_url
store-assets/screenshots/ 1280x800 listing images (made by tests/screenshots.py)
tests/                    real-Firefox E2E, suffix-list unit test, local test server, screenshots
tools/release.py          build / lint / submit / status / contrib / screenshots
```

## Develop and test

```powershell
python tools/release.py lint                 # build + web-ext lint the zip (expect 0/0/0)
node tests/psl_test.mjs                      # suffix list: 69 cases
python -m pip install selenium pillow        # once, ideally in a venv, for the tests
python tests/e2e_firefox.py                  # all seven sessions, 203 checks, about 10 minutes
python tests/e2e_firefox.py access           # one session by name
python tests/screenshots.py                  # regenerate store screenshots
```

The E2E installs the extracted built zip in throwaway headless, muted Firefox
profiles and visits pages from `tests/server.py` under made-up host names
(`network.dns.localDomains`). The grace delay is set to 3 s (6 s in `suspend`).
Never run it against a real profile.

Result on Firefox 147.0.3 (2026-11-12): 203 of 203, plus 69 of 69 in
`psl_test.mjs`.

| Session | Checks | What it covers |
| --- | --- | --- |
| `main` | 129 | Firefox's default cookie settings (Total Cookie Protection on). Manifest permissions; no tab on install. Off after install: closing a tab only logs a preview, nothing is deleted, "turn on" is refused until the setup is done. The setup: its words, open sites listed first, the summary and button count, nothing deleted when it is turned on. A site cleaned after its last tab closes, not before the delay, HttpOnly, session and domain-wide cookies included, and the server no longer sees the cookie. Keep always from one popup click, never cleaned, refused by both clean buttons. Subdomains grouped; `example.co.uk` vs `other.co.uk` and `alice.github.io` vs `bob.github.io` kept apart. A tab in another window, a tab in a container. The grace delay: reopening inside it, a full new wait after, "Not now". Restore: exact cookies back, HttpOnly too, the site knows the browser again, "Keep this site" after a restore, "Can no longer be restored" after 15 minutes, late restore refused, the memory buffer purged, the 4 MB cap. Partitioned cookies: cleaned and restored with the visited site, a tracker's own cookies apart from its partitioned ones, a kept site keeping what it embeds. Clean now (popup and dashboard) and clean everything: confirmation with the exact numbers, Cancel, Undo. Keep until Firefox closes while it stays open. Same-tab navigation both ways. Turning it off during a wait. The "restore session?" page. A tab closed by the browser itself. Going through the setup again. No cookie name or value in storage.local, the log, the popup or the dashboard. Dashboard keep list, filters, settings, activity. The thank-you card only after 1,000 cookies, "Don't ask again". Ko-fi links. The real toolbar popup. |
| `fpi` | 12 | `privacy.firstparty.isolate` on: every cookie carries `firstPartyDomain`; an embedded widget's cookies go with the visited site; grace delay, grouping, restore with HttpOnly, keep. |
| `suspend` | 13 | `extensions.background.idle.timeout` 2 s, grace 6 s. The background page is seen "stopped" during the wait; the alarm wakes it and the site is cleaned on time from storage; Restore works from the stopped state; reopening wakes it and cancels the wait; what a tab has visited survives the stop. |
| `access` | 14 | Site access switched off the way about:addons does it: noticed at once, the waiting list dropped, "!" on the button, nothing cleaned, both pages say "Paused" and why, clean buttons refuse; "Give access back" works and cleans nothing by itself; cleaning resumes for tabs closed after that. |
| `restart` | 22 | The add-on stopped and started with Firefox's start reason (`runtime.onStartup`, empty `storage.session`). Keep until Firefox closes ends at the start (cleaned after the minute, not before half of it), unless its tab came back; keep always untouched; a tab closed just before quitting is cleaned after the start; sites that were open at the end are left alone by default and cleaned with the option on; "Not now" still works; cleaning carries on afterwards. |
| `private` | 10 | A private window next to a normal one: Dustpan is not allowed there, sees no private tab, is refused the private store; the same site in a normal tab is cleaned while its private cookies stay; nothing about a private-only site is stored. |
| `control` | 3 | The same add-on with the Public Suffix List swapped for "the last two labels are the site": the grouping checks then fail (both `co.uk` sites become one, `github.io` users share one), which proves `main` tests the real list. |

Things measured in Firefox 147 while building this:

- `cookies.getAll({})` leaves out partitioned cookies (Total Cookie Protection
  is on by default, cookie behaviour 5). `partitionKey: {}` together with
  `firstPartyDomain: null` returns every cookie of a store.
- With first-party isolation on, `cookies.getAll` without `firstPartyDomain`
  throws ("the required 'firstPartyDomain' attribute was not set").
- `cookies.set` with the fields read from `getAll` (and `domain` only for
  domain cookies, no `expirationDate` for session cookies) recreates HttpOnly,
  partitioned and first-party-isolated cookies exactly: the JSON of the cookie
  read back is identical.
- In MV3 the install-time `*://*/*` can be switched off by the user. Afterwards
  `cookies.getAll` returns an empty list (no error) and `cookies.remove`
  returns `null`, so a cleaner that does not check would silently do nothing.
  `permissions.onRemoved` fires.
- The private cookie store throws "Extension disallowed access to the private
  cookies storeId" when the add-on is not allowed in private windows.
- `cookies.getAllCookieStores()` lists a container only while it has a tab.
- A browser restart can be simulated for an installed temporary add-on with
  `XPIInternal.BootstrapScope` (`shutdown`, then `startup` with
  `BOOTSTRAP_REASONS.APP_STARTUP`): `runtime.onStartup` fires and
  `storage.session` is empty, `storage.local` is kept. A temporary add-on does
  not survive a real restart, so this is as close as a test gets.

Manual: `about:debugging#/runtime/this-firefox` -> Load Temporary Add-on ->
`src/manifest.json`. Use a separate profile: Dustpan deletes real cookies.

## Release

Submitted to AMO on 2026-11-12: addon id 3126705, slug `dustpan-cookie-cleaner`,
v0.1.0 awaiting review. AMO validation 0 errors, 0 warnings, 0 notices. Read
back: 7 bold headings and no escaped tags, Ko-fi Contribute button, Firefox
desktop only, MPL-2.0, category privacy-security, 3 screenshots 1280x800
(preview ids 449474, 449475, 449476) with the captions from `listing.json`.

```powershell
python tools/release.py submit --notes "First release"
python tools/release.py screenshots          # after the listing exists
python tools/release.py status
```

Bump `version` in `src/manifest.json` for every later submit.
