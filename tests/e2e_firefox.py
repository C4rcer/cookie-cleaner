"""End-to-end test of Dustpan in a real Firefox (Selenium + geckodriver).

  python -m pip install selenium pillow      (once, ideally in a venv)
  python tools/release.py build
  python tests/e2e_firefox.py [main] [fpi] [suspend] [access] [restart] [private] [control]

Installs the built zip (extracted, by path) as a temporary add-on in throwaway
profiles and visits pages served by tests/server.py under made-up host names
(network.dns.localDomains). Every browser runs headless and muted. Nothing here
touches a real Firefox profile.

Sessions (all run when none is named):
  main     the whole add-on with Firefox's default cookie settings (Total
           Cookie Protection on): off and preview, the setup, the grace delay,
           grouping by site, other windows, containers, restore, partitioned
           cookies, the log, clean now, keep levels, same-tab navigation
  fpi      the same core rules with first-party isolation switched on
  suspend  the background page is stopped by Firefox after 2 s without work,
           during the grace delay
  access   site access is switched off after install, and given back
  restart  the add-on is stopped and started again the way a browser restart
           does it: keep until Firefox closes, tabs that were open at the end
  private  a private window next to a normal one
  control  the same add-on with the suffix list swapped for a guess based on
           dots: the grouping checks of "main" then fail, which proves they
           test the real thing
"""
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402
from harness import ADDON_ID, EXT, Fx, check, latest_zip, results, wait  # noqa: E402

PORT = 8975
G = 3  # grace delay used by the tests, in seconds
st = server.STATE
SECRET = "ZQX"  # every secret cookie name and value of the test server contains this

HOSTS = [
    "mail.example.com", "accounts.example.com", "www.example.org",
    "shop.example.co.uk", "news.other.co.uk", "alice.github.io", "bob.github.io",
    "widget.tracker.test", "www.basic.test", "www.kept.test", "www.win.test", "www.box.test", "www.grace.test",
    "www.skip.test", "www.restore.test", "www.restore2.test", "www.expire.test", "top.test", "ptop.test",
    "www.manual.test", "www.session.test", "www.nav-a.test", "www.nav-b.test", "www.off.test", "www.defer.test",
    "www.real.test", "www.priv.test", "www.privonly.test", "www.one.test", "www.two.test", "www.three.test",
    "www.four.test", "www.five.test", "www.six.test", "www.seven.test",
]


def u(host, path="/"):
    return f"http://{host}:{PORT}{path}"


def snap(fx, host, **kw):
    """The cookies of a host, as comparable text."""
    return sorted(json.dumps(c, sort_keys=True) for c in fx.jar(host, **kw))


def gone(fx, host, timeout=G + 4, **kw):
    return wait(lambda: fx.names(host, **kw) == [], timeout, 0.2)


def settle(fx, extra=2.0):
    """Wait until every grace delay that is running now is over."""
    time.sleep(G + extra)


def last_log(fx, site):
    entries = fx.log(site=site)
    return entries[-1] if entries else None


def start(unpacked, prefs=None, grace=G):
    fx = Fx(unpacked, HOSTS, prefs)
    st.reset()
    fx.grace(grace)
    return fx


def enable(fx, keep=None):
    """Finish the setup through the same message the setup page sends."""
    return fx.send("setup:finish", keep=keep or {})


# =================================================================== main

def session_main(unpacked):
    fx = start(unpacked)
    try:
        # ---- install
        man = json.loads((unpacked / "manifest.json").read_text(encoding="utf-8"))
        check("manifest: only cookies, tabs, storage, alarms and site access",
              sorted(man["permissions"]) == ["alarms", "cookies", "storage", "tabs"] and man["host_permissions"] == ["*://*/*"]
              and "optional_permissions" not in man and man["incognito"] == "not_allowed", man)
        check("manifest: no data collection, non-persistent background page",
              man["browser_specific_settings"]["gecko"]["data_collection_permissions"] == {"required": ["none"]}
              and man["background"] == {"scripts": ["background.js"], "type": "module"}, man)
        check("install opens no tab and no window", fx.handles_after_install == 1, fx.handles_after_install)
        check("fresh install: automatic cleaning is off", fx.state()["settings"]["enabled"] is False and fx.state()["settings"]["setupDone"] is False)
        check("site access is granted at install", fx.access() is True)

        # ---- off: nothing is deleted, only a preview is logged
        t = fx.open(u("mail.example.com", "/?d=example.com"))
        base = fx.names("example.com")
        check("the test site set four cookies, one of them HttpOnly", base == ["js", "sess", "sid_ZQXNAME", "wide"]
              and any(c["httpOnly"] for c in fx.jar("example.com")), base)
        fx.open_popup(t)
        check("popup while off: says so and offers the setup", fx.xtext("#statusTitle") == "Automatic cleaning is off"
              and fx.xtext("#statusBtn") == "Set up automatic cleaning" and "deletes nothing by itself" in fx.xtext("#statusText"), fx.xtext("#statusText"))
        check("popup while off: the site by its registrable domain, with its cookie count",
              fx.xtext("#siteName") == "example.com" and fx.xtext("#siteCount") == "4 cookies", (fx.xtext("#siteName"), fx.xtext("#siteCount")))
        check("popup while off: 'would be cleaned', not 'will be'", fx.xtext("#siteState").startswith("Would be cleaned 3 seconds after")
              and "if automatic cleaning were on" in fx.xtext("#siteState"), fx.xtext("#siteState"))
        fx.close(t)
        p = wait(lambda: fx.pending().get("example.com"), 3)
        check("off: closing the tab only schedules a preview", bool(p) and p["preview"] is True, p)
        fx.open_popup(fx.page_tab_id())
        check("popup while off: the waiting list is labelled as a preview", fx.xtext("#pendingTitle") == "Would be cleaned (preview)"
              and fx.xtexts("#pendingList .site") == ["example.com"] and not fx.shown('#pendingList [data-act="skip"]'), fx.xtext("#pendingTitle"))
        settle(fx)
        check("off: nothing is deleted after the grace delay", fx.names("example.com") == base, fx.names("example.com"))
        log = fx.log()
        check("off: the log holds one preview entry with site and count", len(log) == 1 and log[0]["kind"] == "preview"
              and log[0]["site"] == "example.com" and log[0]["count"] == 4, log)
        check("off: turning it on is refused until the setup is done", fx.send("enabled:set", value=True) == {"ok": False, "reason": "setup"}
              and fx.settings().get("enabled") is not True, fx.settings())

        # ---- the setup
        t_acc = fx.open(u("accounts.example.com"))
        t_shop = fx.open(u("shop.example.co.uk"))
        t_org = fx.open(u("www.example.org"))
        fx.close(t_org)
        settle(fx)
        before = snap(fx, "example.com") + snap(fx, "example.co.uk") + snap(fx, "example.org")
        fx.open_app("#setup")
        check("setup opens on step 1 and nothing else is switched on", fx.shown("#step1") and not fx.shown("#step2") and fx.settings().get("enabled") is not True)
        words = fx.xtext("#step1")
        check("setup explains in plain words: what happens, signed out, never touched, restore, nothing deleted now",
              "waits 3 seconds and then deletes that site's cookies" in words and "You will be signed out." in words
              and "still open in any tab, window or container" in words and "Restore puts the cookies back" in words
              and "gone for good" in words and "Nothing is deleted when you turn it on." in words, words)
        fx.click("#toStep2")
        open_sites = fx.xtexts("#setupOpen .site")
        other_sites = fx.xtexts("#setupOther .site")
        check("setup lists the sites with open tabs first", sorted(open_sites) == ["example.co.uk", "example.com"] and other_sites == ["example.org"]
              and fx.xjs("return !!(document.querySelector('#openGroup').compareDocumentPosition(document.querySelector('#otherGroup')) & 4);"),
              (open_sites, other_sites))
        check("setup: nothing is ticked to begin with, and it says what that means",
              fx.xjs("return document.querySelectorAll('#step2 input:checked').length") == 0
              and "keeping no sites" in fx.xtext("#setupSummary") and "keeping no sites" in fx.xtext("#setupFinish"), fx.xtext("#setupSummary"))
        fx.click('#setupOpen li[data-site="example.co.uk"] input')
        check("setup: the summary and the button count the ticked sites", "keeping 1 site." in fx.xtext("#setupSummary")
              and "The other 2 sites" in fx.xtext("#setupSummary") and fx.xtext("#setupFinish") == "Turn on automatic cleaning, keeping 1 site",
              (fx.xtext("#setupSummary"), fx.xtext("#setupFinish")))
        fx.click("#setupFinish")
        check("setup done: cleaning is on and the ticked site is kept", wait(lambda: fx.settings().get("enabled") is True, 5)
              and fx.settings().get("setupDone") is True and fx.keep() == {"example.co.uk": "always"}, (fx.settings(), fx.keep()))
        check("turning it on deletes nothing and leaves nothing waiting",
              snap(fx, "example.com") + snap(fx, "example.co.uk") + snap(fx, "example.org") == before and fx.pending() == {})
        check("dashboard shows it is on", wait(lambda: fx.xtext("#statusTitle") == "Automatic cleaning is on", 5) and not fx.shown("#setup"), fx.xtext("#statusTitle"))
        fx.close(t_acc, t_shop)
        check("first real clean: example.com goes after its tab closed", gone(fx, "example.com"))
        check("the ticked site keeps its cookies", fx.names("example.co.uk") == ["js", "sess", "sid_ZQXNAME"], fx.names("example.co.uk"))

        # ---- the basic rule, with its timing
        t = fx.open(u("www.basic.test", "/?d=basic.test"))
        fx.open_popup(t)
        check("popup while on: 'will be cleaned 3 seconds after you close its last tab'", fx.xtext("#statusTitle") == "Automatic cleaning is on"
              and fx.xtext("#siteState") == "Will be cleaned 3 seconds after you close its last tab.", fx.xtext("#siteState"))
        t0 = time.time()
        fx.close(t)
        p = wait(lambda: fx.pending().get("basic.test"), 2)
        check("closing the last tab starts the wait", bool(p) and p["preview"] is False and p["reason"] == "closed"
              and abs(p["due"] / 1000 - (t0 + G)) < 1.2, p)
        time.sleep(max(0, t0 + G - 1.3 - time.time()))
        check("nothing is deleted before the wait is over", fx.names("basic.test") == ["js", "sess", "sid_ZQXNAME", "wide"], fx.names("basic.test"))
        ok = gone(fx, "basic.test")
        took = time.time() - t0
        check("all four cookies are deleted when it is over: HttpOnly, session and domain-wide ones too", ok and G - 0.5 <= took <= G + 3, took)
        e = last_log(fx, "basic.test")
        check("the log entry: site and number, nothing else", bool(e) and e["kind"] == "auto" and e["count"] == 4
              and sorted(e) == ["at", "count", "id", "kind", "site"], e)
        st.reset()
        t = fx.open(u("www.basic.test"))
        check("the site no longer knows the browser", st.requests("www.basic.test", "/")[-1]["cookie"] == "", st.requests("www.basic.test"))
        fx.close(t)
        gone(fx, "basic.test")

        # ---- keep always: one click in the popup, never cleaned
        t = fx.open(u("www.kept.test"))
        fx.open_popup(t)
        fx.click("#keepAlways")
        check("one click in the popup adds the current site to the keep list", wait(lambda: fx.keep().get("kept.test") == "always", 3), fx.keep())
        check("popup: the kept site says so and offers no clean button", wait(lambda: fx.xtext("#siteState") == "On your keep list. Dustpan never cleans it.", 3)
              and not fx.shown("#cleanSite") and not fx.shown("#keepAlways") and fx.shown("#unkeep"), fx.xtext("#siteState"))
        check("toolbar button shows a tick on a kept site's tab", wait(lambda: fx.badge(t) == "✓", 3), fx.badge(t))
        kept = snap(fx, "kept.test")
        fx.close(t)
        time.sleep(0.6)
        check("a kept site is not even put on the waiting list", "kept.test" not in fx.pending(), fx.pending())
        settle(fx)
        check("a kept site is never cleaned", snap(fx, "kept.test") == kept and fx.log(site="kept.test") == [])
        r = fx.send("clean:site", site="kept.test")
        check("'clean now' refuses a kept site", r == {"ok": False, "reason": "kept"} and snap(fx, "kept.test") == kept, r)
        fx.send("clean:all", sites=["kept.test"])
        check("'clean everything' skips a kept site even when asked for it", snap(fx, "kept.test") == kept)

        # ---- grouping by site
        m = fx.open(u("mail.example.com", "/?d=example.com"))
        a = fx.open(u("accounts.example.com"))
        both = snap(fx, "example.com")
        fx.close(m)
        time.sleep(0.6)
        check("two subdomains are one site: closing one of them schedules nothing", "example.com" not in fx.pending(), fx.pending())
        settle(fx)
        check("subdomains grouped: nothing cleaned while the other subdomain is open", snap(fx, "example.com") == both and len(both) == 7, len(both))
        fx.close(a)
        check("subdomains grouped: both are cleaned together once the last one closes",
              gone(fx, "example.com") and last_log(fx, "example.com")["count"] == 7, last_log(fx, "example.com"))
        n = fx.open(u("news.other.co.uk"))
        s = fx.open(u("shop.example.co.uk"))
        fx.keep_set("example.co.uk", None)
        other = snap(fx, "other.co.uk")
        fx.close(s)
        check("two sites under co.uk are two sites: one is cleaned", gone(fx, "example.co.uk") and last_log(fx, "example.co.uk")["count"] == 3)
        check("two sites under co.uk are two sites: the other, still open, is untouched", snap(fx, "other.co.uk") == other and len(other) == 3)
        fx.close(n)
        gone(fx, "other.co.uk")
        al = fx.open(u("alice.github.io"))
        bo = fx.open(u("bob.github.io"))
        bob = snap(fx, "bob.github.io")
        fx.close(al)
        check("alice.github.io and bob.github.io are two sites (private section of the suffix list)",
              gone(fx, "alice.github.io") and snap(fx, "bob.github.io") == bob and last_log(fx, "alice.github.io")["site"] == "alice.github.io")
        fx.close(bo)
        gone(fx, "bob.github.io")

        # ---- a tab in another window
        t1 = fx.open(u("www.win.test"))
        w2, t2 = fx.new_window(u("www.win.test"))
        win = snap(fx, "win.test")
        fx.close(t1)
        settle(fx)
        check("still open in another window: not cleaned, not waiting", snap(fx, "win.test") == win and "win.test" not in fx.pending())
        fx.close_window(w2)
        p = wait(lambda: fx.pending().get("win.test"), 2)
        check("closing that window starts the wait", bool(p) and p["reason"] == "window", p)
        check("cleaned once the other window is closed too", gone(fx, "win.test"))

        # ---- a tab in a container
        t1 = fx.open(u("www.box.test"))
        t2 = fx.open(u("www.box.test"), cookieStoreId="firefox-container-1")
        check("container tab has its own cookies", len(fx.jar("box.test", store="firefox-container-1")) == 3 and len(fx.jar("box.test", store="firefox-default")) == 3)
        box = snap(fx, "box.test")
        fx.close(t1)
        settle(fx)
        check("still open in a container: not cleaned in any cookie store", snap(fx, "box.test") == box and "box.test" not in fx.pending())
        fx.close(t2)
        check("cleaned in the default store and in the container once it is open nowhere",
              gone(fx, "box.test") and last_log(fx, "box.test")["count"] == 6, last_log(fx, "box.test"))
        t2 = fx.open(u("www.box.test"), cookieStoreId="firefox-container-2")
        fx.close(t2)
        check("a site that was only open in a container is cleaned there", gone(fx, "box.test", store="firefox-container-2"))

        # ---- the grace delay
        t = fx.open(u("www.grace.test"))
        grace = snap(fx, "grace.test")
        fx.close(t)
        wait(lambda: "grace.test" in fx.pending(), 2)
        time.sleep(1.0)
        t = fx.open(u("www.grace.test"))
        check("reopening inside the grace delay takes the site off the waiting list", "grace.test" not in fx.pending(), fx.pending())
        settle(fx)
        check("reopened inside the grace delay: nothing deleted", fx.names("grace.test") == ["js", "sess", "sid_ZQXNAME"] and len(grace) == 3
              and fx.log(site="grace.test") == [], fx.names("grace.test"))
        t0 = time.time()
        fx.close(t)
        time.sleep(G - 1.3)
        still = fx.names("grace.test")
        ok = gone(fx, "grace.test")
        check("closed again: a full new wait, then cleaned", len(still) == 3 and ok and time.time() - t0 >= G - 0.5, (still, time.time() - t0))
        t = fx.open(u("www.skip.test"))
        fx.close(t)
        wait(lambda: "skip.test" in fx.pending(), 2)
        fx.open_popup(fx.page_tab_id())
        check("popup shows what is waiting, with a countdown", fx.xtext("#pendingTitle") == "Waiting to be cleaned"
              and fx.xtexts("#pendingList .site") == ["skip.test"] and fx.xtext("#pendingList .when").startswith("in "), fx.xtext("#pendingList"))
        fx.click('#pendingList [data-act="skip"]')
        check("'Not now' takes it off the waiting list", wait(lambda: "skip.test" not in fx.pending(), 3))
        settle(fx)
        check("'Not now': the site keeps its cookies this time", len(fx.names("skip.test")) == 3)

        # ---- restore
        t = fx.open(u("www.restore.test", "/?d=restore.test"))
        want = snap(fx, "restore.test")
        fx.close(t)
        check("restore: the site is cleaned first", gone(fx, "restore.test") and len(want) == 4)
        fx.open_popup(fx.page_tab_id())
        check("popup lists the clean with a Restore button", fx.xtexts("#recentList .log-item .site")[0] == "restore.test"
              and fx.shown('#recentList .log-item[data-site="restore.test"] [data-restore="can"]'))
        fx.click('#recentList .log-item[data-site="restore.test"] [data-restore="can"]')
        check("restore puts every cookie back exactly as it was: HttpOnly, session and domain-wide included",
              wait(lambda: snap(fx, "restore.test") == want, 5), snap(fx, "restore.test"))
        check("popup says what was put back", fx.xtext("#noticeText") == "Put back 4 cookies for restore.test. Reload the page to be signed in again.", fx.xtext("#noticeText"))
        e = last_log(fx, "restore.test")
        check("the entry is marked restored, in the log and in the popup", e.get("restored") == 4
              and wait(lambda: fx.xtext('#recentList .log-item[data-site="restore.test"] [data-restore="done"]') == "Restored", 3), e)
        st.reset()
        t = fx.open(u("www.restore.test"))
        check("the site knows the browser again", "sid_ZQXNAME=ZQXVALUE7731-www.restore.test" in st.requests("www.restore.test", "/")[-1]["cookie"])
        fx.close(t)
        gone(fx, "restore.test")
        t = fx.open(u("www.restore2.test"))
        fx.close(t)
        gone(fx, "restore2.test")
        fx.open_popup(fx.page_tab_id())
        fx.click('#recentList .log-item[data-site="restore2.test"] [data-restore="can"]')
        wait(lambda: fx.shown("#keepRestored"), 3)
        check("after a restore the popup offers to keep the site", fx.xtext("#keepRestored") == "Keep restore2.test")
        fx.click("#keepRestored")
        check("one click keeps the restored site", wait(lambda: fx.keep().get("restore2.test") == "always", 3))

        t = fx.open(u("www.expire.test"))
        fx.close(t)
        gone(fx, "expire.test")
        eid = last_log(fx, "expire.test")["id"]
        fx.api("""
          const got = await browser.storage.session.get("restore");
          for (const e of got.restore) if (e.id === arguments[0]) e.at -= 16 * 60000;
          await browser.storage.session.set({ restore: got.restore });""", eid)
        fx.open_popup(fx.page_tab_id())
        gone_el = '#recentList .log-item[data-site="expire.test"] [data-restore="gone"]'
        check("after 15 minutes the popup says a restore is no longer possible, and why", fx.xtext(gone_el) == "Can no longer be restored"
              and "gone for good" in fx.xjs("return document.querySelector(arguments[0]).title", gone_el)
              and not fx.shown('#recentList .log-item[data-site="expire.test"] [data-restore="can"]'), fx.xtext(gone_el))
        r = fx.send("restore", ids=[eid])
        check("a late restore is refused and sets nothing", r["results"] == [{"id": eid, "ok": False}] and fx.names("expire.test") == [], r)
        fx.api("browser.alarms.create('purge', { when: Date.now() + 200 });")
        check("the expired cookies are dropped from memory", wait(lambda: all(e["id"] != eid for e in fx.sess("restore").get("restore", [])), 5))

        # ---- partitioned cookies (Total Cookie Protection)
        tw = fx.open(u("widget.tracker.test"))
        tt = fx.open(u("top.test", "/embed?w=widget.tracker.test"))
        wait(lambda: len(fx.jar("widget.tracker.test", top="top.test")) == 2, 5)
        part = fx.jar("widget.tracker.test", top="top.test")
        check("the embedded widget's cookies are partitioned under the visited site",
              sorted(c["name"] for c in part) == ["fhttp", "fjs"] and all(c["partitionKey"]["topLevelSite"] == "http://top.test" for c in part), part)
        own = snap(fx, "widget.tracker.test", top=False)
        fx.close(tw)
        check("closing the tracker's own tab cleans its own cookies", wait(lambda: fx.names("widget.tracker.test", top=False) == [], G + 4, 0.2) and len(own) == 3)
        check("but not the ones it holds inside a site that is still open", len(fx.jar("widget.tracker.test", top="top.test")) == 2)
        tw = fx.open(u("widget.tracker.test"))
        own = snap(fx, "widget.tracker.test", top=False)
        want = snap(fx, "top.test") + snap(fx, "widget.tracker.test", top="top.test")
        fx.close(tt)
        check("closing the visited site cleans its cookies and the partitioned ones under it",
              gone(fx, "top.test") and fx.jar("widget.tracker.test", top="top.test") == [] and last_log(fx, "top.test")["count"] == 3, last_log(fx, "top.test"))
        check("the tracker's own cookies, with its tab open, are untouched", snap(fx, "widget.tracker.test", top=False) == own and len(own) == 3)
        r = fx.send("restore", ids=[last_log(fx, "top.test")["id"]])
        check("restore puts partitioned cookies back into their partition",
              snap(fx, "top.test") + snap(fx, "widget.tracker.test", top="top.test") == want and r["results"][0]["set"] == 3, r)
        fx.send("clean:site", site="top.test")
        fx.keep_set("ptop.test", "always")
        tp = fx.open(u("ptop.test", "/embed?w=widget.tracker.test"))
        wait(lambda: len(fx.jar("widget.tracker.test", top="ptop.test")) == 2, 5)
        fx.close(tp, tw)
        gone(fx, "widget.tracker.test", top=False)
        settle(fx, 1.0)
        check("a kept site keeps the partitioned cookies of what it embeds, even when that tracker itself is cleaned",
              len(fx.jar("widget.tracker.test", top="ptop.test")) == 2 and fx.names("ptop.test") == ["top"], fx.jar("widget.tracker.test"))

        # ---- clean now: this site
        t = fx.open(u("www.manual.test"))
        fx.open_popup(t)
        fx.click("#cleanSite")
        check("clean now asks first and states the number of cookies", fx.shown("#confirm")
              and fx.xtext("#confirmText") == "Delete 3 cookies for manual.test now? You will be signed out of it."
              and fx.xtext("#confirmYes") == "Delete 3 cookies", fx.xtext("#confirmText"))
        fx.click("#confirmNo")
        check("Cancel deletes nothing", not fx.shown("#confirm") and len(fx.names("manual.test")) == 3)
        fx.click("#cleanSite")
        fx.click("#confirmYes")
        check("confirmed: the site is cleaned although its tab is open", wait(lambda: fx.names("manual.test") == [], 5)
              and last_log(fx, "manual.test")["kind"] == "manual" and last_log(fx, "manual.test")["count"] == 3)
        check("the popup reports it and offers Undo", wait(lambda: fx.xtext("#noticeText") == "Deleted 3 cookies for manual.test.", 3) and fx.shown("#undo"), fx.xtext("#noticeText"))
        fx.click("#undo")
        check("Undo puts them back", wait(lambda: len(fx.names("manual.test")) == 3, 5))
        fx.close(t)
        gone(fx, "manual.test")

        # ---- keep until Firefox closes (while Firefox stays open)
        t = fx.open(u("www.session.test"))
        fx.open_popup(t)
        fx.click("#keepSession")
        check("popup: keep until Firefox closes", wait(lambda: fx.keep().get("session.test") == "session", 3)
              and wait(lambda: fx.xtext("#siteState") == "Kept until Firefox closes. It is cleaned the next time Firefox starts.", 3), fx.xtext("#siteState"))
        sess = snap(fx, "session.test")
        fx.close(t)
        settle(fx)
        check("kept until Firefox closes: closing its tab cleans nothing", snap(fx, "session.test") == sess and "session.test" not in fx.pending()
              and fx.log(site="session.test") == [])

        # ---- moving on to another site in the same tab
        t = fx.open(u("www.nav-a.test"))
        fx.nav(t, u("www.nav-b.test"))
        settle(fx)
        check("default: a tab holds on to a site it has left, so Back still works", len(fx.names("nav-a.test")) == 3 and "nav-a.test" not in fx.pending(), fx.pending())
        fx.close(t)
        check("closing that tab cleans every site it had visited", gone(fx, "nav-a.test") and gone(fx, "nav-b.test"))
        fx.send("settings:set", patch={"onNavigate": True})
        t = fx.open(u("www.nav-a.test"))
        fx.nav(t, u("www.nav-b.test"))
        check("option on: leaving a site in the same tab starts its wait", wait(lambda: "nav-a.test" in fx.pending(), 2), fx.pending())
        check("option on: the site that was left is cleaned, the one being shown is not", gone(fx, "nav-a.test") and len(fx.names("nav-b.test")) == 3)
        fx.nav(t, u("www.nav-a.test"))
        fx.nav(t, u("www.nav-b.test"))
        wait(lambda: "nav-a.test" in fx.pending(), 2)
        fx.nav(t, u("www.nav-a.test"))
        check("option on: going back inside the grace delay stops the wait", "nav-a.test" not in fx.pending())
        fx.send("settings:set", patch={"onNavigate": False})
        fx.close(t)
        gone(fx, "nav-a.test")
        gone(fx, "nav-b.test")

        # ---- switched off in the middle of a wait
        t = fx.open(u("www.off.test"))
        fx.close(t)
        wait(lambda: "off.test" in fx.pending(), 2)
        fx.open_popup(fx.page_tab_id())
        fx.click("#statusBtn")
        check("Turn off in the popup stops everything that was waiting", wait(lambda: fx.settings()["enabled"] is False, 3) and fx.pending() == {}, fx.pending())
        settle(fx)
        check("switched off during the wait: nothing deleted", len(fx.names("off.test")) == 3)
        check("after the setup the popup offers a plain Turn on", fx.xtext("#statusBtn") == "Turn on")
        fx.click("#statusBtn")
        check("Turn on: on again, and nothing is cleaned for what happened while it was off",
              wait(lambda: fx.settings()["enabled"] is True, 3) and fx.pending() == {} and len(fx.names("off.test")) == 3)

        # ---- Firefox asking whether to restore the last session
        t = fx.open(u("www.defer.test"))
        fx.page_get("about:sessionrestore")
        fx.close(t)
        settle(fx)
        p = fx.pending().get("defer.test")
        check("while Firefox shows its 'restore session?' page nothing is cleaned, the wait is pushed back",
              len(fx.names("defer.test")) == 3 and bool(p) and p["due"] / 1000 - time.time() > 30, p)
        fx.send("pending:cancel", site="defer.test")
        fx.page_get("about:blank")

        # ---- clean everything not kept
        for i, host in enumerate(["www.one.test", "www.two.test"]):
            for k in range(i + 2):
                fx.set_cookie(url=f"http://{host}/", name=f"left{k}", value="x", expirationDate=int(time.time()) + 3600)
        to = fx.open(u("www.three.test"))
        s0 = fx.state()
        sweep = s0["sweep"]
        every = fx.jar()
        open_and_kept = snap(fx, "three.test") + snap(fx, "kept.test") + snap(fx, "session.test") + snap(fx, "ptop.test") + snap(fx, "restore2.test")
        check("the count for 'clean everything' leaves out open and kept sites",
              {"one.test", "two.test", "off.test", "skip.test", "defer.test", "example.org"} <= set(sweep["sites"])
              and not {"three.test", "kept.test", "session.test", "ptop.test", "restore2.test"} & set(sweep["sites"]), sweep)
        fx.open_app()
        fx.click("#cleanAll")
        n_sites, n_cookies = len(sweep["sites"]), sweep["cookies"]
        text = fx.xtext("#confirmText")
        check("clean everything asks first and states the number of sites and cookies",
              fx.shown("#confirm") and text.startswith(f"Delete {n_cookies} cookies from {n_sites} sites? You will be signed out of them.")
              and f"Sites with an open tab ({sweep['open']}) and sites on your keep list ({sweep['kept']}) are left alone." in text
              and fx.xtext("#confirmYes") == f"Delete {n_cookies} cookies from {n_sites} sites", text)
        fx.click("#confirmNo")
        check("Cancel deletes nothing", len(fx.jar()) == len(every))
        fx.click("#cleanAll")
        fx.click("#confirmYes")
        wait(lambda: fx.shown("#notice"), 8)
        left = fx.jar()
        check("confirmed: exactly the stated number of cookies is deleted", len(every) - len(left) == n_cookies
              and fx.xtext("#noticeText") == f"Deleted {n_cookies} cookies from {n_sites} sites.", (len(every), len(left), fx.xtext("#noticeText")))
        check("open and kept sites are untouched",
              snap(fx, "three.test") + snap(fx, "kept.test") + snap(fx, "session.test") + snap(fx, "ptop.test") + snap(fx, "restore2.test") == open_and_kept)
        check("every site that was neither open nor kept is empty", all(fx.names(s) == [] for s in ["one.test", "two.test", "off.test", "skip.test", "defer.test", "example.org"]))
        fx.click("#undo")
        check("Undo after clean everything puts all of it back",
              wait(lambda: sorted(json.dumps(c, sort_keys=True) for c in fx.jar()) == sorted(json.dumps(c, sort_keys=True) for c in every), 8), len(fx.jar()))
        fx.close(to)
        gone(fx, "three.test")

        # ---- the restore buffer has a size limit
        big = ["www.four.test", "www.five.test", "www.six.test", "www.seven.test", "www.one.test", "www.two.test", "www.three.test", "www.basic.test"]
        fx.send("clean:all", sites=[h[4:] for h in big])
        fx.api("""
          const exp = Math.floor(Date.now() / 1000) + 3600;
          const value = "v".repeat(3900);
          for (const host of arguments[0]) {
            for (let i = 0; i < 150; i++) await browser.cookies.set({ url: "http://" + host + "/", name: "big" + i, value, expirationDate: exp });
          }""", big)
        check("eight sites hold 150 large cookies each", all(len(fx.names(h)) == 150 for h in big))
        fx.send("log:clear")
        r = fx.send("clean:all", sites=[h[4:] for h in big])
        buf = fx.sess("restore")["restore"]
        size = sum(e["bytes"] for e in buf)
        can = [e for e in fx.state()["log"] if e["restoreUntil"]]
        check("more than the limit was deleted at once: the buffer stays under 4 MB by dropping the oldest",
              len(r["entries"]) == 8 and size <= 4 * 1024 * 1024 and 1 <= len([e for e in buf if e["site"] in [h[4:] for h in big]]) < 8, (size, len(buf)))
        check("the log says honestly which of them can still be restored", 1 <= len(can) < 8 and len(fx.state()["log"]) == 8, len(can))
        fx.send("restore", ids=[e["id"] for e in fx.state()["log"]])
        fx.send("clean:all", sites=[h[4:] for h in big])
        fx.api("await browser.storage.session.set({ restore: [] });")

        # ---- the log and what is written to disk
        dump = json.dumps(fx.store(None))
        check("storage.local holds no cookie name or value", SECRET not in dump and "fhttp" not in dump, dump[:300])
        keys = set().union(*[set(e) for e in fx.store("log")["log"]]) if fx.store("log")["log"] else set()
        t = fx.open(u("www.basic.test"))
        fx.close(t)
        gone(fx, "basic.test")
        keys |= set().union(*[set(e) for e in fx.log()])
        check("log entries have no field that could hold one", keys <= {"id", "at", "kind", "site", "count", "left", "restored", "restoredAt"}, keys)
        sess_dump = fx.sess(None)
        check("the deleted cookies exist only in storage.session (memory), under 'restore'",
              SECRET in json.dumps(sess_dump.get("restore")) and SECRET not in json.dumps({k: v for k, v in sess_dump.items() if k != "restore"})
              and SECRET not in json.dumps(fx.store(None)))
        fx.open_app()
        page_text = fx.body_text()
        check("the dashboard shows sites and numbers, never a cookie name or value", SECRET not in page_text and "basic.test" in page_text)
        fx.open_popup(fx.page_tab_id())
        check("neither does the popup", SECRET not in fx.body_text() and "basic.test" in fx.body_text())

        # ---- dashboard: keep list, filters, activity, settings
        fx.open_app()
        fx.xjs("document.getElementById('addInput').value = arguments[0];", "https://Mail.Example.com/inbox?x=1")
        fx.click('#addForm button[type="submit"]')
        check("typing an address keeps its whole site", wait(lambda: fx.keep().get("example.com") == "always", 3)
              and wait(lambda: fx.xtext("#addMsg") == "example.com is on your keep list.", 3), fx.xtext("#addMsg"))
        fx.xjs("document.getElementById('addInput').value = arguments[0];", "not a site !!")
        fx.click('#addForm button[type="submit"]')
        check("something that is not an address is refused with a hint", wait(lambda: "not a site address" in (fx.xtext("#addMsg") or ""), 3)
              and len(fx.keep()) == 5, (fx.xtext("#addMsg"), fx.keep()))
        fx.click('.chip[data-filter="kept"]')
        rows = fx.xtexts("#siteTable tbody td.site")
        check("the Kept filter lists exactly the keep list", sorted(rows) == sorted(fx.keep()), rows)
        fx.xjs("""const s = document.querySelector('#siteTable tr[data-site="example.com"] select');
                  s.value = ''; s.dispatchEvent(new Event('change', { bubbles: true }));""")
        check("a site can be taken off the keep list in the table", wait(lambda: "example.com" not in fx.keep(), 3))
        fx.click('.chip[data-filter="all"]')
        check("the activity list shows cleans with site and count", wait(lambda: len(fx.xtexts("#logList .log-item")) >= 1, 3)
              and "basic.test" in fx.xtext("#logList") and "3 cookies" in fx.xtext("#logList"), fx.xtext("#logList")[:200])
        fx.xjs("const g = document.getElementById('grace'); g.value = '60'; g.dispatchEvent(new Event('change', { bubbles: true }));")
        check("settings: the wait can be changed", wait(lambda: fx.settings()["graceSec"] == 60, 3)
              and wait(lambda: "1 minute after you close its last tab" in fx.xtext("#statusText"), 3), fx.xtext("#statusText"))
        fx.grace(G)
        fx.click("#cleanOpenAtQuit")
        check("settings: 'clean what was open when Firefox closed' is off by default and can be switched on", wait(lambda: fx.settings()["cleanOpenAtQuit"] is True, 3))
        fx.click("#cleanOpenAtQuit")
        wait(lambda: fx.settings()["cleanOpenAtQuit"] is False, 3)
        fx.click("#clearLog")
        check("the activity list can be cleared", wait(lambda: fx.log() == [], 3) and wait(lambda: fx.shown("#logEmpty"), 3))

        # ---- a row in the dashboard, and a tab closed by the browser itself
        t = fx.open(u("www.six.test"))
        fx.open_app()
        row = '#siteTable tr[data-site="six.test"]'
        check("dashboard: an open site is shown as open, with its cookie count", wait(lambda: fx.xtext(row + " .tag") == "Open", 3)
              and fx.xtext(row + " td.num") == "3", fx.xtext(row))
        fx.click(row + ' [data-act="clean"]')
        check("dashboard: clean now for a row asks first and says the site is open",
              fx.xtext("#confirmText") == "Delete 3 cookies for six.test now? You will be signed out of it. It is open in a tab right now.", fx.xtext("#confirmText"))
        fx.click("#confirmNo")
        check("dashboard: Cancel deletes nothing", len(fx.names("six.test")) == 3)
        closed = fx.chrome_close_tabs("www.six.test")
        check("a tab closed with the browser's own close-tab is noticed", closed == 1 and wait(lambda: "six.test" in fx.pending(), 2), fx.pending())
        check("dashboard: the row shows the countdown", wait(lambda: (fx.xtext(row + " .tag") or "").startswith("Cleaning in "), 2), fx.xtext(row))
        check("and the site is cleaned after the wait", gone(fx, "six.test"))

        # ---- going through the setup again
        fx.open_app()
        fx.click("#rerunSetup")
        fx.click("#toStep2")
        ticked = fx.xjs("return [...document.querySelectorAll('#step2 li')].filter((li) => li.querySelector('input').checked).map((li) => li.dataset.site).sort();")
        check("setup again: the sites already kept are ticked", ticked == sorted(fx.keep()) and "kept.test" in ticked, (ticked, fx.keep()))
        fx.click('#step2 li[data-site="restore2.test"] input')
        fx.click("#setupFinish")
        check("setup again: unticking takes a site off the keep list, the rest keep their level",
              wait(lambda: "restore2.test" not in fx.keep(), 3) and fx.keep().get("session.test") == "session" and fx.keep().get("kept.test") == "always"
              and fx.settings()["enabled"] is True, fx.keep())

        # ---- a page that is not a website, and the thank-you card
        fx.page_get("about:blank")
        # The run so far cleaned well over 1,000 cookies (the restore-limit test alone 1,200): step back below the first milestone.
        fx.api("await browser.storage.local.set({ stats: { cookies: 999 } }); await browser.storage.local.remove('supportNudge');")
        fx.open_popup(fx.page_tab_id())
        check("popup on a page that is not a website says so and offers nothing to click",
              fx.xtext("#siteName") == "This page" and "not a website" in fx.xtext("#siteState") and not fx.shown("#keepAlways") and not fx.shown("#cleanSite"), fx.xtext("#siteState"))
        check("no thank-you card before Dustpan has been of real use", not fx.shown("#supportCard"))
        fx.api("await browser.storage.local.set({ stats: { cookies: 1000 } });")
        fx.open_popup(fx.page_tab_id())
        check("after 1,000 cleaned cookies the popup thanks once, with a Ko-fi link", wait(lambda: fx.shown("#supportCard"), 3)
              and "1,000 cookies" in fx.xtext("#supportCard") and fx.xjs("return document.querySelector('#supportCard a').href") == "https://ko-fi.com/carcer7378", fx.xtext("#supportCard"))
        fx.xjs("[...document.querySelectorAll('#supportCard button')].find((b) => b.textContent === \"Don't ask again\").click();")
        time.sleep(0.4)
        fx.open_popup(fx.page_tab_id())
        time.sleep(0.4)
        check("'Don't ask again' is final", not fx.shown("#supportCard"))

        # ---- support links
        fx.open_popup(fx.page_tab_id())
        kofi = "https://ko-fi.com/carcer7378"
        check("Ko-fi pill in the popup header", fx.xjs("const a = document.querySelector('header a.support-pill'); return a && a.href") == kofi)
        fx.open_app()
        check("Support section in the dashboard, with the Ko-fi link and 'every feature is unlocked'",
              fx.xjs("const a = document.querySelector('#support a[data-support]'); return a && a.href") == kofi
              and "Every feature is unlocked for everyone" in fx.xtext("#support"))
        check_more_addons(fx.api)

        # ---- the real toolbar button and popup
        fx.page_get(u("www.real.test"))
        where = fx.click_toolbar_button()
        got = wait(lambda: (lambda r: r if r and r.get("ready") == "1" else None)(fx.popup_read("#siteName")), 8)
        check("the real toolbar popup shows the site of the tab it was opened on", where == "nav-bar" and bool(got) and got["text"] == "real.test", (where, got))
        fx.page_get("about:blank")
    finally:
        fx.quit()


# ==================================================================== fpi

def session_fpi(unpacked):
    """privacy.firstparty.isolate: every cookie carries the visited site in firstPartyDomain."""
    fx = start(unpacked, {"privacy.firstparty.isolate": True})
    try:
        enable(fx, {"kept.test": "always"})
        tt = fx.open(u("top.test", "/embed?w=widget.tracker.test"))
        tw = fx.open(u("widget.tracker.test"))
        tk = fx.open(u("www.kept.test"))
        m = fx.open(u("mail.example.com", "/?d=example.com"))
        a = fx.open(u("accounts.example.com"))
        wait(lambda: len([c for c in fx.jar("widget.tracker.test") if c["firstPartyDomain"] == "top.test"]) == 2, 5)
        jar = fx.jar()
        check("first-party isolation is really on: every cookie names its first party",
              len(jar) >= 14 and all(c["firstPartyDomain"] for c in jar), [(c["name"], c["firstPartyDomain"]) for c in jar])
        embedded = [c for c in jar if c["domain"] == "widget.tracker.test" and c["firstPartyDomain"] == "top.test"]
        check("the embedded widget's cookies are filed under the visited site", sorted(c["name"] for c in embedded) == ["fhttp", "fjs"], embedded)
        fx.open_popup(tt)
        check("popup counts the embedded cookies with the visited site", fx.xtext("#siteName") == "top.test" and fx.xtext("#siteCount") == "3 cookies", fx.xtext("#siteCount"))

        own = sorted(json.dumps(c, sort_keys=True) for c in jar if c["firstPartyDomain"] == "tracker.test")
        want = sorted(json.dumps(c, sort_keys=True) for c in jar if c["firstPartyDomain"] == "top.test")
        t0 = time.time()
        fx.close(tt)
        time.sleep(G - 1.3)
        check("first-party isolation: nothing deleted before the wait is over", len([c for c in fx.jar() if c["firstPartyDomain"] == "top.test"]) == 3)
        ok = wait(lambda: [c for c in fx.jar() if c["firstPartyDomain"] == "top.test"] == [], G + 4, 0.2)
        check("first-party isolation: closing the site cleans everything filed under it", ok and time.time() - t0 >= G - 0.5
              and last_log(fx, "top.test")["count"] == 3, last_log(fx, "top.test"))
        check("the tracker's own first-party cookies, with its tab open, are untouched",
              sorted(json.dumps(c, sort_keys=True) for c in fx.jar() if c["firstPartyDomain"] == "tracker.test") == own and len(own) == 3)
        r = fx.send("restore", ids=[last_log(fx, "top.test")["id"]])
        check("first-party isolation: restore puts them back, HttpOnly ones included",
              sorted(json.dumps(c, sort_keys=True) for c in fx.jar() if c["firstPartyDomain"] == "top.test") == want
              and r["results"][0]["set"] == 3 and any(json.loads(c)["httpOnly"] for c in want), r)

        both = snap(fx, "example.com")
        fx.close(m)
        settle(fx)
        check("first-party isolation: subdomains are still one site", snap(fx, "example.com") == both and len(both) == 7)
        fx.close(a)
        check("first-party isolation: cleaned together when the last one closes", gone(fx, "example.com") and last_log(fx, "example.com")["count"] == 7)

        kept = snap(fx, "kept.test")
        fx.close(tk, tw)
        check("first-party isolation: the tracker is cleaned once its tab is closed",
              wait(lambda: [c for c in fx.jar() if c["firstPartyDomain"] == "tracker.test"] == [], G + 4, 0.2))
        settle(fx, 1.0)
        check("first-party isolation: a kept site is never cleaned", snap(fx, "kept.test") == kept and len(kept) == 3)
        check("first-party isolation: the cookies restored for top.test are still there (nothing cleans a restored site behind your back)",
              len([c for c in fx.jar() if c["firstPartyDomain"] == "top.test"]) == 3)
    finally:
        fx.quit()


# ================================================================ suspend

def session_suspend(unpacked):
    """Firefox stops the background page after 2 s of nothing to do. The grace delay is 6 s."""
    fx = start(unpacked, {"extensions.background.idle.timeout": 2000}, grace=6)
    try:
        enable(fx)
        t = fx.open(u("www.basic.test", "/?d=basic.test"))
        want = snap(fx, "basic.test")
        check("background page is stopped by Firefox when idle", wait(lambda: fx.bg_state() == "stopped", 15, 0.2), fx.bg_state())
        t0 = time.time()
        fx.close(t)
        p = wait(lambda: fx.pending().get("basic.test"), 3)
        check("closing the tab wakes it and the wait is written to storage", bool(p) and abs(p["due"] / 1000 - (t0 + 6)) < 1.5, p)
        asleep = wait(lambda: fx.bg_state() == "stopped", 5, 0.1)
        slept_at = time.time() - t0
        alarms = fx.api("return await browser.alarms.getAll();")
        check("the background page is stopped again during the grace delay", bool(asleep) and slept_at < 5.2 and len(fx.names("basic.test")) == 4, (asleep, slept_at))
        check("one alarm carries the wait", [a["name"] for a in alarms] == ["sweep"] and abs(alarms[0]["scheduledTime"] - p["due"]) < 100, alarms)
        ok = wait(lambda: fx.names("basic.test") == [], 10, 0.2)
        took = time.time() - t0
        check("the alarm wakes it and the site is cleaned on time, from what was stored", ok and 5.5 <= took <= 9.5, took)
        check("it is logged, and it goes back to sleep", last_log(fx, "basic.test")["count"] == 4 and wait(lambda: fx.bg_state() == "stopped", 15, 0.2))
        fx.open_popup(fx.page_tab_id())
        check("the popup still offers Restore after the background page was stopped",
              fx.shown('#recentList .log-item[data-site="basic.test"] [data-restore="can"]'))
        wait(lambda: fx.bg_state() == "stopped", 15, 0.2)
        fx.click('#recentList .log-item[data-site="basic.test"] [data-restore="can"]')
        check("restore works from the stopped state: the cookies were waiting in storage.session",
              wait(lambda: snap(fx, "basic.test") == want, 6), fx.names("basic.test"))

        t = fx.open(u("www.grace.test"))
        fx.close(t)
        wait(lambda: "grace.test" in fx.pending(), 3)
        check("stopped during the second wait", wait(lambda: fx.bg_state() == "stopped", 5, 0.1), fx.bg_state())
        t = fx.open(u("www.grace.test"))
        check("reopening the site wakes it and cancels the wait", wait(lambda: "grace.test" not in fx.pending(), 3), fx.pending())
        time.sleep(8)
        check("reopened while the page was stopped: nothing deleted", len(fx.names("grace.test")) == 3 and fx.log(site="grace.test") == [])

        t2 = fx.open(u("www.nav-a.test"))
        fx.nav(t2, u("www.nav-b.test"))
        wait(lambda: fx.bg_state() == "stopped", 15, 0.2)
        time.sleep(1)
        visited = fx.sess("visited").get("visited", {})
        check("what a tab has visited survives the stop (storage.session)", sorted(visited.get(str(t2), [])) == ["nav-a.test", "nav-b.test"], visited)
        fx.close(t)
        wait(lambda: fx.names("grace.test") == [], 12, 0.2)
        check("after waking up for another tab, the site left behind in an open tab is still held", len(fx.names("nav-a.test")) == 3 and "nav-a.test" not in fx.pending())
    finally:
        fx.quit()


# ================================================================= access

def session_access(unpacked):
    """The user switches "Access your data for all websites" off in about:addons, later on again."""
    fx = start(unpacked)
    try:
        enable(fx)
        t1 = fx.open(u("www.basic.test"))
        t2 = fx.open(u("www.grace.test"))
        fx.close(t1)
        wait(lambda: "basic.test" in fx.pending(), 2)
        check("before: access is there and a site is waiting", fx.access() is True and "basic.test" in fx.pending())
        fx.revoke_access()
        check("access switched off: Dustpan notices at once", wait(lambda: fx.access() is False, 3))
        check("whatever was waiting is dropped", wait(lambda: fx.pending() == {}, 3), fx.pending())
        check("the toolbar button shows a warning", wait(lambda: fx.badge() == "!", 3), fx.badge())
        fx.close(t2)
        time.sleep(0.6)
        check("closing a site now schedules nothing", fx.pending() == {})
        settle(fx)
        fx.grant_access()
        wait(lambda: fx.access() is True, 3)
        check("nothing was deleted while access was off", len(fx.names("basic.test")) == 3 and len(fx.names("grace.test")) == 3 and fx.log() == [])
        fx.revoke_access()
        wait(lambda: fx.access() is False, 3)

        fx.open_popup(fx.page_tab_id())
        check("popup says cleaning is paused, and why", fx.xtext("#statusTitle") == "Paused: no access to your sites"
              and "Site access was switched off in this add-on's permissions" in fx.xtext("#statusText")
              and fx.xjs("return document.getElementById('status').dataset.state") == "paused", fx.xtext("#statusText"))
        check("popup offers to fix it and disables the clean buttons", fx.xtext("#statusBtn") == "Give access back"
              and fx.xjs("return document.getElementById('cleanAll').disabled") is True)
        r = fx.send("clean:all", sites=["basic.test"])
        check("clean now refuses without access", r == {"ok": False, "reason": "access"}, r)
        fx.open_app()
        check("dashboard says the same", fx.xtext("#statusTitle") == "Paused: no access to your sites" and "Permissions" in fx.xtext("#statusText"))
        fx.click("#statusBtn")
        check("'Give access back' asks Firefox and access returns", wait(lambda: fx.access() is True, 5))
        check("status is back to on, warning gone", wait(lambda: fx.xtext("#statusTitle") == "Automatic cleaning is on", 5) and wait(lambda: fx.badge() == "", 3), fx.badge())
        settle(fx)
        check("getting access back cleans nothing by itself", len(fx.names("basic.test")) == 3 and len(fx.names("grace.test")) == 3 and fx.pending() == {})
        t = fx.open(u("www.basic.test"))
        fx.close(t)
        check("with access back, closing a site cleans it again", gone(fx, "basic.test") and len(fx.names("grace.test")) == 3)
    finally:
        fx.quit()


# ================================================================ restart

def restart(fx, close=()):
    """A browser restart as the add-on sees it. Tabs named in close go away while it is stopped."""
    fx.addon_shutdown()
    for needle in close:
        fx.chrome_close_tabs(needle)
    reason = fx.addon_startup()
    return reason, time.time()


def session_restart(unpacked):
    """Stops the add-on and starts it with Firefox's APP_STARTUP reason, which is what a browser restart
    looks like from inside: storage.session is empty, storage.local is as it was, runtime.onStartup fires.
    (A temporary add-on does not survive a real restart, so a real one can not be tested this way.)"""
    fx = start(unpacked)
    try:
        enable(fx, {"kept.test": "always", "session.test": "session", "restore2.test": "session"})
        for host in ["www.kept.test", "www.session.test", "www.basic.test"]:
            fx.close(fx.open(u(host)))
        gone(fx, "basic.test")
        check("while Firefox is open, 'keep until Firefox closes' keeps the site", len(fx.names("session.test")) == 3 and len(fx.names("kept.test")) == 3)
        t_back = fx.open(u("www.restore2.test"))     # kept for the session, and its tab comes back after the restart
        t_stay = fx.open(u("www.one.test"))          # not kept, its tab comes back
        fx.open(u("www.two.test"))                   # not kept, open at the end, does not come back
        w3, _ = fx.new_window(u("www.three.test"))   # its window is closed a moment before the end
        t_closed = fx.open(u("www.grace.test"))      # its tab is closed a moment before the end
        fx.close(t_closed)
        fx.close_window(w3)
        wait(lambda: {"grace.test", "three.test"} <= set(fx.pending()), 2)
        check("before the restart: one site waits after its tab closed, one after its window closed",
              fx.pending()["grace.test"]["reason"] == "closed" and fx.pending()["three.test"]["reason"] == "window", fx.pending())
        fx.api("await browser.storage.session.set({ marker: 1 });")
        reason, t0 = restart(fx, close=["www.two.test"])
        check("the add-on was started the way a browser start does it", reason == "APP_STARTUP" and fx.sess("marker") == {}, reason)
        check("its settings and keep list survived", fx.settings()["enabled"] is True and fx.keep()["session.test"] == "session")
        p = fx.pending()
        check("after the start: the session-kept site and the closed tab's site wait for a minute",
              {"session.test", "grace.test"} <= set(p) and all(55 <= x["due"] / 1000 - t0 <= 65 for x in p.values()), p)
        check("a site whose window closed at the very end is not cleaned by default (it may just have been open when Firefox quit)", "three.test" not in p, p)
        check("the session-kept site whose tab is back, the kept site and the open-at-quit site are not waiting",
              not {"restore2.test", "kept.test", "two.test", "one.test"} & set(p), p)
        fx.open_popup(fx.page_tab_id())
        check("the popup shows what will be cleaned after the start, with Keep and Not now",
              sorted(fx.xtexts("#pendingList .site")) == ["grace.test", "session.test"] and fx.shown('#pendingList [data-act="skip"]'))
        time.sleep(max(0, t0 + 30 - time.time()))
        check("half a minute after the start nothing has been deleted",
              len(fx.names("session.test")) == 3 and len(fx.names("grace.test")) == 3)
        ok = wait(lambda: fx.names("session.test") == [] and fx.names("grace.test") == [], 45, 0.5)
        took = time.time() - t0
        check("about a minute after the start: 'keep until Firefox closes' has ended and that site is cleaned", ok and 55 <= took <= 70, took)
        check("it is logged as cleaned at the start", last_log(fx, "session.test")["kind"] == "start" and last_log(fx, "session.test")["count"] == 3)
        check("the site stays on the keep list at that level for the next session", fx.keep()["session.test"] == "session")
        check("keep always survives the restart untouched", len(fx.names("kept.test")) == 3)
        check("the session-kept site whose tab came back is untouched", len(fx.names("restore2.test")) == 3)
        check("default: sites that were open when Firefox closed are left alone, tab back or not",
              len(fx.names("one.test")) == 3 and len(fx.names("two.test")) == 3 and len(fx.names("three.test")) == 3)
        fx.close(t_back)
        settle(fx)
        check("the session-kept site is kept again when its restored tab closes", len(fx.names("restore2.test")) == 3)

        # second restart, with "clean what was still open" switched on
        fx.send("settings:set", patch={"cleanOpenAtQuit": True})
        fx.open(u("www.four.test"))                  # open at the end, does not come back
        w5, _ = fx.new_window(u("www.five.test"))    # window closed at the very end
        fx.close_window(w5)
        wait(lambda: "five.test" in fx.pending(), 2)
        reason, t0 = restart(fx, close=["www.four.test"])
        p = fx.pending()
        check("option on: after the start the sites that were open at the end wait too",
              {"four.test", "five.test", "session.test", "restore2.test"} <= set(p) and p["four.test"]["reason"] == "quit"
              and "one.test" not in p and "kept.test" not in p, p)
        fx.send("pending:cancel", site="five.test")
        ok = wait(lambda: fx.names("four.test") == [], 75, 0.5)
        took = time.time() - t0
        check("option on: a site that was open when Firefox closed and did not come back is cleaned after a minute", ok and 55 <= took <= 70, took)
        check("option on: the site whose tab came back is untouched", len(fx.names("one.test")) == 3 and fx.tab_urls().count(u("www.one.test")) == 1)
        check("'Not now' on the waiting list holds after a start too", len(fx.names("five.test")) == 3)
        check("the earlier leftovers were never on the list and are untouched", len(fx.names("two.test")) == 3 and len(fx.names("three.test")) == 3)
        fx.close(t_stay)
        check("and normal cleaning carries on after the restart", gone(fx, "one.test"))
    finally:
        fx.quit()


# ================================================================ private

def session_private(unpacked):
    """Dustpan is not allowed in private windows at all ("incognito": "not_allowed")."""
    fx = start(unpacked)
    try:
        enable(fx)
        info = fx.open_private_window(u("www.priv.test"))
        check("a private window is open on a site", info.get("private") is True and "www.priv.test" in info.get("url", ""), info)
        priv = wait(lambda: fx.private_cookies("priv.test"), 5)
        check("the site set cookies in the private window", priv == ["js", "sess", "sid_ZQXNAME"], priv)
        check("Dustpan can not be allowed in private windows", fx.api("return await browser.extension.isAllowedIncognitoAccess();") is False)
        check("it sees no private tab", not any("priv.test" in (x or "") for x in fx.tab_urls()), fx.tab_urls())
        r = fx.api("try { return (await browser.cookies.getAll({ storeId: 'firefox-private', firstPartyDomain: null, partitionKey: {} })).length; } catch (e) { return String(e); }")
        check("and Firefox refuses it the private cookie store", isinstance(r, str) and "private" in r, r)
        fx.open_private_window(u("www.privonly.test"))
        t = fx.open(u("www.priv.test"))
        check("the same site in a normal tab has its own cookies", len(fx.names("priv.test")) == 3)
        fx.close(t)
        check("closing the normal tab cleans the normal cookies", gone(fx, "priv.test") and last_log(fx, "priv.test")["count"] == 3)
        check("the private window's cookies are untouched", fx.private_cookies("priv.test") == priv and fx.private_cookies("privonly.test") == priv)
        fx.send("clean:all", sites=["priv.test", "privonly.test"])
        check("clean everything does not reach them either", fx.private_cookies("priv.test") == priv and fx.private_cookies("privonly.test") == priv)
        dump = json.dumps(fx.store(None)) + json.dumps(fx.sess(None))
        check("a site that was only open in a private window appears nowhere in Dustpan's storage", "privonly" not in dump, dump[:300])
        fx.close_private_windows()
    finally:
        fx.quit()


# ================================================================ control

def session_control(unpacked):
    """Dustpan with the Public Suffix List swapped for "the last two labels are the site"."""
    broken = Path(tempfile.mkdtemp(prefix="dustpan-naive-"))
    shutil.copytree(unpacked, broken, dirs_exist_ok=True)
    psl = broken / "shared" / "psl.js"
    src = psl.read_text(encoding="utf-8")
    marker = "export function siteOfHost(host) {\n"
    assert src.count(marker) == 1
    psl.write_text(src.replace(marker, marker + "  { const g = normalizeHost(host); if (g.includes('.') && !isIp(g)) return g.split('.').slice(-2).join('.'); }\n"),
                   encoding="utf-8")
    fx = start(broken)
    try:
        enable(fx)
        n = fx.open(u("news.other.co.uk"))
        s = fx.open(u("shop.example.co.uk"))
        fx.open_popup(s)
        name = fx.xtext("#siteName")
        fx.close(s)
        settle(fx)
        check("control: a guess based on dots calls both sites 'co.uk' and never cleans the closed one while the other is open",
              name == "co.uk" and len(fx.names("example.co.uk")) == 3 and fx.log() == [], (name, fx.names("example.co.uk")))
        fx.keep_set("co.uk", "always")
        fx.close(n)
        settle(fx)
        check("control: with that guess, keeping one of them would keep every site under co.uk",
              len(fx.names("example.co.uk")) == 3 and len(fx.names("other.co.uk")) == 3)
        al = fx.open(u("alice.github.io"))
        bo = fx.open(u("bob.github.io"))
        fx.close(al)
        settle(fx)
        check("control: and alice.github.io is not cleaned while bob.github.io is open", len(fx.names("alice.github.io")) == 3)
        fx.close(bo)
    finally:
        fx.quit()
        shutil.rmtree(broken, ignore_errors=True)


SESSIONS = {"main": session_main, "fpi": session_fpi, "suspend": session_suspend, "access": session_access,
            "restart": session_restart, "private": session_private, "control": session_control}


def check_more_addons(api):
    """Rate pill and "More free add-ons" card on the settings page that is open now.
    The expected list comes from the shared file, so a new round only flips `live` flags."""
    more = wait(lambda: api("""
      const items = [...document.querySelectorAll('#moreAddons .more-item a')];
      if (!items.length) return null;
      const rate = document.querySelector('[data-rate]');
      const all = document.querySelector('[data-more-all]');
      const m = await import('/shared/more-addons.js');
      const me = browser.runtime.id;
      const self = m.ADDONS.find((a) => a.id === me);
      const fake = [{id: 'a', live: true, android: false}, {id: 'b', live: true, android: true},
                    {id: 'self', live: true, android: true}, {id: 'c', live: false, android: true}];
      return {
        names: items.map((a) => a.querySelector('.more-name').textContent),
        expected: m.ADDONS.filter((a) => a.live && a.id !== me).map((a) => a.name),
        left_out: m.ADDONS.filter((a) => !a.live || a.id === me).map((a) => a.name),
        self_slug: self ? self.slug : null, self_live: self ? self.live : null,
        hrefs: items.map((a) => a.href),
        newTab: items.every((a) => a.target === '_blank' && a.rel === 'noopener'),
        rate: rate.hidden ? null : rate.href, rateNewTab: rate.target === '_blank',
        all: all.href,
        androidPick: m.moreAddons('self', 'android', fake).map((x) => x.id),
        desktopPick: m.moreAddons('self', 'win', fake).map((x) => x.id),
      };
    """))
    more = more if isinstance(more, dict) else {}
    check("this add-on is marked live in the shared add-on list", more.get("self_live") is True, more.get("self_slug"))
    check("settings page lists every other live add-on, in order",
          bool(more.get("names")) and more.get("names") == more.get("expected"), (more.get("names"), more.get("expected")))
    check("it leaves out itself and add-ons still in review",
          bool(more.get("names")) and not set(more["names"]) & set(more.get("left_out") or []), more.get("left_out"))
    check("each listed add-on links to its AMO page in a new tab",
          bool(more.get("hrefs")) and all(h.startswith("https://addons.mozilla.org/firefox/addon/") for h in more["hrefs"])
          and more.get("newTab") is True, more.get("hrefs"))
    check("rate link opens this add-on's own AMO page",
          bool(more.get("self_slug")) and more.get("rate") == "https://addons.mozilla.org/firefox/addon/%s/" % more.get("self_slug")
          and more.get("rateNewTab") is True, more.get("rate"))
    check("see-all link opens the author's AMO page",
          more.get("all") == "https://addons.mozilla.org/firefox/user/20013808/", more.get("all"))
    check("list skips itself and unreleased add-ons, and desktop-only ones on Android",
          more.get("desktopPick") == ["a", "b"] and more.get("androidPick") == ["b"],
          (more.get("desktopPick"), more.get("androidPick")))


def main():
    names = [a for a in sys.argv[1:] if a in SESSIONS] or list(SESSIONS)
    unpacked = Path(tempfile.mkdtemp(prefix="dustpan-e2e-"))
    with zipfile.ZipFile(latest_zip()) as z:
        z.extractall(unpacked)
    httpd = server.start(PORT)
    try:
        for name in names:
            print(f"\n=== {name}", flush=True)
            n = len(results)
            try:
                SESSIONS[name](unpacked)
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                check(f"{name}: session ran to the end", False, repr(e)[:300])
            print(f"--- {name}: {sum(1 for _, ok in results[n:] if ok)}/{len(results) - n}", flush=True)
    finally:
        httpd.shutdown()
        shutil.rmtree(unpacked, ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    for n in failed:
        print("  FAILED:", n.encode("ascii", "replace").decode())
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
