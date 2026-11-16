# Kiến trúc hệ thống

Hệ thống gồm hai nơi: **GitHub** giữ toàn bộ mã nguồn và chạy trình duyệt kiểm thử;
**Cloudflare** chạy website quản lý và lưu dữ liệu. Không có máy chủ riêng nào khác.

```
                 GitHub (repo private mss100-creator/game-maps-qa)
 ┌──────────────────────────────────────────────────────────────────┐
 │ Mã nguồn (bản gốc duy nhất)          GitHub Actions               │
 │  worker/   website                   ├─ deploy.yml  → đưa worker/  │
 │  runner/   script trình duyệt        │                 lên Cloudflare
 │  test/     trang mẫu                 └─ qa.yml      → chạy runner/ │
 │  .github/workflows/                     trên 1–20 máy ảo ở Mỹ      │
 └──────────────────────────────────────────────────────────────────┘
        │ deploy (tự động)          ▲ workflow_dispatch     │ GET cấu hình
        ▼                           │ (Chạy ngay / hẹn giờ) │ POST kết quả
 ┌──────────────────────────────────────────────────────────────────┐
 │ Cloudflare (Workers Free + D1)                                    │
 │  Worker "game-maps-qa"  – website + API + hẹn giờ (cron mỗi giờ)  │
 │  D1 "game-maps-qa"      – cài đặt, lượt chạy, điểm bấm            │
 └──────────────────────────────────────────────────────────────────┘
```

## 1. Thành phần

| Thành phần | Nằm ở | Vai trò |
|---|---|---|
| `worker/src/index.js` | GitHub → chạy trên Cloudflare | Đăng nhập, API, lưu/đọc D1, gọi GitHub chạy kiểm thử, hẹn giờ |
| `worker/src/app.html`, `login.html` | GitHub → nhúng vào Worker khi deploy | Giao diện website (một trang, tối ưu điện thoại) |
| `worker/schema.sql` | GitHub → chạy vào D1 mỗi lần deploy | Cấu trúc bảng dữ liệu |
| `worker/wrangler.toml` | GitHub | Cấu hình Worker: tên, D1, cron `17 * * * *` |
| `runner/run.py` | GitHub, chạy trên máy ảo Actions | Mở Chrome, dò màu, bấm chuột giữa, kiểm tra tab mới, gửi kết quả |
| `config.yaml` | GitHub | Thông số trình duyệt (khung hình, timeout, hồ sơ múi giờ) và màu mẫu cho chạy thử |
| `.github/workflows/qa.yml` | GitHub Actions | Chạy N lượt kiểm thử song song (tối đa 5 cùng lúc) |
| `.github/workflows/deploy.yml` | GitHub Actions | Tạo D1 nếu chưa có, cập nhật bảng, đưa Worker lên, đặt secret |
| `test/` | GitHub | Trang mẫu có sẵn 2 ô lỗi, dùng cho "Chạy thử với trang mẫu" |
| D1 `game-maps-qa` | Chỉ ở Cloudflare | Cài đặt từ website và toàn bộ kết quả. **Không có bản sao trên GitHub** |

## 2. Luồng một đợt kiểm thử

1. **Kích hoạt.** Có hai cách:
   - Bấm *Chạy ngay* → `POST /api/run`.
   - Cron của Worker chạy phút 17 mỗi giờ, đổi sang giờ Việt Nam; nếu giờ đó nằm trong `run_hours` và
     *Tự động* đang bật thì kích hoạt với `runs_per_batch` lượt.

   Worker gọi GitHub API `workflow_dispatch` cho `qa.yml` với `count`, `api` (địa chỉ website) và `selftest`.
2. **Chia lượt.** Job `plan` tạo ma trận `0…count-1`. Mỗi phần tử là một job trên **một máy ảo mới**
   (IP mới, thường thuộc Azure ở Mỹ). Tối đa 5 job chạy cùng lúc, mỗi job tối đa 10 phút.
3. **Lấy cấu hình.** Runner gọi `GET {api}/api/config` (kèm `RUNNER_TOKEN`). Lượt thứ `i` (đếm từ 0) dùng
   link thứ `i % số_link` (xoay vòng) và hồ sơ múi giờ thứ `i % số_hồ_sơ` trong `config.yaml`.
4. **Kiểm thử.**
   - Mở link bằng Chrome (khung 1366×768, tỉ lệ điểm ảnh 1) và chờ `wait_seconds`.
   - Chụp màn hình và tìm các vùng có màu cần tìm (± độ lệch, diện tích ≥ `min_area`).
   - Bấm chuột giữa vào tâm từng vùng. Bấm thành công khi có tab mới mở được, mã HTTP < 400.
   - Nếu bấm không mở tab hoặc tải quá lâu thì bấm lại 1 lần để tránh báo lỗi nhầm.
5. **Gửi kết quả.**
   - Runner tra IP và vị trí của máy qua ipinfo.io.
   - Gửi `POST {api}/api/results` với User-Agent riêng: Cloudflare chặn chữ ký mặc định của Python với mã 403.
   - Worker ghi 1 dòng `runs` và toàn bộ điểm bấm vào `clicks`.
6. **Xem.** Website đọc D1 theo ngày (giờ Việt Nam) rồi gộp và lọc ngay trên trình duyệt.

Chạy thử với trang mẫu (`selftest=true`) bỏ qua bước 3. Runner dùng màu trong `config.yaml` và trang
`test/page.html` phục vụ ngay trên máy ảo, nên kết quả đúng phải là 3/5 điểm bấm được.

## 3. Dữ liệu (D1)

| Bảng | Một dòng là | Cột chính |
|---|---|---|
| `settings` | Một mục cài đặt | `key = 'config'` (JSON cài đặt), `key = 'origin'` (địa chỉ website, dùng cho hẹn giờ) |
| `runs` | Một lượt chạy (một máy ảo) | `id`, `created_at` (UTC), `ip`, `city`, `region`, `country`, `asn`, `profile`, `kind` (`real`/`selftest`), `total`, `ok`, `seconds` |
| `clicks` | Một điểm bấm | `run_id`, `site` (link đã chạy), `color`, `x`, `y`, `ok`, `url` (trang đích), `status` (HTTP), `reason` |

JSON cài đặt:
```json
{ "enabled": true, "urls": ["https://…"], "names": ["Chính"], "wait_seconds": 4,
  "colors": [{ "color": "#2E86DE", "tolerance": 12, "min_area": 30, "max": 50 }],
  "runs_per_batch": 20, "run_hours": [8] }
```

Mã `reason`: `khong_mo_tab`, `tai_trang_qua_lau`, `khong_thay_mau`, `http_<mã>`.

## 4. API của Worker

| Đường dẫn | Xác thực | Mục đích |
|---|---|---|
| `POST /login`, `GET /logout` | – | Đăng nhập bằng `ADMIN_PASS`, cookie `qa_auth` 30 ngày |
| `GET /` | Cookie | Giao diện; đồng thời lưu `origin` cho hẹn giờ |
| `GET /api/config` | Cookie hoặc `RUNNER_TOKEN` | Đọc cài đặt |
| `PUT /api/config` | Cookie | Lưu cài đặt (đã làm sạch: tối đa 20 link, 12 màu, 1–20 lượt) |
| `POST /api/run` | Cookie | Kích hoạt `qa.yml` (`{count}` hoặc `{selftest:true}`) |
| `POST /api/results` | `RUNNER_TOKEN` | Runner gửi kết quả một lượt |
| `GET /api/data?day=YYYY-MM-DD` | Cookie | Các lượt và điểm bấm trong ngày (giờ VN) |
| `GET /api/trend?days=14` | Cookie | Tỉ lệ bấm được theo ngày và theo link |
| `GET /api/csv?day=` | Cookie | Xuất CSV (UTF-8 có BOM để Excel đọc đúng tiếng Việt) |

## 5. Bảo mật

| Bí mật | Ai giữ | Dùng để |
|---|---|---|
| `ADMIN_PASS` | GitHub Secret → secret của Worker | Đăng nhập website. Cookie là HMAC của mật khẩu, nên đổi mật khẩu thì mọi phiên cũ hết hiệu lực |
| `GH_DISPATCH_TOKEN` | GitHub Secret → secret `GH_TOKEN` của Worker | Worker gọi GitHub chạy `qa.yml`. Token fine-grained, chỉ quyền Actions trên repo này |
| `CLOUDFLARE_API_TOKEN` | GitHub Secret | `deploy.yml` đưa Worker lên và quản lý D1 |
| `RUNNER_TOKEN` | **Không lưu ở đâu cả.** Tính ra từ `sha256(CLOUDFLARE_API_TOKEN + ":runner")`, lấy 48 ký tự đầu | Runner xác thực khi đọc cài đặt và gửi kết quả. Đổi token Cloudflare thì `RUNNER_TOKEN` cũng đổi theo, nên phải deploy lại |

Repo để private vì kết quả có link và vị trí vật phẩm lỗi. Website chỉ mở cho người có mật khẩu.

## 6. Giới hạn cần biết

| Hạng mục | Giới hạn | Ảnh hưởng |
|---|---|---|
| GitHub Actions, repo private | Hạn mức phút miễn phí hằng tháng (2.000 phút với gói Free). Mỗi lượt được làm tròn lên khoảng 2 phút | Trang Cài đặt ước tính và cảnh báo khi vượt |
| Workers Free | 100.000 request/ngày, 10 ms CPU/request | Dư cho nhu cầu hiện tại |
| D1 Free | 5 triệu dòng đọc/ngày, 100.000 dòng ghi/ngày, 5 GB tổng, 500 MB mỗi database, 50 câu lệnh mỗi lần gọi Worker | Mỗi lượt ghi bằng 2 câu lệnh. 20 lượt × 100 điểm = khoảng 2.000 dòng/ngày. Quá giới hạn ngày thì D1 báo lỗi đến 0h UTC hôm sau |
| Một lượt | Tối đa 2.000 điểm bấm được lưu; mỗi màu tối đa `max` điểm (mặc định 50) | |
| Vị trí IP | Máy ảo GitHub dùng IP Azure, tập trung ở vài vùng của Mỹ | Không phủ đều mọi bang |
