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

## Engine khớp tự động (thứ tự ưu tiên bằng chứng)
Engine chạy bằng chứng MẠNH trước, yếu sau (bằng chứng mạnh thắng):
0. **Giờ giao dịch** (bank day + bank time): đúng số tiền trong ±60′ → Khớp
   đúng; cùng thời điểm ±5′ nhưng số tiền khác (≤20%) → 🟡 Lệch số tiền
1. Số tiền đúng + ngày ±N (mặc định ±3)
2. SĐT của đơn trong memo + đúng số tiền
3. Cọc + chuyển nốt (2 GD = 1 đơn; cùng người chuyển hoặc có SĐT)
4. **SĐT trong memo (neo mạnh)** — kể cả số tiền lệch: credit lớn hơn đơn →
   🟢 GD gộp (1 lần CK trả nhiều bé, cần tách tay); credit nhỏ hơn → 🟡 cọc/thiếu
5. 1 GD trả 2 đơn (chung nhà; cùng SĐT hoặc cùng ngày + sales)
6. **Chốt cuối**: số tiền đúng + ngày ±35 NHƯNG chỉ khi số tiền đó DUY NHẤT
   trong cửa sổ (tránh khớp nhầm sang khách khác trùng số tiền)

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


## Cầu nối SĐT từ file điền tay (mục 5)  ⭐ MỚI
File điền tay = từng dòng sao kê đã được sale gắn SĐT khách (97% dòng có SĐT).
Khi bạn nạp file này (mục 5), engine nối SĐT vào từng giao dịch ngân hàng
theo **timestamp** (số tiền trong file điền tay có thể bị sửa tay nên không
dùng để nối, chỉ dùng giờ giao dịch). Nhờ đó khớp được theo SĐT cả khi nội
dung chuyển khoản của ngân hàng không ghi số điện thoại.

Tác động trên dữ liệu Q1 (HN): 🔴 Không tìm thấy giảm **490 → 228** đơn,
tiền chưa rõ giảm từ ~5,78 tỷ xuống ~2,71 tỷ. Cột "Số tiền đã đặt cọc" trong
file điền tay cũng được dùng để nhận diện đơn "đã trừ cọc (đủ tiền)".


## Bể sao kê chung — dò chéo tài khoản HN ↔ HCM  ⭐ MỚI
Team HCM lúc thì cho khách chuyển vào tài khoản HCM, lúc thì vào tài khoản HN.
Vì vậy engine gộp **tất cả sao kê (HN + HCM) thành một bể chung**, mỗi đơn được
dò trên cả hai tài khoản. Cột **"Tiền về TK"** trong tab chi tiết cho biết tiền
thực về tài khoản nào.

Tác động trên Q1: đơn HCM 🔴 giảm **64 → 32**; trong số đơn HCM khớp được,
71 đơn tiền về TK Hà Nội, 56 đơn về TK HCM. Khi có thêm sao kê tài khoản khác,
chỉ cần nạp vào là bể chung tự mở rộng, đơn nào tiền về đó cũng khớp được.

File điền tay hiện khớp theo timestamp với sao kê HN (sao kê HCM/VCB chỉ có
ngày, không có giờ) — nên nó phủ luôn các đơn HCM chuyển vào tài khoản HN.
