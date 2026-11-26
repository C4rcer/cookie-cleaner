"""Capture the AMO listing screenshots (1280x800) of Dustpan in a real Firefox.

  python tools/release.py build
  python tests/screenshots.py          (needs selenium + pillow)

Writes store-assets/screenshots/{1-popup,2-setup,3-sites}.png. The sites are
made up (tests/demo/*.html served by tests/server.py under .example host
names, which set a few cookies each); nothing here ships in the add-on. The
cookies, the setup, the cleans and the restore entries are made the real way;
only the times in the activity list are moved back afterwards so it does not
read "just now" everywhere. Throwaway headless profile, muted.
"""
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from selenium.webdriver.common.by import By

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402
from harness import ROOT, Fx, latest_zip, wait  # noqa: E402

PORT = 8976
OUT = ROOT / "store-assets" / "screenshots"
W, H = 1280, 800
# 1.25 device pixels per CSS pixel: a 1024x640 CSS viewport is exactly 1280x800
# (Firefox only does scales where 60 / scale is a whole number).
DPR = 1.25
MIN = 60000

GAZETTE = "www.harbourgazette.example"
SITES = {  # host: cookies it sets
    GAZETTE: 9,
    "mail.harbourpost.example": 14,
    "online.northbank.example": 7,
    "www.tidetables.example": 4,
    "forum.sailors.example": 11,
    "www.ferrytickets.example": 12,
    "www.recipebox.example": 8,
    "video.streamly.example": 23,
    "shop.harbourshop.example": 16,
    "www.weatherdesk.example": 5,
}
# Open while the setup is shown. tidetables is opened after it; ferrytickets and recipebox are first
# visited after it too (they are the cleans in the activity list), so the setup fits on one screen.
OPEN = [GAZETTE, "mail.harbourpost.example", "forum.sailors.example"]
LATER = ["www.tidetables.example", "www.ferrytickets.example", "www.recipebox.example"]


def scroll_to(fx, sel, gap):
    """Scroll so that sel sits gap CSS px below the top, on a whole device pixel (no sliver above the sticky header)."""
    fx.xjs("""const y = document.querySelector(arguments[0]).getBoundingClientRect().top + scrollY - arguments[1];
              window.scrollTo(0, Math.round(y / 4) * 4);""", sel, gap)


def u(host):
    path = "/demo/news.html" if host == GAZETTE else "/demo/site.html"
    return f"http://{host}:{PORT}{path}?n={SITES[host]}"


def fit(img):
    canvas = Image.new("RGB", (W, H), (246, 243, 238))
    canvas.paste(img.convert("RGB").crop((0, 0, min(W, img.width), min(H, img.height))), (0, 0))
    return canvas


def card(img, radius=12, scale=1.0):
    """Rounded corners and a soft drop shadow around a capture."""
    img = img.convert("RGBA")
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    pad = 40
    out = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    sm = Image.new("L", out.size, 0)
    ImageDraw.Draw(sm).rounded_rectangle((pad, pad + 8, pad + img.width, pad + img.height + 8), radius, fill=130)
    out.putalpha(sm.filter(ImageFilter.GaussianBlur(18)))
    out.paste(img, (pad, pad), mask)
    return out, pad


def set_viewport(fx, cw, ch):
    """Grow the current window until the page area is exactly cw x ch CSS pixels."""
    outer = [cw + 16, ch + 100]
    inner = None
    for _ in range(8):
        fx.d.set_window_size(*outer)
        time.sleep(0.3)
        inner = fx.d.execute_script("return [innerWidth, innerHeight]")
        if inner == [cw, ch]:
            break
        outer = [outer[0] + cw - inner[0], outer[1] + ch - inner[1]]
    return inner


def main():
    unpacked = Path(tempfile.mkdtemp(prefix="dustpan-shots-"))
    with zipfile.ZipFile(latest_zip()) as z:
        z.extractall(unpacked)
    httpd = server.start(PORT)
    OUT.mkdir(parents=True, exist_ok=True)
    fx = Fx(unpacked, list(SITES), prefs={
        "layout.css.devPixelsPerPx": str(DPR),
        "ui.systemUsesDarkTheme": 0,
        "layout.css.prefers-color-scheme.content-override": 1,  # light
    })
    try:
        cw, ch = round(W / DPR), round(H / DPR)
        fx.to_page()
        print("page viewport:", set_viewport(fx, cw, ch))
        fx.page_get(u(GAZETTE))
        gazette = fx.page_tab_id()

        # ---- every site sets its cookies; the ones not in OPEN are closed again (cleaning is off: preview only)
        fx.grace(1)
        tabs = {h: fx.open(u(h)) for h in SITES if h != GAZETTE and h not in LATER}
        fx.close(*[t for h, t in tabs.items() if h not in OPEN])
        time.sleep(3)
        print("cookies:", len(fx.jar()))

        # ---- 2: the setup, step 2, with two sites ticked
        fx.to_ext()
        print("app viewport:", set_viewport(fx, cw, ch))
        fx.open_app("#setup")
        fx.click("#toStep2")
        for site in ["harbourpost.example", "northbank.example"]:
            fx.click(f'#step2 li[data-site="{site}"] input')
        scroll_to(fx, "#step2", 68)
        time.sleep(0.6)
        fx.d.save_screenshot(str(OUT / "2-setup.png"))
        fit(Image.open(OUT / "2-setup.png")).save(OUT / "2-setup.png")
        fx.click("#setupFinish")
        wait(lambda: fx.settings().get("enabled") is True, 5)
        tabs["www.tidetables.example"] = fx.open(u("www.tidetables.example"))

        # ---- real cleans for the activity list, then one site waiting
        fx.send("log:clear")
        for h in ["video.streamly.example", "www.recipebox.example", "www.ferrytickets.example"]:
            fx.close(fx.open(u(h)))
            wait(lambda: fx.names(h.split(".", 1)[1]) == [], 8)
        fx.grace(30)
        fx.close(tabs["forum.sailors.example"])
        wait(lambda: "sailors.example" in fx.pending(), 3)
        fx.api(f"""
          const now = Date.now(), MIN = {MIN};
          const back = {{ "streamly.example": 41 * MIN, "recipebox.example": 9 * MIN, "ferrytickets.example": 2 * MIN }};
          const got = await browser.storage.local.get("log");
          for (const e of got.log) if (back[e.site]) e.at = now - back[e.site];
          await browser.storage.local.set({{ log: got.log }});
          const s = await browser.storage.session.get("restore");
          for (const e of s.restore) if (back[e.site]) e.at = now - back[e.site];
          await browser.storage.session.set({{ restore: s.restore }});
          await browser.storage.local.set({{ stats: {{ cookies: 43 }} }});
          return true;""")
        print("log:", [(e["site"], e["count"]) for e in fx.log()])

        # ---- 1: the popup over the page it was opened on
        fx.to_page()
        fx.d.switch_to.window(fx.page)
        time.sleep(0.4)
        base_path = OUT / "_base.png"
        fx.d.save_screenshot(str(base_path))
        base = Image.open(base_path)
        fx.open_popup(gazette)
        fx.d.set_window_size(900, 1400)
        time.sleep(1.2)
        print("popup CSS size:", fx.d.execute_script("return [document.body.offsetWidth, document.body.offsetHeight]"))
        pop_path = OUT / "_popup.png"
        fx.d.find_element(By.TAG_NAME, "body").screenshot(str(pop_path))
        popup = Image.open(pop_path)
        backdrop = fit(base).convert("RGBA")
        backdrop = Image.alpha_composite(backdrop, Image.new("RGBA", backdrop.size, (23, 50, 77, 70)))
        k = min(1.0, (H - 28) / popup.height)
        shadowed, pad = card(popup, radius=12, scale=k)
        shot = backdrop.copy()
        shot.alpha_composite(shadowed, (W - shadowed.width + pad - 30, 14 - pad))
        shot.convert("RGB").save(OUT / "1-popup.png")

        # ---- 3: the sites table
        fx.to_ext()
        print("app viewport:", set_viewport(fx, cw, ch))
        fx.open_app()
        scroll_to(fx, "#sites", 64)
        time.sleep(0.8)
        fx.d.save_screenshot(str(OUT / "3-sites.png"))
        fit(Image.open(OUT / "3-sites.png")).save(OUT / "3-sites.png")
    finally:
        fx.quit()
        httpd.shutdown()
        shutil.rmtree(unpacked, ignore_errors=True)
        for tmp in OUT.glob("_*.png"):
            tmp.unlink()
    for p in sorted(OUT.glob("*.png")):
        print(p.relative_to(ROOT), Image.open(p).size)


if __name__ == "__main__":
    main()
