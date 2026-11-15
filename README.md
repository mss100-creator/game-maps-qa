# Kiểm thử game maps – bấm chuột giữa theo màu

Mọi việc làm trên **website quản lý** (dùng tốt trên điện thoại):
- **Kết quả**: vật phẩm lỗi cần khóa, các lượt chạy, IP và nơi chạy, chọn xem theo ngày.
- **Chạy ngay**: chọn số lượt (1–20) rồi bấm.
- **Cài đặt**: các link trang bản đồ (mỗi dòng một link, các lượt chạy xoay vòng qua từng link), màu ô vật phẩm, số lượt mỗi đợt, giờ chạy tự động.

Mỗi lượt chạy trên một máy GitHub mới ở Mỹ (IP mới), mở Chrome, tìm các ô màu, bấm chuột giữa từng ô và
ghi lại tab mới có mở thành công không (bấm lại 1 lần trước khi kết luận lỗi).

## Cài đặt một lần (khoảng 10 phút)

Cần thêm 3 "Secret" vào repo tại
**https://github.com/mss100-creator/game-maps-qa/settings/secrets/actions/new**
(mỗi Secret: điền *Name* và *Secret*, bấm *Add secret*).

### 1. `ADMIN_PASS` – mật khẩu vào website
Tự đặt một mật khẩu dài, dễ nhớ với bạn.

### 2. `GH_DISPATCH_TOKEN` – cho website bấm "Chạy ngay"
1. Mở https://github.com/settings/personal-access-tokens/new
2. *Token name*: `game-maps-qa` · *Expiration*: 1 năm
3. *Repository access*: **Only select repositories** → chọn `game-maps-qa`
4. *Permissions* → *Repository permissions* → **Actions: Read and write**
5. *Generate token*, chép chuỗi `github_pat_…` vào Secret này

### 3. `CLOUDFLARE_API_TOKEN` – để đưa website lên Cloudflare
1. Mở https://dash.cloudflare.com/profile/api-tokens → *Create Token*
2. Chọn mẫu **Edit Cloudflare Workers** → *Use template*
3. Bấm *+ Add more* và thêm quyền: **Account · D1 · Edit**
4. *Continue to summary* → *Create Token*, chép chuỗi vào Secret này

(Nếu tài khoản Cloudflare có nhiều account, thêm Secret `CLOUDFLARE_ACCOUNT_ID`.
Lần đầu dùng Workers, vào dash.cloudflare.com → Workers & Pages một lần để Cloudflare tạo tên miền `workers.dev`.)

### 4. Triển khai
Mở **https://github.com/mss100-creator/game-maps-qa/actions/workflows/deploy.yml** → *Run workflow*.
Khoảng 1 phút sau, mở lượt chạy đó: phần Summary ghi **địa chỉ website quản lý**
(dạng `https://game-maps-qa.<ten>.workers.dev`). Lưu địa chỉ này vào màn hình chính điện thoại.

### 5. Trên website
Đăng nhập → tab **Cài đặt**: nhập địa chỉ trang game, màu ô vật phẩm, giờ chạy, bật *Tự động chạy hằng ngày* → *Lưu*.
Bấm *Chạy thử với trang mẫu* để chắc mọi thứ hoạt động.

## Chi phí
Cloudflare Workers + D1: gói Free. GitHub Actions (repo private): mỗi lượt khoảng 2 phút;
trang Cài đặt hiện ước tính số phút mỗi tháng và cảnh báo khi vượt 2.000 phút miễn phí.

## Cấu trúc
- `worker/` – website quản lý (Cloudflare Worker + D1), tự hẹn giờ chạy theo trang Cài đặt
- `runner/run.py` – script trình duyệt; đọc cấu hình và gửi kết quả về website
- `.github/workflows/qa.yml` – chạy các lượt kiểm thử (website kích hoạt)
- `.github/workflows/deploy.yml` – đưa website lên Cloudflare
- `test/` – trang mẫu cho "Chạy thử với trang mẫu"
