# Triển khai và bảo trì

Xem kiến trúc ở [kien-truc.md](kien-truc.md). Cài đặt lần đầu (tạo 3 Secret) ở [README](../README.md).

## 1. Thay đổi nào tự cập nhật

| Sửa trên nhánh `main` | Cách cập nhật | Có hiệu lực |
|---|---|---|
| `worker/**` hoặc `.github/workflows/deploy.yml` | `deploy.yml` tự chạy khi push | Khoảng 1 phút sau |
| `runner/**`, `config.yaml`, `test/**`, `.github/workflows/qa.yml` | Không cần deploy, mỗi lượt checkout code mới nhất | Lượt chạy kế tiếp |
| Cài đặt trên website | Lưu thẳng vào D1 | Ngay lập tức |
| Secrets trên GitHub | **Không tự cập nhật.** Phải chạy lại `deploy.yml` bằng tay | Sau khi deploy xong |

Không sửa Worker trực tiếp trên dashboard Cloudflare. Lần deploy sau từ GitHub sẽ ghi đè.

## 2. Workflow `deploy.yml` làm gì

1. Kiểm tra đủ `CLOUDFLARE_API_TOKEN`, `ADMIN_PASS`, `GH_DISPATCH_TOKEN`. Thiếu thì ghi thông báo ở Summary rồi
   dừng, không báo lỗi đỏ.
2. Tìm D1 tên `game-maps-qa`, chưa có thì tạo. Điền ID vào `wrangler.toml` (chỉ trên máy ảo, không commit).
3. Chạy `worker/schema.sql` vào D1. Các lệnh đều là `CREATE … IF NOT EXISTS`, chạy lại nhiều lần không mất dữ liệu.
4. `wrangler deploy --var GH_REPO:<owner/repo>`.
5. Đặt secret cho Worker: `ADMIN_PASS`, `GH_TOKEN`, `RUNNER_TOKEN` (tính từ token Cloudflare).
6. Ghi địa chỉ website vào Summary.

Chạy lại bằng tay: Actions → *Triển khai website quản lý* → *Run workflow*.
Chạy lại nhiều lần đều an toàn: dữ liệu và cài đặt trong D1 được giữ nguyên.

## 3. Bảo trì định kỳ

| Việc | Khi nào | Cách làm |
|---|---|---|
| Gia hạn `GH_DISPATCH_TOKEN` | Trước khi token hết hạn (đặt 1 năm khi tạo). GitHub gửi email nhắc trước | Tạo token mới (cùng quyền *Actions: Read and write*, chỉ repo này), cập nhật Secret, chạy lại `deploy.yml`. Dấu hiệu hết hạn: *Chạy ngay* báo "GitHub trả 401" và lịch tự động ngừng |
| Kiểm tra phút GitHub Actions | Hằng tháng | github.com/settings/billing → Actions. Giảm số lượt hoặc giờ chạy nếu gần hết |
| Sao lưu dữ liệu | Hằng tuần hoặc tháng | Nút *Tải CSV* theo ngày, hoặc sao lưu toàn bộ (mục 4) |
| Theo dõi D1 | Khi dữ liệu lớn dần | Cloudflare dashboard → Storage & Databases → D1 → `game-maps-qa`: dung lượng (tối đa 500 MB ở gói Free) |
| Dọn dữ liệu cũ | Khi D1 gần 500 MB | Mục 4, lệnh xoá dữ liệu cũ |
| Cập nhật action/thư viện | Khi Actions cảnh báo phiên bản cũ | Nâng `actions/checkout`, `setup-python`, `setup-node` trong workflow. Playwright tự cài bản mới mỗi lượt |

## 4. Thao tác dữ liệu (D1)

Chạy trên máy có Node.js, đã đặt biến môi trường `CLOUDFLARE_API_TOKEN`, trong thư mục `worker/`:

```bash
# Sao lưu toàn bộ database ra file SQL
npx wrangler d1 export game-maps-qa --remote --output backup-$(date +%F).sql

# Xem nhanh
npx wrangler d1 execute game-maps-qa --remote --command "SELECT COUNT(*) FROM runs"

# Xoá dữ liệu cũ hơn 180 ngày (giữ cài đặt)
npx wrangler d1 execute game-maps-qa --remote --command \
 "DELETE FROM clicks WHERE run_id IN (SELECT id FROM runs WHERE created_at < datetime('now','-180 days'));
  DELETE FROM runs WHERE created_at < datetime('now','-180 days');"

# Khôi phục từ bản sao lưu vào database trống
npx wrangler d1 execute game-maps-qa --remote --file backup-YYYY-MM-DD.sql
```

## 5. Thay đổi cấu trúc dữ liệu

`schema.sql` chạy lại mỗi lần deploy, nên mọi lệnh trong đó phải chạy lặp lại được.
- **Bảng hoặc index mới:** thêm `CREATE TABLE/INDEX IF NOT EXISTS …` vào `schema.sql`.
- **Thêm cột vào bảng đã có:** SQLite không có `ADD COLUMN IF NOT EXISTS`, nên không đưa `ALTER TABLE` vào `schema.sql`
  vì lần deploy sau sẽ lỗi. Chạy `ALTER TABLE …` một lần bằng `wrangler d1 execute --remote`, đồng thời cập nhật
  `CREATE TABLE` trong `schema.sql` cho database mới.
- Code Worker cần chịu được dữ liệu cũ thiếu cột hoặc khoá mới. Ví dụ: `getSetting` tự bổ sung `urls`/`names` cho cài đặt kiểu cũ.

## 6. Quay lại bản trước

- **Website:** `git revert <commit>` trên `main` rồi push, `deploy.yml` sẽ đưa bản cũ lên. Cần gấp thì vào
  Cloudflare dashboard → Workers → `game-maps-qa` → Deployments → *Rollback*, nhưng lần push sau sẽ ghi đè lại.
- **Runner:** `git revert` là đủ, lượt sau dùng bản cũ.
- Dữ liệu D1 không bị ảnh hưởng khi quay lại code.

## 7. Đổi bí mật

| Đổi | Các bước |
|---|---|
| Mật khẩu website | Sửa Secret `ADMIN_PASS` → chạy `deploy.yml`. Mọi người phải đăng nhập lại |
| Token GitHub | Sửa Secret `GH_DISPATCH_TOKEN` → chạy `deploy.yml` |
| Token Cloudflare | Sửa Secret `CLOUDFLARE_API_TOKEN` → chạy `deploy.yml`. `RUNNER_TOKEN` tự đổi theo. Lượt kiểm thử nào đang chạy dở lúc đó sẽ gửi kết quả thất bại |

## 8. Sự cố khi triển khai và vận hành

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `deploy.yml` báo "thiếu Secrets" | Chưa thêm hoặc sai tên Secret | Kiểm tra đúng 3 tên ở README |
| `deploy.yml` lỗi ở bước D1 hoặc deploy, mã 10000 / Authentication | Token Cloudflare thiếu quyền hoặc hết hạn | Tạo lại theo mẫu *Edit Cloudflare Workers* và thêm *D1 · Edit* |
| `deploy.yml` lỗi "workers.dev subdomain" | Tài khoản chưa có tên miền workers.dev | Mở dashboard → Workers & Pages một lần để Cloudflare tạo, rồi chạy lại |
| Nhiều account Cloudflare, deploy chọn sai | Wrangler không biết dùng account nào | Thêm Secret `CLOUDFLARE_ACCOUNT_ID` |
| *Chạy ngay* báo "GitHub trả 401/403/404" | `GH_DISPATCH_TOKEN` hết hạn, thiếu quyền Actions, hoặc repo đổi tên | Tạo lại token, chạy `deploy.yml` (deploy cũng cập nhật `GH_REPO`) |
| Lượt chạy xanh nhưng website không có kết quả | Runner gửi kết quả thất bại | Mở log job, bước *Chạy kiểm thử*: `401` thì `RUNNER_TOKEN` lệch, chạy lại `deploy.yml`; `403` thì Cloudflare chặn (WAF/Bot Fight), cho qua User-Agent `game-maps-qa-runner` |
| Lượt chạy đỏ "Chưa có link trang bản đồ" | Cài đặt chưa có link | Thêm link trên website |
| Hẹn giờ không chạy | *Tự động* đang tắt, chưa có link, hoặc chưa ai mở website sau lần deploy đầu (chưa có `origin`) | Bật tự động và mở website một lần. Xem log cron: dashboard → Workers → `game-maps-qa` → Logs |
| Mọi điểm bấm đều "Không thấy màu" | Bản đồ chưa vẽ xong, hoặc màu bị bóng hay khử răng cưa | Tăng *Chờ bản đồ hiện xong*, tăng độ lệch màu |
| D1 báo lỗi vượt giới hạn | Quá hạn mức dòng đọc/ghi trong ngày (gói Free) | Tự hết lúc 0h UTC (7h sáng VN). Giảm lượt hoặc dọn dữ liệu |

## 9. Chạy trên máy để phát triển

```bash
pip install -r runner/requirements.txt && python -m playwright install chromium
cd worker
printf 'RUNNER_TOKEN=t123\nADMIN_PASS=p123\nGH_TOKEN=x\nGH_REPO=a/b\n' > .dev.vars   # đã có trong .gitignore
npx wrangler d1 execute game-maps-qa --local --file schema.sql
npx wrangler dev --port 8787            # mở http://localhost:8787, mật khẩu p123
# Cửa sổ khác: trang mẫu + một lượt kiểm thử gửi kết quả về website trên máy
(cd test && python -m http.server 8765) &
SELFTEST=true SITE_URL=http://localhost:8765/page.html API_URL=http://localhost:8787 RUNNER_TOKEN=t123 \
  python runner/run.py --config config.yaml --out result.json
```
Trên máy không có Chrome thật thì đặt `browser_channel: ""` trong `config.yaml` để dùng Chromium.
