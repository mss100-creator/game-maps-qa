# Kiểm thử game maps – bấm chuột giữa theo màu

Chạy hoàn toàn trên GitHub Actions. Mỗi ngày 08:17 (giờ VN) workflow chạy 20 lượt, mỗi lượt là một
máy ảo mới ở Mỹ (IP mới). Mỗi lượt mở Chrome, tìm các ô màu trong `config.yaml`, bấm chuột giữa từng ô
và ghi lại tab mới có mở thành công không.

## Xem kết quả
- **Issue "Vật phẩm lỗi ngày YYYY-MM-DD"**: danh sách vật phẩm lỗi cần khóa, tự tạo/cập nhật sau mỗi đợt.
  GitHub gửi thông báo qua email/app cho người theo dõi repo.
- **Tab Actions → lượt chạy → Summary**: bảng tổng hợp, IP và nơi chạy của từng lượt.
- **Nhánh `results`**: lưu file JSON + Markdown của mọi đợt để tra lại.

## Việc cần làm một lần
Sửa `config.yaml`:
- `url`: trang bản đồ của game (thay `ten-mien-game-cua-ban.com`; khi còn chữ này workflow tự bỏ qua)
- `colors`: mã màu từng loại ô vật phẩm; tăng `tolerance` nếu màu bị bóng/khử răng cưa
- `wait_ms`: thời gian chờ bản đồ vẽ xong

## Chạy tay
Actions → **QA game maps** → **Run workflow**:
- `count`: số lượt (1–20)
- `selftest`: tích vào để chạy với trang mẫu trong `test/` (kiểm tra công cụ, không đụng game thật)

## Lý do lỗi
| Mã | Ý nghĩa |
|---|---|
| Bấm không mở tab | Bấm chuột giữa nhưng không có tab mới |
| `http_404`, `http_500`… | Tab mở nhưng trang đích trả lỗi |
| Tải trang quá lâu | Tab mới không tải xong trong `timeout_ms` |
| Không thấy màu trên bản đồ | Không tìm thấy ô màu đó trong lượt này |

## Chi phí
Repo private: dùng hạn mức phút Actions miễn phí hằng tháng của tài khoản. Mỗi lượt khoảng 2–3 phút,
nên 20 lượt/ngày có thể chạm ngưỡng; giảm `count` hoặc đổi lịch nếu cần.

## Chạy trên máy
```bash
pip install -r runner/requirements.txt && python -m playwright install chromium
python runner/run.py --config config.yaml --out result.json
```
