"""Bấm chuột giữa vào mọi phần tử có chứa "Abc・" (từ trên xuống dưới) và ghi lại tab mới có mở thành công không.

Chạy:  python runner/run.py --config config.yaml [--profile 3]
Có API_URL (website quản lý): đọc cấu hình từ website và gửi kết quả về đó.
Không có API_URL: đọc config.yaml, chỉ in kết quả và ghi file --out.
Biến môi trường: API_URL, RUNNER_TOKEN, SITE_URL (thay url game, dùng cho selftest), SELFTEST=true.

Chữ cần bấm mặc định là "Abc・" (đổi được bằng khoá "texts" nếu cần; không bắt buộc).
Trường "colors" giữ nguyên như cũ: chỉ dùng dự phòng khi trang không có chữ "Abc・" nào
(vd trang selftest cũ chỉ có ô màu) — khi đó chạy y hệt cách bấm màu cũ.
"""
import argparse, asyncio, io, json, os, sys, time, urllib.error, urllib.request, uuid

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

DEFAULT_TEXTS = ["Abc・"]
MARK = "data-qa-abc"        # gắn số lên phần tử tìm được để bấm đúng từng cái
DONE = "data-qa-abc-done"   # đánh dấu phần tử đã bấm, không bấm lại

# Tổng độ cuộn dọc: cả trang + các khung cuộn bên trong (nếu game cuộn trong 1 khung).
SCROLL_OFFSET_JS = """() => {
  let y = window.scrollY || 0;
  const skip = [document.scrollingElement, document.documentElement, document.body];
  for (const el of document.querySelectorAll('*'))
    if (!skip.includes(el) && el.scrollTop > 0) y += el.scrollTop;
  return y;
}"""

# Gắn số cho các phần tử tìm được (chưa bấm), trả về vị trí tuyệt đối trên trang để sắp từ trên xuống.
COLLECT_JS = """(els, mark) => els.filter(e => !e.hasAttribute(mark + '-done')).map(e => {
  window.__qaN = (window.__qaN || 0) + 1;
  e.setAttribute(mark, String(window.__qaN));
  const r = e.getBoundingClientRect();
  let y = r.top, x = r.left;   // vị trí trên màn hình + độ cuộn của mọi khung chứa nó = vị trí trên trang
  for (let p = e.parentElement; p; p = p.parentElement) { y += p.scrollTop || 0; x += p.scrollLeft || 0; }
  return {id: window.__qaN, y: Math.round(y), x: Math.round(x)};
})"""


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


async def click_and_check(context, page, x, y, timeout_ms, locator=None):
    """Chuột giữa vào `locator` (tự cuộn tới) hoặc tại (x, y); thành công = có tab mới và tải được (HTTP < 400)."""
    try:
        async with context.expect_page(timeout=timeout_ms) as info:
            if locator is not None:
                await locator.click(button="middle", timeout=timeout_ms)
            else:
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


async def scroll_through(page, cfg):
    """Cuộn từ trên xuống cuối trang rồi về đầu, để các mục tải dần (lazy-load) hiện ra hết."""
    try:
        vw, vh = cfg["viewport"]["width"], cfg["viewport"]["height"]
        await page.mouse.move(vw // 2, vh // 2)
        last = -1
        for _ in range(int(cfg.get("max_scrolls", 200))):
            await page.mouse.wheel(0, int(vh * 0.8))
            await page.wait_for_timeout(int(cfg.get("scroll_wait_ms", 400)))
            off = await page.evaluate(SCROLL_OFFSET_JS)
            if off <= last:
                break  # không cuộn được nữa = hết trang
            last = off
        await page.evaluate("""() => { window.scrollTo(0, 0);
          for (const el of document.querySelectorAll('*')) if (el.scrollTop > 0) el.scrollTop = 0; }""")
        await page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001  — cuộn lỗi thì vẫn tìm/bấm bình thường
        pass


async def collect(page, text, exact):
    """Tìm mọi phần tử (đang hiển thị, chưa bấm) chứa `text`, cả trong iframe; sắp từ trên xuống dưới."""
    items = []
    for frame in page.frames:
        try:
            loc = frame.get_by_text(text, exact=exact).filter(visible=True)
            if await loc.count() == 0:
                continue
            found = await loc.evaluate_all(COLLECT_JS, MARK)
            base = {"x": 0, "y": 0}
            if frame != page.main_frame:  # cộng vị trí của iframe trên trang chính
                fe = await frame.frame_element()
                base = await fe.evaluate("e => { const r = e.getBoundingClientRect();"
                                         " return {x: r.left + scrollX, y: r.top + scrollY}; }")
        except Exception:  # noqa: BLE001  — iframe vừa bị xoá/đổi trang: bỏ qua iframe đó
            continue
        for it in found:
            it["x"] += round(base["x"])
            it["y"] += round(base["y"])
            it["frame"] = frame
        items += found
    items.sort(key=lambda it: (it["y"], it["x"]))
    return items


async def click_all_text(context, page, site, cfg, text, exact, limit, label, results):
    """Bấm mọi phần tử chứa `text` từ trên xuống dưới. Trả về số phần tử đã bấm."""
    n = 0
    # Vòng 1 bấm hết những gì tìm thấy; các vòng sau bắt mục mới hiện ra trong lúc bấm.
    for _ in range(int(cfg.get("rescan_rounds", 3))):
        items = await collect(page, text, exact)
        if not items:
            break
        for it in items:
            if limit is not None and n >= limit:
                return n
            n += 1
            el = it["frame"].locator(f'[{MARK}="{it["id"]}"]')
            try:
                await el.evaluate(f"e => e.setAttribute('{DONE}', '1')")
            except Exception:  # noqa: BLE001
                pass
            r = await click_and_check(context, page, None, None, cfg["timeout_ms"], locator=el)
            if not r["ok"] and r["reason"] in ("khong_mo_tab", "tai_trang_qua_lau"):
                await page.wait_for_timeout(1500)  # bấm lại 1 lần để tránh báo lỗi nhầm
                r = await click_and_check(context, page, None, None, cfg["timeout_ms"], locator=el)
            # giữ đúng các trường như bản cũ: site, color, x, y, ok, url, status, reason
            results.append({"site": site["url"], "color": label, "x": it["x"], "y": it["y"], **r})
            await page.wait_for_timeout(cfg.get("pause_ms", 500))
    return n


async def click_colors(context, page, site, cfg, results):
    """Cách bấm màu cũ, giữ nguyên — chỉ dùng dự phòng khi trang không có chữ cần bấm."""
    for target in site.get("colors") or []:
        png = await page.screenshot()
        spots = find_spots(png, target["color"], target.get("tolerance", 12),
                           target.get("min_area", 30))
        if not spots:
            results.append({"site": site["url"], "color": target["color"],
                            "ok": False, "reason": "khong_thay_mau"})
        for x, y, _ in spots[: target.get("max", 50)]:
            r = await click_and_check(context, page, x, y, cfg["timeout_ms"])
            if not r["ok"] and r["reason"] in ("khong_mo_tab", "tai_trang_qua_lau"):
                await page.wait_for_timeout(1500)  # bấm lại 1 lần để tránh báo lỗi nhầm
                r = await click_and_check(context, page, x, y, cfg["timeout_ms"])
            results.append({"site": site["url"], "color": target["color"],
                            "x": x, "y": y, **r})
            await page.wait_for_timeout(cfg.get("pause_ms", 500))


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
            await scroll_through(page, cfg)  # cho mục tải dần hiện ra hết trước khi tìm
            colors = site.get("colors") or []
            # nhãn ghi vào trường "color" của kết quả: dùng màu đã cấu hình (như cũ) nếu có
            label = colors[0]["color"] if colors and isinstance(colors[0], dict) and colors[0].get("color") else None
            total = 0
            for t in site.get("texts") or cfg.get("texts") or DEFAULT_TEXTS:
                t = t if isinstance(t, dict) else {"text": t}
                total += await click_all_text(context, page, site, cfg, t["text"], t.get("exact", False),
                                              t.get("max"), label or t["text"], results)
            if total == 0:
                if colors:
                    await click_colors(context, page, site, cfg, results)  # dự phòng: như bản cũ
                else:
                    results.append({"site": site["url"], "color": label or DEFAULT_TEXTS[0],
                                    "ok": False, "reason": "khong_thay_mau"})
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


def api_call(path, data=None):
    req = urllib.request.Request(
        os.environ["API_URL"].rstrip("/") + path,
        data=json.dumps(data).encode() if data is not None else None,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json",
                 # Cloudflare chặn chữ ký mặc định "Python-urllib" (403), nên tự đặt tên riêng
                 "User-Agent": "game-maps-qa-runner/1.0 (+github-actions)",
                 "Authorization": f"Bearer {os.environ.get('RUNNER_TOKEN', '')}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def config_from_web(base, index):
    """Lượt thứ index (0, 1, 2…) chạy link thứ index % số link: xoay vòng."""
    w = api_call("/api/config")
    urls = w.get("urls") or ([w["url"]] if w.get("url") else [])
    if not urls:
        raise SystemExit("Chưa có link trang bản đồ trong Cài đặt")
    url = urls[index % len(urls)]
    print(f"Lượt {index + 1}: link {index % len(urls) + 1}/{len(urls)} – {url}")
    base["sites"] = [{"url": url, "wait_ms": int(w.get("wait_seconds", 4)) * 1000,
                      "colors": w.get("colors", [])}]
    if w.get("texts"):  # không bắt buộc; website không gửi thì dùng "Abc・"
        base["sites"][0]["texts"] = w["texts"]
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--profile", type=int, default=0, help="số thứ tự hồ sơ múi giờ")
    ap.add_argument("--out", default="result.json")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    if os.environ.get("API_URL") and os.environ.get("SELFTEST") != "true":
        cfg = config_from_web(cfg, a.profile)  # selftest dùng màu mẫu trong config.yaml
    if os.environ.get("SITE_URL"):
        cfg["sites"][0]["url"] = os.environ["SITE_URL"]
    profiles = cfg["profiles"]
    profile = profiles[a.profile % len(profiles)]
    started = time.time()
    results = asyncio.run(run(cfg, profile))
    payload = {"run_id": str(uuid.uuid4()), "profile": profile.get("name", ""),
               "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "where": lookup_ip(),
               "selftest": os.environ.get("SELFTEST") == "true",
               "seconds": round(time.time() - started, 1), "clicks": results}
    ok = sum(r["ok"] for r in results)
    print(f"{ok}/{len(results)} điểm bấm thành công")
    for r in results:
        if not r["ok"]:
            print("  LỖI", r["color"], r.get("x"), r.get("y"), r["reason"])
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    if os.environ.get("API_URL"):
        try:
            print("Đã gửi về website:", api_call("/api/results", payload))
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Website từ chối nhận kết quả: HTTP {e.code} {e.read()[:200]!r}")


if __name__ == "__main__":
    sys.exit(main())
