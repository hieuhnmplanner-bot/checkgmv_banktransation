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


## Sửa lỗi quan trọng (từ feedback dữ liệu)  ⭐
1. **Bug đảo ngày/tháng**: cột `bank day` là object chứa datetime; bước parse
   dự phòng từng đảo ngày↔tháng với giá trị mơ hồ (ngày ≤ 12), khiến nhiều đơn
   tháng 1 bị đẩy sang tháng khác và báo 🔴 oan. Đã sửa: nhận diện datetime gốc,
   không ép qua chuỗi. Sau khi sửa, ✅ khớp đúng tăng mạnh.
2. **Bug cắt số điện thoại**: `norm_phone` cắt nhầm chữ số "1" đầu như mã quốc
   gia (vd 1079347605 → 79347605). Đã bỏ "1" khỏi danh sách mã quốc gia.
3. **Đơn trả qua cổng (VIMO/thẻ)**: không còn ép khớp vào 1 giao dịch lẻ trùng
   SĐT; xếp thẳng vào 🟠 "trả qua thẻ/cổng" để đối soát bằng file settlement.
4. **Thu nhiều đợt**: đơn lần TT thứ 2+ còn thiếu một phần → nhóm mới
   🟢 "Thu nhiều đợt — phần còn lại là cọc/đợt trước", không tính là mất tiền
   (phần thiếu thường là cọc đóng ở kỳ trước, có thể ngoài phạm vi nghiên cứu).

### Ca chưa tự khớp được (cần sửa ở khâu nhập liệu)
Phụ huynh chuyển 1 lần cho 2 bé nhưng sao kê điền tay chỉ điền **1 SĐT** →
giao dịch mang SĐT bé kia, không tìm theo SĐT bé này được. Khắc phục gốc: điền
đủ SĐT cả 2 bé, hoặc liên kết theo phụ huynh/UID trong mô hình dữ liệu chuẩn hóa.


## Tự tìm "anh em chung 1 lần chuyển"  ⭐
Phụ huynh chuyển 1 lần cho nhiều bé, sao kê chỉ điền 1 SĐT. Engine tự tìm bằng:
1. Các đơn có **cùng dấu thời gian thanh toán** (bank day + bank time) là cùng
   một lần chuyển → gộp tổng, tìm giao dịch = tổng (ưu tiên trùng giờ trong ngày).
2. **Khóa chủ giao dịch**: giao dịch đã gắn SĐT cụ thể (qua file điền tay hoặc
   memo) chỉ được khớp cho đơn của SĐT đó / nhóm anh em chứa nó — không cho đơn
   khác trùng số tiền chiếm. Nhờ vậy giao dịch "Khangbang" 9.080.000 được giữ
   đúng cho cặp Khang + Băng thay vì bị 1 trong 30 đơn lẻ 9.080.000 lấy mất.
Ví dụ thực: Hy Băng (986037282) + Nguyên Khang (913627413) → khớp đúng vào 1 GD.


## Dùng Gateway (ngân hàng gửi) làm tín hiệu  ⭐
- **Kiểm chứng anh em**: các đơn anh em chung 1 lần chuyển phải cùng Gateway
  (cùng ngân hàng gửi) — chặn việc gộp nhầm 2 đơn trùng giờ nhưng khác nguồn.
- **Pass anh em theo ngày+Gateway**: khi report ghi giờ thanh toán các bé lệch
  nhau, gom theo cùng ngày + cùng Gateway, thử cặp/bộ ba cộng đúng 1 giao dịch
  (chỉ nhận khi giao dịch đó DUY NHẤT trong cửa sổ -> an toàn). Không cần memo
  ghi tên vẫn khớp được.
- **Ví điện tử**: Momo, Zalopay, ViettelPay/Viettel Money, VIMO, Ngân Lượng →
  xếp nhóm 🟠 (tiền về dạng cục qua cổng, không phải credit ngân hàng lẻ;
  đối soát bằng file settlement của cổng).

Lưu ý: ngân hàng GỬI không xuất hiện trong nội dung sao kê (chỉ có mã napas/FT),
nên Gateway dùng để kiểm chứng & gom nhóm, không dùng để dò ngược từ memo.


## Ô tìm kiếm + 2 tab tra cứu hai chiều  ⭐
- **Ô tìm SĐT/UID** (trên cùng): lọc nhanh mọi tab theo số điện thoại hoặc UID.
- **Tab "Nguồn doanh thu điền tay"**: toàn bộ đơn SM Hà Nội + HCM với các cột
  bank time, Gateway, User Name, Phone, UID, Pay Time, Real Pay(VND) + đánh dấu
  Tìm thấy bên sao kê chưa, Trạng thái khớp, Lệch, và mô tả ngắn cách khớp.
- **Tab "Sao Kê Ngân Hàng"**: toàn bộ giao dịch 2 file HN + HCM (cả ghi nợ) với
  NGÀY GIAO DỊCH, PHÁT SINH NỢ/CÓ, ĐƠN VỊ THỤ HƯỞNG/CHUYỂN, NỘI DUNG,
  BÚT TOÁN (HCM dùng cột Doc No/Số CT thay thế) + đánh dấu gắn được với đơn nào,
  trạng thái, lệch, mô tả cách khớp. Hai tab này đối chiếu hai chiều giúp soi
  nhanh cái nào đúng/sai.


## Cập nhật xử lý cổng + combo + tìm kiếm chéo  ⭐
- **Cổng/thẻ tín dụng**: nhận diện thêm Payoo, 9Pay, VNPay, OnePay (cùng VIMO,
  Momo, Zalopay, ViettelPay...). Đơn qua cổng xếp nhóm 🟠 và KHÔNG hiển thị
  số tiền như khoản lệch (tiền về qua settlement của cổng, không phải credit lẻ).
- **Combo nhiều gói cùng người**: nhiều gói cùng UID + cùng giờ thanh toán mà
  phần lệch bù trừ nhau (tổng khớp) -> gộp thành 🟢 "Khớp combo nhiều gói",
  lech = 0 (vd 366346066: 9.275.000 + 4.740.000 = 10.800.000 + 3.215.000).
- **Tìm kiếm chéo**: gõ SĐT/UID ở tab "Nguồn doanh thu điền tay" thì tab
  "Sao Kê Ngân Hàng" cũng tự lọc đúng giao dịch đã khớp với đơn đó.
- **Tab Nguồn doanh thu điền tay**: cột "Lệch số tiền" hiển thị rõ giá trị lệch
  từng đơn (trống với đơn qua cổng).
- Metric tổng quan: "Đơn cần xử lý" chỉ đếm 🔴 + 🟡 lệch thật; đơn qua cổng
  tách riêng, không tính là tiền lệch.


## Xử lý thêm các ca nhiều giao dịch / tag sai SĐT  ⭐
- **Gộp nhiều khoản cùng SĐT** (cọc + hoàn thiện cùng ngày): 1 đơn trả bằng
  nhiều giao dịch cùng gắn đúng SĐT, tổng khớp -> gộp, lech 0
  (vd 3305598868: 40.000 + 16.920.000 = 16.960.000).
- **Combo nhiều gói cùng người**: vd 366346066: 2 gói 9.275.000 + 4.740.000
  = 2 GD 10.800.000 + 3.215.000, tổng khớp -> lech 0.
- **Khớp qua tên trong nội dung CK**: khi file điền tay gắn SĐT sai nhưng memo
  ghi đúng tên khách + đúng số tiền + đúng ngày -> khớp (vd 914290611 memo
  "be Mai Khanh"). An toàn vì đòi đủ tên + đúng tiền + ngày ±2 + ứng viên duy nhất.

### Ca cố ý KHÔNG tự khớp (cần sửa khâu nhập liệu)
983888631: giao dịch đúng số tiền nhưng file điền tay gắn SĐT của KHÁCH KHÁC,
và memo không ghi tên khách này. Tự gán sẽ rủi ro lấy nhầm tiền của người khác,
nên để 🔴 chờ kiểm tra. Khắc phục gốc: sửa SĐT trong file điền tay cho đúng.


## Pass khớp KHÔNG dựa SĐT (số tiền + ngày + nội dung)  ⭐
Cho các ca file điền tay gắn SĐT sai (vd 983888631, 914290611):
- **Khớp qua tên trong nội dung CK** (Pass B): đúng số tiền + ngày ±2 + đủ tên
  khách trong memo + ứng viên duy nhất -> khớp (vd 914290611 memo "be Mai Khanh").
- **Khớp số tiền + ngày 1-1 duy nhất** (Pass C): khi đúng 1 đơn chưa khớp và
  đúng 1 giao dịch tự do cùng số tiền trong ±2 ngày -> ghép, BỎ QUA SĐT (vì có
  thể gắn sai). Xếp nhóm 🟡 "cần xem" để kiểm chứng (vd 983888631).
Hai pass này chạy SAU cùng nên không ảnh hưởng khớp chắc chắn phía trước.

Lưu ý: nếu đang xem bản cũ, các case 366346066 / 3305598868 vẫn hiện lệch hoặc
ghép nhiều giao dịch. Sau khi deploy bản mới nhất, search 366346066 ở tab Sao Kê
chỉ còn đúng 2 giao dịch (3.215.000 + 10.800.000).
