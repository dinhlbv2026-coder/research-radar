# Research Radar — Radar xu hướng nghiên cứu tự động

Kho này tự chạy **mỗi sáng thứ Hai lúc 6h (giờ Việt Nam)** trên GitHub Actions:

1. **Gemini + Google Search** quét tin 30 ngày gần nhất cho từng chủ đề → 5–7 xu hướng, mỗi xu hướng có bằng chứng, insight xã hội, câu hỏi nghiên cứu tiềm năng, hàm ý kinh doanh. Nguồn lấy từ *grounding metadata* của Google, không để mô hình tự viết URL.
2. **OpenAlex** đo độ "nóng" học thuật: số công bố theo năm, CAGR thô và **CAGR chuẩn hoá theo tổng công bố toàn CSDL** (loại bỏ hiệu ứng CSDL tự phình to), cùng danh sách bài được trích dẫn nhiều 3 năm gần đây. Phần này chỉ là tín hiệu trắc lượng, không phải cơ sở nội dung lược khảo.
3. Báo cáo được lưu vào `reports/YYYY-MM-DD.md` và `reports/latest.md`; dữ liệu thô ở `data/`. Lịch sử commit cho phép so sánh xu hướng theo thời gian.

Plugin Cowork **research-radar-vn** đọc `reports/latest.md` để phân tích sâu, viết học thuật và đề xuất ứng dụng.

## Cài đặt (khoảng 10 phút, làm một lần)

| Bước | Việc cần làm |
|---|---|
| 1 | Vào github.com → **New repository** → tên `research-radar` → chọn **Public** (để Claude đọc báo cáo trực tiếp; nếu chọn Private xem ghi chú bên dưới) → Create. |
| 2 | Trong kho mới: **Add file → Upload files** → kéo toàn bộ nội dung thư mục này vào (kể cả thư mục `.github`) → Commit. Nếu trình duyệt ẩn thư mục `.github`, tạo tay file `.github/workflows/weekly-radar.yml` rồi dán nội dung vào. |
| 3 | **Settings → Secrets and variables → Actions → New repository secret**: `GEMINI_API_KEY` = khoá lấy tại aistudio.google.com. |
| 4 | (Khuyến nghị) Tạo tài khoản miễn phí tại openalex.org, lấy khoá ở openalex.org/settings/api → thêm secret `OPENALEX_API_KEY`. |
| 5 | **Settings → Actions → General → Workflow permissions** → chọn *Read and write permissions* → Save. |
| 6 | Tab **Actions → Research Radar hằng tuần → Run workflow** để chạy thử ngay. Sau 3–5 phút, mở `reports/latest.md`. |

## Tuỳ chỉnh

- Sửa `config/topics.yaml`: thêm chủ đề (sao chép một khối `- id:`), đổi từ khoá, đổi mô hình Gemini, đổi số ngày quét.
- Đổi lịch chạy: sửa dòng `cron` trong `.github/workflows/weekly-radar.yml` (giờ UTC = giờ VN − 7).

## Chi phí (theo bảng giá Google AI tại thời điểm tháng 9/2026)

- **Gói miễn phí (đã kiểm tra trên AI Studio ngày 25/9/2026):** Google Search grounding chỉ mở cho dòng Gemini 2.x/2.5 (1.500 lượt/ngày); dòng Gemini 3.x có hạn mức grounding = 0, gọi sẽ báo lỗi 429. Vì vậy radar mặc định dùng `gemini-2.5-flash` (5 lượt/phút, 20 lượt/ngày) — đủ cho 4 chủ đề/tuần.
- Nếu bật billing (Paid tier), có thể đổi sang `gemini-3.8-flash` trong `config/topics.yaml`; theo bảng giá Google, dòng 3.x có 5.000 lượt search/tháng miễn phí, sau đó 14 USD/1.000 lượt.
- OpenAlex: khoá miễn phí có hạn mức 1 USD/ngày (khoảng 1.000 lượt search), radar dùng khoảng 20 lượt/lần.
- GitHub Actions miễn phí cho kho Public.

## Kho Private

Nếu chọn Private, Claude không đọc được qua đường dẫn công khai. Cách xử lý: clone kho về máy (GitHub Desktop), rồi trong Cowork bấm **Add folder** chọn thư mục đó — plugin sẽ đọc `reports/latest.md` tại chỗ.

## Chạy thủ công trên máy

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...   # và OPENALEX_API_KEY=...
python src/radar.py                      # tất cả chủ đề
python src/radar.py --topic life-insurance
python src/ask_gemini.py "Thị phần bảo hiểm nhân thọ Việt Nam 2025?"   # hỏi đối chiếu nhanh
```

## Giới hạn cần biết

- Gemini có thể tóm tắt sai ý của nguồn; mọi số liệu đưa vào luận án phải mở nguồn gốc để kiểm.
- Từ khoá OpenAlex tìm theo tiêu đề/tóm tắt, nên số đếm là chỉ báo xu hướng, không phải số tuyệt đối của lĩnh vực.
- Tên mô hình Gemini thay đổi theo thời gian; nếu mô hình chính bị ngừng, script tự thử danh sách `gemini_fallback_models`.
