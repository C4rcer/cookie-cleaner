"""Shared plumbing for Dustpan's real-Firefox tests (Selenium + geckodriver).

One headless, muted Firefox with a throwaway profile and the built add-on
installed from the extracted zip. Window 1 is for web pages the test drives
itself; window 2 sits on one of the add-on's own pages, which is where the
WebExtension API is called from (opening and closing tabs, reading cookies and
storage) and where the popup and the dashboard are shown.

geckodriver runs with --allow-system-access so the tests can do what only the
browser itself can: look at the state of the background page, switch site
access off the way about:addons does, open a private window, and stop and
start the add-on the way a browser restart does.
"""
import json
import os
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "dustpan-cookie-cleaner@c4rcer"
WIDGET_ID = "dustpan-cookie-cleaner_c4rcer-browser-action"
UUID = "3c9a4e52-1f6b-4d7a-8e21-5b0c9d7a6f14"
EXT = f"moz-extension://{UUID}"
FIREFOX = r"C:\Program Files\Mozilla Firefox\firefox.exe"
STORES = ["firefox-default", "firefox-container-1", "firefox-container-2", "firefox-container-3"]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    line = ("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not ok else "")
    print(line.encode("ascii", "replace").decode(), flush=True)  # Windows consoles choke on some characters
    return bool(ok)


def wait(fn, timeout=8.0, step=0.1):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except Exception:  # noqa: BLE001
            last = None
        time.sleep(step)
    return last


def latest_zip():
    zips = sorted((ROOT / "dist").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        sys.exit("build first: python tools/release.py build")
    return zips[-1]


class Fx:
    def __init__(self, unpacked, hosts, prefs=None):
        os.environ.setdefault("SE_AVOID_STATS", "true")
        opts = Options()
        opts.binary_location = FIREFOX
        opts.add_argument("-headless")
        opts.set_preference("media.volume_scale", "0.0")
        opts.set_preference("extensions.webextensions.uuids", json.dumps({ADDON_ID: UUID}))
        opts.set_preference("network.dns.localDomains", ",".join(hosts))
        opts.set_preference("privacy.userContext.enabled", True)  # container tabs
        opts.set_preference("security.notification_enable_delay", 0)
        # Asking for site access back is granted without the prompt (it still takes a real click to ask).
        opts.set_preference("extensions.webextOptionalPermissionPrompts", False)
        opts.set_preference("browser.tabs.warnOnClose", False)
        opts.set_preference("browser.warnOnQuit", False)
        for k, v in (prefs or {}).items():
            opts.set_preference(k, v)
        self.d = webdriver.Firefox(options=opts, service=Service(service_args=["--allow-system-access"]))
        self.d.set_script_timeout(120)
        self.d.set_window_size(1280, 900)
        self.d.execute("INSTALL_ADDON", {"path": str(unpacked), "temporary": True})
        time.sleep(1.2)
        self.handles_after_install = len(self.d.window_handles)
        self.page = self.d.current_window_handle
        self.d.switch_to.new_window("window")
        self.ext = self.d.current_window_handle
        self.d.set_window_size(1100, 900)
        self.d.get(f"{EXT}/app/app.html")
        self.ready()

    def quit(self):
        self.d.quit()

    # ---- windows
    def to_page(self):
        if self.d.current_window_handle != self.page:
            self.d.switch_to.window(self.page)

    def to_ext(self):
        if self.d.current_window_handle != self.ext:
            self.d.switch_to.window(self.ext)

    def ready(self):
        return wait(lambda: self.d.execute_script("return document.body && document.body.dataset.ready === '1'"), 10)

    def page_get(self, url):
        self.to_page()
        self.d.get(url)

    def js(self, script, *args):
        self.to_page()
        return self.d.execute_script(script, *args)

    def xjs(self, script, *args):
        self.to_ext()
        return self.d.execute_script(script, *args)

    def api(self, code, *args):
        """Run async code with the WebExtension API, on the add-on's own page."""
        self.to_ext()
        return self.d.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            f"(async () => {{ {code} }})().then(done, (e) => done('ERR ' + e));", *args)

    def send(self, type_, **data):
        return self.api("return await browser.runtime.sendMessage(arguments[0]);", {"type": type_, **data})

    def chrome(self, script, *args):
        """Privileged code in the browser window itself."""
        self.to_ext()
        with self.d.context("chrome"):
            return self.d.execute_script(script, *args)

    def chrome_async(self, body, *args):
        self.to_ext()
        with self.d.context("chrome"):
            return self.d.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                f"(async () => {{ {body} }})().then(done, (e) => done('ERR ' + e + ' ' + (e && e.stack)));", *args)

    # ---- add-on state
    def store(self, keys=None):
        return self.api("return await browser.storage.local.get(arguments[0]);", keys)

    def sess(self, keys=None):
        return self.api("return await browser.storage.session.get(arguments[0]);", keys)

    def settings(self):
        return self.store("settings").get("settings") or {}

    def keep(self):
        return self.store("keep").get("keep") or {}

    def pending(self):
        return self.store("pending").get("pending") or {}

    def log(self, kind=None, site=None):
        out = self.store("log").get("log") or []
        if kind:
            out = [e for e in out if e["kind"] == kind]
        if site:
            out = [e for e in out if e["site"] == site]
        return out

    def grace(self, sec):
        return self.send("settings:set", patch={"graceSec": sec})

    def keep_set(self, site, level):
        return self.send("keep:set", site=site, level=level)

    def state(self, tab=None):
        return self.send("state", tabId=tab)

    def bg_state(self):
        return self.chrome("return WebExtensionPolicy.getByID(arguments[0]).extension.backgroundState;", ADDON_ID)

    def badge(self, tab=None):
        return self.api("return await browser.action.getBadgeText(arguments[0] == null ? {} : { tabId: arguments[0] });", tab)

    def access(self):
        return self.api("return await browser.permissions.contains({ origins: ['*://*/*'] });")

    # ---- cookies
    def jar(self, host=None, store=None, top=None):
        """Every cookie in the known stores. host: the cookie's own domain is that host or below it.
        top: only cookies partitioned under that top-level site (True: any partition, False: none)."""
        got = self.api("""
          const out = [];
          for (const storeId of arguments[0]) {
            try { out.push(...await browser.cookies.getAll({ storeId, firstPartyDomain: null, partitionKey: {} })); } catch (e) {}
          }
          return out;""", STORES)
        out = []
        for c in got:
            dom = c["domain"].lstrip(".")
            if host is not None and not (dom == host or dom.endswith("." + host)):
                continue
            if store is not None and c["storeId"] != store:
                continue
            pk = (c.get("partitionKey") or {}).get("topLevelSite")
            if top is True and not pk:
                continue
            if top is False and pk:
                continue
            if isinstance(top, str) and (not pk or top not in pk):
                continue
            out.append(c)
        return out

    def names(self, host, **kw):
        return sorted(c["name"] for c in self.jar(host, **kw))

    def set_cookie(self, **details):
        return self.api("return await browser.cookies.set(arguments[0]);", details)

    # ---- tabs, through the same API a user's actions end up in
    def open(self, url, wait_load=True, **opts):
        tab = self.api("return (await browser.tabs.create(arguments[0])).id;", {"url": url, "active": False, **opts})
        if wait_load:
            self.loaded(tab)
        return tab

    def loaded(self, tab, timeout=15):
        return wait(lambda: self.api(
            "const t = await browser.tabs.get(arguments[0]); return t.status === 'complete' && t.url !== 'about:blank';", tab), timeout, 0.15)

    def nav(self, tab, url):
        self.api("await browser.tabs.update(arguments[0], { url: arguments[1] });", tab, url)
        wait(lambda: self.api("const t = await browser.tabs.get(arguments[0]); return t.status === 'complete' && t.url === arguments[1];", tab, url), 15, 0.15)

    def close(self, *tabs):
        self.api("await browser.tabs.remove(arguments[0]);", list(tabs))

    def tab_urls(self):
        return self.api("return (await browser.tabs.query({})).map((t) => t.url);")

    def page_tab_id(self):
        return self.api("""
          const me = await browser.tabs.getCurrent();
          const t = (await browser.tabs.query({ active: true })).find((x) => x.windowId !== me.windowId);
          return t ? t.id : null;""")

    def new_window(self, url, **opts):
        """A second normal browser window with one tab. Returns (windowId, tabId)."""
        got = self.api("const w = await browser.windows.create(arguments[0]); return [w.id, w.tabs[0].id];", {"url": url, **opts})
        self.loaded(got[1])
        return got

    def close_window(self, window_id):
        self.api("await browser.windows.remove(arguments[0]);", window_id)

    # ---- the add-on's pages, in window 2
    def open_popup(self, tab):
        self.to_ext()
        self.d.get(f"{EXT}/popup/popup.html?tab={tab}")
        self.ready()

    def open_app(self, hash_=""):
        self.to_ext()
        self.d.get("about:blank")
        self.d.get(f"{EXT}/app/app.html" + hash_)
        self.ready()

    def click(self, sel):
        self.to_ext()
        self.d.find_element(By.CSS_SELECTOR, sel).click()

    def xtext(self, sel):
        return self.xjs("const e = document.querySelector(arguments[0]); return e ? e.textContent.trim() : null;", sel)

    def xtexts(self, sel):
        return self.xjs("return [...document.querySelectorAll(arguments[0])].map((e) => e.textContent.trim());", sel)

    def shown(self, sel):
        return self.xjs("""const e = document.querySelector(arguments[0]);
          return !!e && !e.hidden && !e.closest('[hidden]') && e.getClientRects().length > 0;""", sel)

    def body_text(self):
        return self.xjs("return document.body.innerText;")

    # ---- the browser's own UI and internals
    def click_toolbar_button(self):
        self.to_page()
        with self.d.context("chrome"):
            return self.d.execute_script("""
              const item = document.getElementById(arguments[0]);
              if (!item) return "no toolbar item";
              const where = item.closest("#nav-bar") ? "nav-bar" : (item.closest("panel, toolbar") || {}).id;
              (item.querySelector(".unified-extensions-item-action-button") || item).click();
              return where;
            """, WIDGET_ID)

    def popup_read(self, sel):
        """Read an element inside the real toolbar popup."""
        self.to_page()
        with self.d.context("chrome"):
            return self.d.execute_async_script("""
              const [sel, done] = arguments;
              const b = document.querySelector("browser.webextension-popup-browser");
              if (!b) { done(null); return; }
              const mm = b.messageManager;
              const name = "dustpan-test:" + Math.random().toString(36).slice(2);
              const on = (m) => { mm.removeMessageListener(name, on); done(m.data); };
              mm.addMessageListener(name, on);
              mm.loadFrameScript("data:," + encodeURIComponent(
                "(() => { const e = content.document.querySelector(" + JSON.stringify(sel) + ");" +
                " sendAsyncMessage(" + JSON.stringify(name) + ", e ? { text: e.textContent.trim(), ready: content.document.body.dataset.ready || null } : null); })();"), false);
            """, sel)

    def revoke_access(self):
        """What the "Access your data for all websites" switch in about:addons does when it is turned off."""
        return self.chrome_async("""
          const { ExtensionPermissions } = ChromeUtils.importESModule("resource://gre/modules/ExtensionPermissions.sys.mjs");
          const ext = WebExtensionPolicy.getByID(arguments[0]).extension;
          await ExtensionPermissions.remove(arguments[0], { permissions: [], origins: ["*://*/*"] }, ext);
          return "ok";""", ADDON_ID)

    def grant_access(self):
        return self.chrome_async("""
          const { ExtensionPermissions } = ChromeUtils.importESModule("resource://gre/modules/ExtensionPermissions.sys.mjs");
          const ext = WebExtensionPolicy.getByID(arguments[0]).extension;
          await ExtensionPermissions.add(arguments[0], { permissions: [], origins: ["*://*/*"] }, ext);
          return "ok";""", ADDON_ID)

    def addon_shutdown(self):
        """First half of a browser restart as the add-on sees it: it is stopped and loses storage.session."""
        self.to_ext()
        self.d.get("about:blank")  # the add-on's own tab would be closed with it
        return self.chrome_async("""
          const { XPIInternal } = ChromeUtils.importESModule("resource://gre/modules/addons/XPIProvider.sys.mjs");
          const scope = XPIInternal.BootstrapScope.get(XPIInternal.XPIStates.findAddon(arguments[0]));
          await scope.shutdown(XPIInternal.BOOTSTRAP_REASONS.ADDON_DISABLE);
          return "ok";""", ADDON_ID)

    def addon_startup(self):
        """Second half: started again with Firefox's "the browser is starting" reason, which fires runtime.onStartup."""
        out = self.chrome_async("""
          const { XPIInternal } = ChromeUtils.importESModule("resource://gre/modules/addons/XPIProvider.sys.mjs");
          const scope = XPIInternal.BootstrapScope.get(XPIInternal.XPIStates.findAddon(arguments[0]));
          await scope.startup(XPIInternal.BOOTSTRAP_REASONS.APP_STARTUP);
          return WebExtensionPolicy.getByID(arguments[0]).extension.startupReason;""", ADDON_ID)
        time.sleep(1.0)
        self.d.get(f"{EXT}/app/app.html")
        self.ready()
        return out

    def chrome_close_tabs(self, needle):
        """Close tabs whose address contains needle, from the browser itself (works while the add-on is stopped)."""
        return self.chrome("""
          let n = 0;
          for (const win of Services.wm.getEnumerator("navigator:browser")) {
            for (const tab of [...win.gBrowser.tabs]) {
              if (tab.linkedBrowser.currentURI.spec.includes(arguments[0])) { win.gBrowser.removeTab(tab); n++; }
            }
          }
          return n;""", needle)

    def open_private_window(self, url):
        return self.chrome_async("""
          const win = OpenBrowserWindow({ private: true });
          await new Promise((r) => win.addEventListener("load", r, { once: true }));
          await new Promise((r) => win.setTimeout(r, 800));
          const b = win.gBrowser.selectedBrowser;
          const loaded = new Promise((r) => {
            const l = { onStateChange(wp, req, flags) { if ((flags & 0x10) && (flags & 0x40000) && wp.isTopLevel) { b.removeProgressListener(l); r(); } },
                        QueryInterface: ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"]) };
            b.addProgressListener(l);
          });
          win.gBrowser.loadURI(Services.io.newURI(arguments[0]), { triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal() });
          await Promise.race([loaded, new Promise((r) => win.setTimeout(r, 8000))]);
          await new Promise((r) => win.setTimeout(r, 500));
          return { private: PrivateBrowsingUtils.isWindowPrivate(win), url: b.currentURI.spec };""", url)

    def private_cookies(self, host):
        """Names of the private-window cookies for a host, read by the browser itself."""
        return self.chrome("""
          const out = [];
          for (const c of Services.cookies.getCookiesWithOriginAttributes(JSON.stringify({ privateBrowsingId: 1 }))) {
            if (c.host === arguments[0] || c.host.endsWith("." + arguments[0])) out.push(c.name);
          }
          return out.sort();""", host)

    def close_private_windows(self):
        return self.chrome("""
          let n = 0;
          for (const win of Services.wm.getEnumerator("navigator:browser")) {
            if (PrivateBrowsingUtils.isWindowPrivate(win)) { win.close(); n++; }
          }
          return n;""")
