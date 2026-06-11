# -*- coding: utf-8 -*-
"""
Dashboard Đối Soát GMV vs Sao Kê Ngân Hàng — PalFish
Chạy: streamlit run app.py
Nguồn dữ liệu: Google Sheets (link export CSV) hoặc upload file.
"""
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from recon_engine import (load_orders, load_bank, classify_nonrevenue,
                          match_orders_to_bank, error_groups,
                          audit_manual_file, attach_manual_phone)

st.set_page_config(page_title="Đối soát GMV vs Bank", page_icon="🏦",
                   layout="wide")

GROUP_COLORS = {
    "✅ Khớp đúng": "#2e7d32",
    "🟢 Khớp qua SĐT — giao dịch gộp (cần tách thủ công)": "#66bb6a",
    "🟡 Lệch số tiền (tìm thấy giao dịch, sai số)": "#fdd835",
    "🟡 Khớp nhưng cần xem (SĐT/lệch ngày/gộp cọc)": "#f9a825",
    "🟠 Không thấy — trả qua thẻ/cổng thanh toán (check file cổng)": "#ef6c00",
    "🔴 Không tìm thấy trong sao kê": "#c62828",
}


def fmt_vnd(x):
    try:
        return f"{x:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return ""


def gsheet_to_csv_url(url):
    """Chuyển link Google Sheet thường thành link export CSV (giữ gid)."""
    url = (url or "").strip()
    if not url:
        return None
    if "export?format=csv" in url or url.endswith(".csv"):
        return url
    if "/d/" in url:
        sheet_id = url.split("/d/")[1].split("/")[0]
        gid = "0"
        if "gid=" in url:
            gid = url.split("gid=")[1].split("&")[0].split("#")[0]
        return (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
                f"/export?format=csv&gid={gid}")
    return url


@st.cache_data(ttl=600, show_spinner=False)
def read_source(url):
    return pd.read_csv(gsheet_to_csv_url(url))


ORDER_KEY_COLS = {"REAL PAY(VND)", "PHONE", "UID", "PAY TIME"}
BANK_KEY_COLS = {"PHAT SINH CO", "SO TIEN GHI CO", "CREDIT", "NOI DUNG"}


def pick_best_sheet(xls_file, kind):
    """Tự tìm sheet đúng trong file Excel nhiều sheet (vd INCOME / REVENUE)."""
    from recon_engine import strip_accents
    keys = ORDER_KEY_COLS if kind == "orders" else BANK_KEY_COLS
    xl = pd.ExcelFile(xls_file)
    best, best_score = None, -1
    for sh in xl.sheet_names:
        try:
            head = xl.parse(sh, nrows=1)
        except Exception:  # noqa: BLE001
            continue
        cols = {strip_accents(str(c)).strip() for c in head.columns}
        score = sum(any(k in c for c in cols) for k in keys)
        if score > best_score:
            best, best_score = sh, score
    if best is None or best_score < 2:
        return None, xl.sheet_names
    return best, xl.sheet_names


def get_df(label, key, kind="orders", help_txt=""):
    """1 nguồn dữ liệu = link Google Sheet hoặc upload CSV/Excel
    (Excel nhiều sheet sẽ tự dò đúng sheet, vd INCOME / REVENUE)."""
    with st.sidebar.expander(label, expanded=False):
        url = st.text_input("Link Google Sheet (tab tương ứng)",
                            key=f"url_{key}", help=help_txt)
        up = st.file_uploader("hoặc upload CSV / Excel",
                              type=["csv", "xlsx", "xlsm"],
                              key=f"up_{key}")
    if up is not None:
        if up.name.lower().endswith(".csv"):
            return pd.read_csv(up)
        sheet, all_sheets = pick_best_sheet(up, kind)
        with st.sidebar.expander(label, expanded=False):
            pass
        chosen = st.sidebar.selectbox(
            f"Sheet cho «{label}»", all_sheets,
            index=all_sheets.index(sheet) if sheet else 0,
            key=f"sh_{key}")
        return pd.read_excel(up, sheet_name=chosen)
    if url:
        try:
            return read_source(url)
        except Exception as e:  # noqa: BLE001
            st.sidebar.error(f"{label}: không đọc được link ({e})")
    return None


@st.cache_data(ttl=600, show_spinner="Đang đối soát...")
def run_recon(orders_specs, bank_specs, date_window, month_from, month_to,
              manual_csv=None):
    """Khớp TẤT CẢ đơn (mọi vùng) với BỂ SAO KÊ CHUNG (mọi tài khoản).

    orders_specs: list các (csv, region)
    bank_specs:   list các (csv, account)
    Một đơn HCM có thể khớp giao dịch ở tài khoản HN và ngược lại — tiền về
    tài khoản nào sẽ hiện ở cột "Tiền về TK".
    """
    orders = pd.concat(
        [load_orders(pd.read_csv(io.StringIO(c)), reg)
         for c, reg in orders_specs], ignore_index=True)
    bank = pd.concat(
        [load_bank(pd.read_csv(io.StringIO(c)), acc)
         for c, acc in bank_specs], ignore_index=True)
    bank["txn_id"] = [f"{a}-{i}" for i, a in enumerate(bank["account"])]
    manual_df = (pd.read_csv(io.StringIO(manual_csv))
                 if manual_csv else None)
    bank = attach_manual_phone(bank, manual_df)
    bank = classify_nonrevenue(bank)

    orders = orders[(orders["month"] >= month_from) &
                    (orders["month"] <= month_to)]
    bank = bank[(bank["month"] >= month_from) &
                (bank["month"] <= month_to)].copy()

    o_all = []
    used_txn = set()
    for m in sorted(set(orders["month"].dropna())):
        m_start = pd.Period(m).start_time - pd.Timedelta(days=5)
        m_end = pd.Period(m).end_time + pd.Timedelta(days=5)
        pool = bank[(bank["txn_date"] >= m_start) &
                    (bank["txn_date"] <= m_end) &
                    (~bank["txn_id"].isin(used_txn))]
        om, bm = match_orders_to_bank(
            orders[orders["month"] == m], pool, date_window=date_window)
        og, _ = error_groups(om, bm)
        # gắn tài khoản tiền thực về (theo giao dịch đã khớp)
        txn_acc = bm.set_index("txn_id")["account"].to_dict()
        og["paid_into"] = og["matched_txn"].astype(str).str.split(
            r"[ +|]").str[0].map(txn_acc)
        o_all.append(og)
        used_txn.update(bm.loc[bm["used_by"].notna(), "txn_id"])

    o_res = (pd.concat(o_all, ignore_index=True)
             if o_all else orders.iloc[0:0])
    bank["bank_group"] = ""
    matched_mask = bank["txn_id"].isin(used_txn)
    bank.loc[matched_mask, "bank_group"] = "✅ Đã gắn với đơn"
    nz = (~matched_mask) & (bank["nonrev_type"] != "")
    bank.loc[nz, "bank_group"] = ("⚪ Không phải doanh thu (" +
                                  bank.loc[nz, "nonrev_type"] + ")")
    rest = bank["bank_group"] == ""
    months_with_orders = set(orders["month"].dropna())
    no_rep = rest & ~bank["month"].isin(months_with_orders)
    bank.loc[no_rep, "bank_group"] = "⚪ Tháng chưa có report đơn hàng"
    bank.loc[bank["bank_group"] == "", "bank_group"] = \
        "🔴 Tiền vào KHÔNG có đơn nào nhận"
    return o_res, bank


# ============================================================ SIDEBAR
st.sidebar.title("⚙️ Nguồn dữ liệu")
st.sidebar.caption(
    "Dán link Google Sheet (mở quyền *Anyone with the link – Viewer*). "
    "Mỗi dataset 1 tab, giữ nguyên cấu trúc cột như file hiện tại.")

df_orders_hn = get_df("1️⃣ Report đơn HN (SM — sheet INCOME)", "ohn",
                      "orders",
                      "Cần cột: bank day, Real Pay(VND), Phone, Sales")
df_bank_hn = get_df("2️⃣ Sao kê ngân hàng HN", "bhn", "bank",
                    "Cần cột: NGÀY GIAO DỊCH, PHÁT SINH CÓ, NỘI DUNG")
df_orders_hcm = get_df("3️⃣ Report đơn HCM (sheet REVENUE)", "ohcm", "orders")
df_bank_hcm = get_df("4️⃣ Sao kê ngân hàng HCM", "bhcm", "bank")
df_manual = get_df("5️⃣ Sao kê điền tay (tùy chọn)", "manual", "bank",
                   "Dùng cho tab kiểm tra toàn vẹn file điền tay")

st.sidebar.divider()
c_a, c_b = st.sidebar.columns(2)
month_from = c_a.text_input("Từ tháng", "2026-01")
month_to = c_b.text_input("Đến tháng", "2026-03")
date_window = st.sidebar.slider("Cửa sổ khớp ngày (± ngày)", 1, 10, 3)
if st.sidebar.button("🔄 Tải lại dữ liệu"):
    st.cache_data.clear()
    st.rerun()

# ============================================================ RUN
st.title("🏦 Đối soát Doanh thu vs Sao kê Ngân hàng")

manual_csv = df_manual.to_csv(index=False) if df_manual is not None else None
orders_specs = []
if df_orders_hn is not None:
    orders_specs.append((df_orders_hn.to_csv(index=False), "HN"))
if df_orders_hcm is not None:
    orders_specs.append((df_orders_hcm.to_csv(index=False), "HCM"))
bank_specs = []
if df_bank_hn is not None:
    bank_specs.append((df_bank_hn.to_csv(index=False), "HN"))
if df_bank_hcm is not None:
    bank_specs.append((df_bank_hcm.to_csv(index=False), "HCM"))

if not orders_specs or not bank_specs:
    st.info("👈 Cần ít nhất 1 **Report đơn** và 1 **Sao kê ngân hàng** "
            "ở thanh bên trái để bắt đầu. Nạp cả sao kê HN và HCM để dò "
            "chéo (đơn HCM có thể nhận tiền vào tài khoản HN và ngược lại).")
    st.stop()

orders, bank = run_recon(orders_specs, bank_specs, date_window,
                         month_from, month_to, manual_csv)

months = sorted(orders["month"].dropna().unique())
regions = sorted(orders["region"].unique())

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Tổng quan theo tháng", "🔍 Chi tiết khoản sai",
    "🏦 Tiền vào không có đơn", "📝 Kiểm tra file điền tay", "❓ Hướng dẫn"])

# ============================================================ TAB 1
with tab1:
    c1, c2 = st.columns([1, 3])
    sel_region = c1.multiselect("Khu vực", regions, default=regions)
    o = orders[orders["region"].isin(sel_region)]
    b = bank[bank["account"].isin(sel_region)]

    n_err = (~o["error_group"].str.startswith("✅")).sum()
    vnd_err = o.loc[~o["error_group"].str.startswith("✅"), "lech"].abs().sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng đơn", f"{len(o):,}")
    m2.metric("Doanh thu ghi nhận", fmt_vnd(o["amount"].sum()) + " đ")
    m3.metric("Đơn có vấn đề", f"{n_err:,}",
              delta=f"-{n_err / max(len(o), 1):.0%} tổng đơn",
              delta_color="inverse")
    m4.metric("Tiền lệch cần xử lý", fmt_vnd(vnd_err) + " đ")

    pv_cnt = (o.pivot_table(index="month", columns="error_group",
                            values="order_id", aggfunc="count", fill_value=0)
              .reindex(columns=list(GROUP_COLORS), fill_value=0))
    pv_vnd = (o.pivot_table(index="month", columns="error_group",
                            values="lech",
                            aggfunc=lambda s: s.abs().sum(), fill_value=0)
              .reindex(columns=list(GROUP_COLORS), fill_value=0))

    cc1, cc2 = st.columns(2)
    long_cnt = pv_cnt.reset_index().melt("month", var_name="Nhóm",
                                         value_name="Số đơn")
    fig = px.bar(long_cnt, x="month", y="Số đơn", color="Nhóm",
                 color_discrete_map=GROUP_COLORS,
                 title="Số đơn theo nhóm lỗi / tháng")
    fig.update_layout(legend_orientation="h", legend_y=-0.25,
                      xaxis_title=None)
    cc1.plotly_chart(fig, use_container_width=True)

    long_vnd = pv_vnd.drop(columns=["✅ Khớp đúng"]).reset_index().melt(
        "month", var_name="Nhóm", value_name="VND lệch")
    fig2 = px.bar(long_vnd, x="month", y="VND lệch", color="Nhóm",
                  color_discrete_map=GROUP_COLORS,
                  title="Giá trị lệch (VND) theo nhóm lỗi / tháng")
    fig2.update_layout(legend_orientation="h", legend_y=-0.25,
                       xaxis_title=None)
    cc2.plotly_chart(fig2, use_container_width=True)

    st.subheader("Bảng tổng hợp: số đơn (và VND lệch) theo nhóm × tháng")
    summary = pv_cnt.astype(str)
    for col in pv_vnd.columns:
        if col == "✅ Khớp đúng":
            continue
        summary[col] = (pv_cnt[col].astype(str) + " đơn — " +
                        pv_vnd[col].map(fmt_vnd) + " đ")
    st.dataframe(summary, use_container_width=True)

    st.subheader("Phía ngân hàng")
    bsum = (b.groupby(["month", "bank_group"])["credit"]
            .agg(GD="count", VND="sum").reset_index())
    bsum["VND"] = bsum["VND"].map(fmt_vnd)
    st.dataframe(bsum, use_container_width=True, hide_index=True)

# ============================================================ TAB 2
with tab2:
    f1, f2, f3 = st.columns(3)
    sel_m = f1.selectbox("Tháng", ["Tất cả"] + list(months))
    sel_g = f2.selectbox("Nhóm lỗi", ["Tất cả lỗi (bỏ khớp đúng)"] +
                         [g for g in GROUP_COLORS if not g.startswith("✅")])
    sel_r = f3.multiselect("Khu vực", regions, default=regions, key="t2r")

    d = orders[orders["region"].isin(sel_r)]
    if sel_m != "Tất cả":
        d = d[d["month"] == sel_m]
    if sel_g.startswith("Tất cả"):
        d = d[~d["error_group"].str.startswith("✅")]
    else:
        d = d[d["error_group"] == sel_g]

    st.markdown(f"**{len(d)} đơn — tổng lệch "
                f"{fmt_vnd(d['lech'].abs().sum())} đ**")
    show = d[["month", "region", "paid_into", "order_date", "customer",
              "phone", "uid", "package", "sales", "amount", "expected_bank",
              "matched_amount", "lech", "match_status", "matched_txn",
              "pay_method", "note"]].copy()
    show.columns = ["Tháng", "KV đơn", "Tiền về TK", "Ngày", "Khách", "SĐT",
                    "UID", "Gói", "Sales", "Real Pay", "Tiền phải về bank",
                    "Tiền tìm thấy", "⚠️ LỆCH", "Trạng thái khớp",
                    "Giao dịch gắn với", "Hình thức TT", "Note"]
    for c in ["Real Pay", "Tiền phải về bank", "Tiền tìm thấy", "⚠️ LỆCH"]:
        show[c] = show[c].map(fmt_vnd)
    st.dataframe(show, use_container_width=True, hide_index=True, height=520)
    st.download_button("⬇️ Tải danh sách này (CSV)",
                       show.to_csv(index=False).encode("utf-8-sig"),
                       file_name="chi_tiet_khoan_sai.csv")

# ============================================================ TAB 3
with tab3:
    st.caption("Tiền đã vào tài khoản nhưng không gắn được với đơn nào — "
               "kiểm tra: cọc cho đơn tương lai, đơn quên ghi nhận, "
               "tiền của team khác, hoặc khoản bất thường.")
    f1, f2 = st.columns(2)
    sel_m3 = f1.selectbox("Tháng", ["Tất cả"] + list(months), key="t3m")
    only_unknown = f2.checkbox("Chỉ hiện 🔴 không rõ nguồn", value=True)
    bb = bank.copy()
    if sel_m3 != "Tất cả":
        bb = bb[bb["month"] == sel_m3]
    if only_unknown:
        bb = bb[bb["bank_group"].str.startswith("🔴")]
    st.markdown(f"**{len(bb)} giao dịch — {fmt_vnd(bb['credit'].sum())} đ**")
    show_b = bb[["month", "account", "txn_date", "credit", "counterparty",
                 "detail", "bank_group"]].copy()
    show_b["credit"] = show_b["credit"].map(fmt_vnd)
    show_b.columns = ["Tháng", "TK", "Ngày GD", "Số tiền", "Người chuyển",
                      "Nội dung", "Phân loại"]
    st.dataframe(show_b, use_container_width=True, hide_index=True,
                 height=520)
    st.download_button("⬇️ Tải danh sách này (CSV)",
                       show_b.to_csv(index=False).encode("utf-8-sig"),
                       file_name="tien_vao_khong_co_don.csv")

# ============================================================ TAB 4
with tab4:
    if df_manual is None or df_bank_hn is None:
        st.info("Cần cung cấp cả **Sao kê điền tay** (mục 5) và "
                "**Sao kê ngân hàng HN** (mục 2) để chạy kiểm tra này.")
    else:
        edited, deleted, dups = audit_manual_file(df_manual, df_bank_hn)
        c1, c2, c3 = st.columns(3)
        c1.metric("Dòng bị sửa số / gõ tay", len(edited))
        c2.metric("Dòng bị xóa khỏi file", len(deleted))
        c3.metric("Dòng bị nhân đôi", len(dups))

        st.subheader("✏️ Dòng có số tiền KHÁC sao kê gốc")
        if len(edited):
            e = edited.copy()
            for c in ["Số trong file điền tay", "Số thực trên sao kê",
                      "Chênh lệch"]:
                e[c] = e[c].map(lambda x: fmt_vnd(x) if pd.notna(x) else "")
            st.dataframe(e, use_container_width=True, hide_index=True)
        st.subheader("🗑️ Dòng có trên sao kê gốc nhưng KHÔNG có trong file")
        if len(deleted):
            dd = deleted[["txn_date", "credit", "counterparty",
                          "detail"]].copy()
            dd["credit"] = dd["credit"].map(fmt_vnd)
            st.dataframe(dd, use_container_width=True, hide_index=True)
        st.subheader("👯 Dòng bị nhân đôi (đếm doanh thu 2 lần)")
        if len(dups):
            dp = dups[["txn_date", "credit", "counterparty"]].copy()
            dp["credit"] = dp["credit"].map(fmt_vnd)
            st.dataframe(dp, use_container_width=True, hide_index=True)

# ============================================================ TAB 5
with tab5:
    st.markdown("""
### Cách dùng
1. Đưa dữ liệu lên Google Sheets, mỗi dataset 1 tab, **giữ nguyên tên cột**
   như file đang dùng:
   - **Report đơn** (SM report / HCM report): cần `Ngày` hoặc `bank day`,
     `Real Pay(VND)`, `Mony via bank` (nếu có), `Phone`, `Sales`, `Package`,
     `Payment Method`
   - **Sao kê ngân hàng**: cần `NGÀY GIAO DỊCH` (hoặc `Ngày hiệu lực`),
     `PHÁT SINH CÓ` (hoặc `Số tiền ghi có`), `NỘI DUNG`,
     `ĐƠN VỊ THỤ HƯỞNG/ĐƠN VỊ CHUYỂN`
2. Share sheet ở chế độ **Anyone with the link → Viewer**, copy link từng tab
   (URL có `gid=`) dán vào thanh bên trái.
3. Hàng tháng chỉ cần **paste thêm dữ liệu vào Google Sheet** rồi bấm
   *Tải lại dữ liệu* — dashboard tự đối soát.

### Các nhóm lỗi
| Nhóm | Ý nghĩa | Việc cần làm |
|---|---|---|
| ✅ Khớp đúng | Số tiền + ngày trùng sao kê | Không cần làm gì |
| 🟡 Khớp cần xem | Khớp qua SĐT / lệch ngày / gộp cọc+nốt / 1 GD trả 2 đơn | Xác nhận nhanh |
| 🟠 Trả qua thẻ/cổng | Đơn 2nd/3rd/4th — tiền về dạng cục qua VIMO/Ngân Lượng | Đối soát bằng file settlement của cổng |
| 🔴 Không tìm thấy | Không có giao dịch nào khớp trong sao kê đã nạp | Kiểm tra: về TK khác? ghi sai số? chưa chuyển? |
| 🔴 Tiền vào không có đơn | Bank có tiền nhưng report không có đơn | Truy ai nhận khoản này |

### Lưu ý
- Engine khớp **theo từng tháng** (theo `NGÀY GIAO DỊCH`); giao dịch cuối
  tháng hạch toán sang tháng sau vẫn được tính đúng tháng giao dịch.
- Giao dịch nội bộ PalFish, lãi tiền gửi, khoản VIMO/Ngân Lượng gộp được
  tự loại khỏi doanh thu (hiện ở tab 3 với nhãn ⚪).
- Muốn khớp tự động tốt hơn nữa: yêu cầu khách ghi **SĐT hoặc UID** vào
  nội dung chuyển khoản.
""")
