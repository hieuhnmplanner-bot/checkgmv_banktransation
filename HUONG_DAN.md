# Dashboard Đối Soát GMV vs Sao Kê Ngân Hàng — PalFish

## Cài đặt & chạy
```bash
pip install -r requirements.txt
streamlit run app.py
```
Deploy lên Streamlit Cloud: push `app.py`, `recon_engine.py`,
`requirements.txt` lên GitHub repo rồi trỏ vào `app.py`
(giống các app PF_dashboard hiện tại).

## Nguồn dữ liệu (sidebar)
| # | Dataset | Nguồn hiện tại | Ghi chú |
|---|---|---|---|
| 1 | Report đơn HN | SM_HANOI_daily_report → sheet **INCOME** | app tự dò sheet khi upload Excel |
| 2 | Sao kê NH HN | File bank transaction MB | KHÔNG sửa tay |
| 3 | Report đơn HCM | HCM_Revenue_statement → sheet **REVENUE** | tự dò sheet |
| 4 | Sao kê NH HCM | File bank transaction VCB SG | bổ sung thêm TK khác khi có |
| 5 | Sao kê điền tay | tùy chọn | cho tab kiểm tra toàn vẹn |

Mỗi mục nhận **link Google Sheet** (Anyone with link → Viewer, link từng
tab có `gid=`) hoặc **upload CSV/Excel**. Quy trình hàng tháng: paste thêm
dữ liệu vào Google Sheet → mở app → "Tải lại dữ liệu".

**Phạm vi nghiên cứu**: chỉnh "Từ tháng / Đến tháng" ở sidebar
(mặc định 2026-01 → 2026-03). Report chứa nhiều năm cũng không sao,
app tự lọc theo cột `Month of payment`.

## Engine khớp tự động (6 vòng)
0. **Theo giờ giao dịch** (bank day + bank time): đúng số tiền trong ±60′
   → Khớp đúng; cùng thời điểm ±5′ nhưng số tiền khác (≤20%)
   → **🟡 Lệch số tiền — chỉ rõ chính xác khoản lệch**
1. Số tiền đúng + ngày ±N (mặc định ±3)
2. Số tiền đúng + SĐT của đơn trong nội dung chuyển khoản
3. Cọc + chuyển nốt (2 GD = 1 đơn; yêu cầu cùng người chuyển hoặc có SĐT)
4. Số tiền đúng + ngày ±35
5. 1 GD trả 2 đơn (chung nhà; cùng SĐT hoặc cùng ngày + sales)

Tự loại khỏi doanh thu: chuyển nội bộ PalFish, lãi tiền gửi, hoàn tiền,
khoản gộp VIMO / Ngân Lượng. Khớp theo từng tháng với pool sao kê nới
±5 ngày để xử lý giao dịch vắt tháng.

## Các nhóm lỗi trên dashboard
| Nhóm | Ý nghĩa | Việc cần làm |
|---|---|---|
| ✅ Khớp đúng | Trùng số tiền (+ giờ/ngày) | — |
| 🟡 Lệch số tiền | Tìm thấy GD đúng thời điểm nhưng sai số — cột ⚠️ LỆCH là khoản chênh chính xác | Đối chiếu cọc/chuyển thừa thiếu |
| 🟡 Khớp cần xem | Khớp qua SĐT / lệch ngày / gộp cọc / chung nhà | Xác nhận nhanh |
| 🟠 Trả qua cổng | Gateway = VIMO/Ngân Lượng — tiền về dạng cục | Đối soát bằng file settlement của cổng |
| 🔴 Không tìm thấy | Không có GD nào khớp trong sao kê đã nạp | Về TK khác? chưa chuyển? ghi sai? |
| 🔴 Tiền vào không có đơn | Bank có tiền, report không có đơn | Truy ai nhận khoản này |

Lưu ý: cột `Payment Method` (1st/2nd/...) là **lần thanh toán thứ mấy**,
không dùng để suy ra thẻ tín dụng; nhận diện cổng thanh toán dựa trên
cột `Gateway`.

## Kết quả chạy thử trên dữ liệu Q1/2026
- HN: 882 đơn khớp đúng, 100 đơn 🟡 lệch số tiền (~108 triệu tổng lệch,
  chỉ rõ từng khoản), 297 đơn 🟡 cần xem, 98 đơn 🟠 qua cổng,
  448 đơn 🔴 chưa tìm thấy (~5,6 tỷ — phần lớn do thiếu sao kê các
  tài khoản nhận khác và các khoản trả góp nhiều lần).
- HCM: 72 khớp + 18 cần xem; 69 đơn 🔴 (~497 triệu) tiền về các tài khoản
  chưa có sao kê (xem cột Gateway để biết ngân hàng nào cần xin sao kê).
