"""Bấm chuột giữa vào các ô màu quy định và ghi lại tab mới có mở thành công không.

Chạy:  python runner/run.py --config config.yaml [--profile 3]
Kết quả ghi ra file JSON (--out), job "report" của workflow gom lại.
Biến môi trường SITE_URL (nếu có) thay cho url đầu tiên trong config.
"""
import argparse, asyncio, io, json, os, sys, time, urllib.request, uuid

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage
from playwright.async_api import async_playwright, TimeoutError as PWTimeout


def hex_to_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)])


def find_spots(png, color, tolerance, min_area):
    """Tìm các vùng có màu `color` (± tolerance) trên ảnh, trả về tâm từng vùng."""
    img = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    mask = np.abs(img - hex_to_rgb(color)).max(axis=2) <= tolerance
    labels, n = ndimage.label(mask)
    if n == 0:
        return []
    idx = range(1, n + 1)
    areas = ndimage.sum(mask, labels, idx)
    centers = ndimage.center_of_mass(mask, labels, idx)
    spots = [(int(round(cx)), int(round(cy)), int(a))
             for (cy, cx), a in zip(centers, areas) if a >= min_area]
    spots.sort(key=lambda s: (s[1], s[0]))
    return spots


async def click_and_check(context, page, x, y, timeout_ms):
    """Chuột giữa tại (x, y); thành công = có tab mới và tải được (HTTP < 400)."""
    try:
        async with context.expect_page(timeout=timeout_ms) as info:
            await page.mouse.click(x, y, button="middle")
        tab = await info.value
    except PWTimeout:
        return {"ok": False, "reason": "khong_mo_tab"}
    try:
        await tab.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        status = await tab.evaluate(
            "() => (performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0")
        url = tab.url
        ok = url not in ("", "about:blank") and (status == 0 or status < 400)
        return {"ok": ok, "url": url, "status": status,
                "reason": None if ok else f"http_{status}"}
    except PWTimeout:
        return {"ok": False, "url": tab.url, "reason": "tai_trang_qua_lau"}
    finally:
        await tab.close()


async def run(cfg, profile):
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            channel=cfg.get("browser_channel") or None,
            headless=cfg.get("headless", True))
        context = await browser.new_context(
            viewport=cfg["viewport"], device_scale_factor=1,
            locale=profile.get("locale", "en-US"),
            timezone_id=profile.get("timezone", "America/New_York"))
        page = await context.new_page()
        for site in cfg["sites"]:
            await page.goto(site["url"], wait_until="load", timeout=cfg["timeout_ms"])
            await page.wait_for_timeout(site.get("wait_ms", 3000))
            for target in site["colors"]:
                png = await page.screenshot()
                spots = find_spots(png, target["color"], target.get("tolerance", 12),
                                   target.get("min_area", 30))
                if not spots:
                    results.append({"site": site["url"], "color": target["color"],
                                    "ok": False, "reason": "khong_thay_mau"})
                for x, y, _ in spots[: target.get("max", 50)]:
                    r = await click_and_check(context, page, x, y, cfg["timeout_ms"])
                    results.append({"site": site["url"], "color": target["color"],
                                    "x": x, "y": y, **r})
                    await page.wait_for_timeout(cfg.get("pause_ms", 500))
        await browser.close()
    return results


def lookup_ip():
    """Tra IP công khai và vị trí của máy đang chạy."""
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as r:
            d = json.load(r)
        return {"ip": d.get("ip"), "city": d.get("city"), "region": d.get("region"),
                "country": d.get("country"), "org": d.get("org")}
    except Exception as e:  # noqa: BLE001
        return {"ip": None, "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--profile", type=int, default=0, help="số thứ tự hồ sơ múi giờ")
    ap.add_argument("--out", default="result.json")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    if os.environ.get("SITE_URL"):
        cfg["sites"][0]["url"] = os.environ["SITE_URL"]
    profiles = cfg["profiles"]
    profile = profiles[a.profile % len(profiles)]
    started = time.time()
    results = asyncio.run(run(cfg, profile))
    payload = {"run_id": str(uuid.uuid4()), "profile": profile.get("name", ""),
               "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "where": lookup_ip(),
               "seconds": round(time.time() - started, 1), "clicks": results}
    ok = sum(r["ok"] for r in results)
    print(f"{ok}/{len(results)} điểm bấm thành công")
    for r in results:
        if not r["ok"]:
            print("  LỖI", r["color"], r.get("x"), r.get("y"), r["reason"])
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
