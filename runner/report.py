"""Gom kết quả các lượt chạy thành báo cáo Markdown + file JSON tổng.

python runner/report.py <thu_muc_ket_qua> <file_md_ra> <file_json_ra>
"""
import glob, json, os, sys
from collections import defaultdict

REASONS = {
    "khong_mo_tab": "Bấm không mở tab",
    "khong_thay_mau": "Không thấy màu trên bản đồ",
    "tai_trang_qua_lau": "Tải trang quá lâu",
}


def place(w):
    return ", ".join(x for x in (w.get("city"), w.get("region"), w.get("country")) if x) or "?"


def main(src, md_out, json_out):
    runs = []
    for f in sorted(glob.glob(os.path.join(src, "**", "*.json"), recursive=True)):
        with open(f, encoding="utf-8") as fh:
            runs.append(json.load(fh))
    runs.sort(key=lambda r: r.get("time", ""))

    total = sum(len(r["clicks"]) for r in runs)
    ok = sum(c["ok"] for r in runs for c in r["clicks"])
    ips = {r["where"].get("ip") for r in runs if r["where"].get("ip")}
    regions = {r["where"].get("region") for r in runs if r["where"].get("region")}

    # Gộp lỗi theo vật phẩm (màu + toạ độ + lý do)
    fails = defaultdict(lambda: {"count": 0, "places": set(), "url": None})
    for r in runs:
        for c in r["clicks"]:
            if c["ok"]:
                continue
            key = (c["color"], c.get("x"), c.get("y"), c["reason"])
            fails[key]["count"] += 1
            fails[key]["places"].add(place(r["where"]))
            fails[key]["url"] = fails[key]["url"] or c.get("url")

    L = [f"**{len(runs)} lượt** · **{len(ips)} IP** · {len(regions)} bang/tỉnh · "
         f"**{ok}/{total}** điểm bấm thành công", ""]
    if fails:
        L += ["### Vật phẩm lỗi cần khóa", "",
              "| Màu | Vị trí (x, y) | Lý do | Số lượt gặp | Nơi chạy | Link |",
              "|---|---|---|---|---|---|"]
        for (color, x, y, reason), v in sorted(fails.items(), key=lambda kv: -kv[1]["count"]):
            link = f"[mở]({v['url']})" if v["url"] else "–"
            L.append(f"| `{color}` | {x if x is not None else '–'}, {y if y is not None else '–'} | "
                     f"{REASONS.get(reason, reason)} | {v['count']}/{len(runs)} | "
                     f"{'; '.join(sorted(v['places']))} | {link} |")
    else:
        L += ["### Không có vật phẩm lỗi"]
    L += ["", "<details><summary>Các lượt chạy</summary>", "",
          "| Giờ (UTC) | IP | Nơi chạy | Nhà mạng | Kết quả |", "|---|---|---|---|---|"]
    for r in runs:
        w = r["where"]
        n_ok = sum(c["ok"] for c in r["clicks"])
        L.append(f"| {r.get('time', '')[11:19]} | {w.get('ip') or '?'} | {place(w)} | "
                 f"{w.get('org') or ''} | {n_ok}/{len(r['clicks'])} |")
    L += ["", "</details>"]

    with open(md_out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(runs, f, ensure_ascii=False, indent=1)
    print(f"{len(runs)} lượt, {ok}/{total} thành công, {len(fails)} vật phẩm lỗi")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
