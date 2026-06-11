# -*- coding: utf-8 -*-
"""
Recon engine: đối soát đơn hàng (report) vs sao kê ngân hàng.
Tách riêng khỏi UI để test được và tái sử dụng (Baserow pipeline sau này).
"""
import re
import unicodedata
from collections import Counter

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- helpers

def vnd(series):
    """Parse số kiểu Việt Nam: 8.500.000 / '1,226' / ' 4500000 ' -> float."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    s = series.astype(str).str.strip()
    s = s.str.replace(".", "", regex=False).str.replace(",", "", regex=False)
    out = pd.to_numeric(s, errors="coerce")
    # nếu chuỗi gốc dạng "7950000.0" thì việc bỏ dấu chấm đã nhân 10 — sửa lại
    dot_dec = series.astype(str).str.match(r"^\s*\d+\.\d{1,2}\s*$")
    if dot_dec.any():
        out.loc[dot_dec] = pd.to_numeric(series[dot_dec], errors="coerce")
    return out


def parse_date_any(series):
    """Chấp nhận dd/mm/yyyy [hh:mm:ss], yyyy/m/d, datetime sẵn có."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    s = series.astype(str).str.strip().str.replace("\n", " ", regex=False)
    out = pd.to_datetime(s, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d"):
        mask = out.isna()
        if not mask.any():
            break
        out.loc[mask] = pd.to_datetime(s[mask], format=fmt, errors="coerce")
    mask = out.isna()
    if mask.any():
        out.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
    return out


def norm_phone(series):
    """84-937362462 / 0937362462 / 84937362462 -> '937362462' (bỏ mã nước, số 0 đầu)."""
    s = series.fillna("").astype(str)
    s = s.where(~s.str.lower().isin(["nan", "none"]), "")
    s = s.str.replace(r"[^\d]", "", regex=True).str.lstrip("0")
    # bỏ mã nước phổ biến (84 VN, 81 JP, 82 KR, 49 DE...) nếu còn dài hơn 9 số
    def strip_cc(x):
        if len(x) > 9:
            for cc in ("84", "81", "82", "49", "1"):
                if x.startswith(cc) and len(x) - len(cc) >= 8:
                    return x[len(cc):].lstrip("0")
        return x
    return s.apply(strip_cc).replace("", np.nan)


def strip_accents(text):
    if not isinstance(text, str):
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn").upper()


PHONE_IN_TEXT = re.compile(r"0\d{8,10}|84\d{9,10}")


def phones_from_text(text):
    """Bắt SĐT xuất hiện trong nội dung chuyển khoản."""
    if not isinstance(text, str):
        return []
    found = PHONE_IN_TEXT.findall(text.replace(" ", ""))
    return list(norm_phone(pd.Series(found)).dropna().unique()) if found else []


# ---------------------------------------------------------------- loaders

def load_orders(df, region):
    """Chuẩn hóa report đơn hàng (SM report HN hoặc HCM report) về 1 schema."""
    df = df.copy()
    cols = {c.strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return df[cols[n]]
        return pd.Series(np.nan, index=df.index)

    out = pd.DataFrame(index=df.index)
    out["region"] = region
    out["order_date"] = parse_date_any(pick("Ngày", "bank day"))
    pay_time = parse_date_any(pick("Pay Time"))
    out["order_date"] = out["order_date"].fillna(pay_time)
    out["pay_time"] = pay_time
    # timestamp đầy đủ = bank day + bank time (nếu report có ghi giờ GD)
    bt = pick("bank time").astype(str).str.strip()
    bt = bt.where(bt.str.match(r"^\d{1,2}:\d{2}(:\d{2})?$"), np.nan)
    has_ts = bt.notna() & out["order_date"].notna()
    out["order_ts"] = pd.NaT
    if has_ts.any():
        out.loc[has_ts, "order_ts"] = pd.to_datetime(
            out.loc[has_ts, "order_date"].dt.strftime("%Y-%m-%d") + " " +
            bt[has_ts], errors="coerce")
    out["amount"] = vnd(pick("Real Pay(VND)", "Real Pay (VND)", "Real Pay"))
    out["expected_bank"] = vnd(pick("Mony via bank", "Money via bank"))
    out["expected_bank"] = out["expected_bank"].fillna(out["amount"])
    out["phone"] = norm_phone(pick("Số điện thoại final ghép", "Phone"))
    phone2 = norm_phone(pick("Phone"))
    out["phone"] = out["phone"].fillna(phone2)
    out["uid"] = pick("UID").astype(str).str.replace(r"\.0$", "", regex=True)
    out["customer"] = pick("User Name", "Họ tên người mua hàng/Tên Đơn vị")
    out["package"] = pick("Package")
    out["sales"] = pick("Sales")
    out["gateway"] = pick("Gateway")
    out["pay_method"] = pick("Payment Method")
    out["note"] = pick("NOTE", "Note")
    out["bank_id"] = pick("Bank ID")
    out = out[out["amount"].notna() & (out["amount"] > 0)]
    # ưu tiên "Month of payment" (tháng kế toán ghi nhận) nếu có, vd "2026/1"
    mop = pick("Month of payment").astype(str).str.strip()
    mop_parsed = pd.to_datetime(mop, format="%Y/%m", errors="coerce")
    out["month"] = mop_parsed.dt.to_period("M").astype(str).where(
        mop_parsed.notna(),
        out["order_date"].dt.to_period("M").astype(str))
    out.loc[out["month"] == "NaT", "month"] = np.nan
    out["order_id"] = [f"{region}-{i}" for i in out.index]
    return out.reset_index(drop=True)


def load_bank(df, account_label):
    """Chuẩn hóa sao kê (format MB/HN hoặc VCB/HCM) về 1 schema, chỉ giữ tiền VÀO."""
    df = df.copy()
    cols = [c.strip() for c in df.columns]
    df.columns = cols

    def find(*keys):
        for c in cols:
            cl = strip_accents(c)
            if any(k in cl for k in keys):
                return c
        return None

    c_credit = find("PHAT SINH CO", "CREDIT", "GHI CO")
    c_eff = find("NGAY HACH TOAN", "HIEU LUC", "EFFECTIVE DATE", "EFFECTIVE")
    c_date = find("NGAY GIAO DICH", "TNX DATE", "NGAY1")
    if c_date == c_eff:
        c_date = None
    c_who = find("DON VI THU HUONG", "DON VI CHUYEN")
    c_detail = find("NOI DUNG", "TRANSACTIONS IN DETAIL", "DETAIL")
    c_ref = find("BUT TOAN", "DOC NO")

    out = pd.DataFrame(index=df.index)
    out["account"] = account_label
    out["credit"] = vnd(df[c_credit]) if c_credit else np.nan
    # cột ngày có thể dạng "02/01/2026 / 5433 - 52354" -> lấy phần trước " / "
    def clean_date_col(col):
        s = df[col].astype(str).str.split(" / ").str[0]
        return parse_date_any(s)
    out["txn_date"] = clean_date_col(c_date) if c_date else pd.NaT
    out["post_date"] = clean_date_col(c_eff) if c_eff else pd.NaT
    # nếu cột ngày giao dịch hỏng/thiếu, dùng ngày hiệu lực
    if c_date is None or out["txn_date"].isna().mean() > 0.5:
        out["txn_date"] = out["txn_date"].fillna(out["post_date"])
        if out["txn_date"].isna().all():
            out["txn_date"] = out["post_date"]
    out["txn_date"] = out["txn_date"].fillna(out["post_date"])
    out["counterparty"] = df[c_who] if c_who else ""
    out["detail"] = df[c_detail] if c_detail else ""
    out["ref"] = df[c_ref] if c_ref else ""
    out = out[out["credit"].notna() & (out["credit"] > 0)].copy()
    out["month"] = out["txn_date"].dt.to_period("M").astype(str)
    text = (out["counterparty"].fillna("").astype(str) + " " +
            out["detail"].fillna("").astype(str))
    out["text_norm"] = text.apply(strip_accents)
    out["phones_in_text"] = text.apply(phones_from_text)
    out["txn_id"] = [f"{account_label}-{i}" for i in out.index]
    return out.reset_index(drop=True)


def classify_nonrevenue(bank):
    """Đánh dấu giao dịch tiền vào KHÔNG phải doanh thu khách hàng."""
    t = bank["text_norm"]
    sender = bank["counterparty"].fillna("").astype(str).apply(strip_accents)
    conds = [
        # nội bộ: NGƯỜI CHUYỂN là pháp nhân PalFish, hoặc nội dung là thanh toán hợp đồng dịch vụ
        sender.str.contains("PALFISH|PAL FISH", na=False) |
        t.str.contains("THANH TOAN PHI DICH VU THEO HOP DONG", na=False),
        t.str.contains("TRA LAI TIEN GUI|INTEREST", na=False),
        t.str.contains("VIMO", na=False),
        t.str.contains("NGAN LUONG", na=False),
        t.str.contains("HOAN TRA|HOAN TIEN|REFUND", na=False),
    ]
    labels = ["Nội bộ PalFish", "Lãi tiền gửi", "Cổng VIMO (gộp)",
              "Cổng Ngân Lượng (gộp)", "Hoàn tiền"]
    bank = bank.copy()
    bank["nonrev_type"] = np.select(conds, labels, default="")
    return bank


# ---------------------------------------------------------------- matching

def match_orders_to_bank(orders, bank, date_window=3, split_window=35):
    """
    Khớp đơn ↔ giao dịch. Trả về (orders, bank) với cột match_status / matched_*.

    Pass 1: số tiền đúng + ngày ±window
    Pass 2: số tiền đúng + SĐT đơn xuất hiện trong nội dung CK (bỏ giới hạn ngày)
    Pass 3: 2 giao dịch cộng lại = số tiền đơn (cọc + chuyển nốt), trong split_window ngày
    Pass 4: số tiền đúng + ngày ±35 (vớt các đơn ghi ngày lệch xa)
    """
    orders = orders.copy()
    bank = bank.copy()
    bank["used_by"] = None
    orders["match_status"] = "KHÔNG TÌM THẤY"
    orders["matched_txn"] = None
    orders["matched_amount"] = np.nan

    free = lambda: bank["used_by"].isna() & (bank["nonrev_type"] == "")

    # Pass 0: khớp theo giờ giao dịch (bank day + bank time). Giờ trong report
    # thường ghi lỏng nên chỉ nhận 2 trường hợp chắc chắn:
    #  a) đúng số tiền + trong ±60 phút  -> KHỚP ĐÚNG
    #  b) ±5 phút + lệch số <=20%        -> LỆCH SỐ TIỀN (chỉ rõ khoản lệch)
    if orders["order_ts"].notna().any():
        b_sorted = bank[free() & bank["txn_date"].notna()].sort_values(
            "txn_date")
        for i, r in orders[orders["order_ts"].notna()].iterrows():
            lo = r["order_ts"] - pd.Timedelta(minutes=60)
            hi = r["order_ts"] + pd.Timedelta(minutes=60)
            cand = b_sorted[(b_sorted["txn_date"] >= lo) &
                            (b_sorted["txn_date"] <= hi)]
            cand = cand[cand.index.map(
                lambda j: bank.loc[j, "used_by"] is None)]
            if not len(cand):
                continue
            exact = cand[cand["credit"] == r["expected_bank"]]
            if len(exact):
                j = exact.index[0]
                bank.loc[j, "used_by"] = r["order_id"]
                orders.loc[i, ["match_status", "matched_txn",
                               "matched_amount"]] = \
                    ["KHỚP ĐÚNG (theo giờ GD)", bank.loc[j, "txn_id"],
                     bank.loc[j, "credit"]]
                continue
            near = cand[(cand["txn_date"] - r["order_ts"]).abs()
                        <= pd.Timedelta(minutes=5)]
            near = near[(near["credit"] - r["expected_bank"]).abs()
                        <= 0.2 * r["expected_bank"]]
            if len(near):
                j = (near["txn_date"] - r["order_ts"]).abs().idxmin()
                bank.loc[j, "used_by"] = r["order_id"]
                orders.loc[i, ["match_status", "matched_txn",
                               "matched_amount"]] = \
                    ["LỆCH SỐ TIỀN (đúng giờ GD)", bank.loc[j, "txn_id"],
                     bank.loc[j, "credit"]]

    # Pass 1 & 4
    for window, label in ((date_window, "KHỚP ĐÚNG"), (35, "KHỚP (lệch ngày)")):
        for i, r in orders[orders["match_status"] == "KHÔNG TÌM THẤY"].iterrows():
            if pd.isna(r["order_date"]):
                continue
            cand = bank[free() & (bank["credit"] == r["expected_bank"]) &
                        (abs((bank["txn_date"] - r["order_date"]).dt.days) <= window)]
            if len(cand):
                j = cand.index[0]
                bank.loc[j, "used_by"] = r["order_id"]
                orders.loc[i, ["match_status", "matched_txn", "matched_amount"]] = \
                    [label, bank.loc[j, "txn_id"], bank.loc[j, "credit"]]
        if label == "KHỚP ĐÚNG":
            # Pass 2: phone trong nội dung CK
            phone_map = {}
            for j, b in bank[free()].iterrows():
                for p in b["phones_in_text"]:
                    phone_map.setdefault(p, []).append(j)
            for i, r in orders[orders["match_status"] == "KHÔNG TÌM THẤY"].iterrows():
                p = r["phone"]
                if pd.isna(p) or p not in phone_map:
                    continue
                for j in phone_map[p]:
                    if bank.loc[j, "used_by"] is None and \
                       bank.loc[j, "credit"] == r["expected_bank"]:
                        bank.loc[j, "used_by"] = r["order_id"]
                        orders.loc[i, ["match_status", "matched_txn",
                                       "matched_amount"]] = \
                            ["KHỚP QUA SĐT", bank.loc[j, "txn_id"],
                             bank.loc[j, "credit"]]
                        break
            # Pass 3: cọc + chuyển nốt (2 giao dịch) — yêu cầu cùng người chuyển
            # hoặc nội dung CK chứa SĐT của đơn, để tránh khớp nhầm
            for i, r in orders[orders["match_status"] == "KHÔNG TÌM THẤY"].iterrows():
                if pd.isna(r["order_date"]):
                    continue
                pool = bank[free() &
                            (abs((bank["txn_date"] - r["order_date"]).dt.days)
                             <= split_window) &
                            (bank["credit"] < r["expected_bank"])]
                target = r["expected_bank"]
                phone = r["phone"]
                found = None
                recs = list(pool[["credit", "counterparty",
                                  "phones_in_text"]].itertuples())
                for a in range(len(recs)):
                    for b in range(a + 1, len(recs)):
                        r1, r2 = recs[a], recs[b]
                        if r1.credit + r2.credit != target:
                            continue
                        same_sender = (
                            isinstance(r1.counterparty, str) and
                            isinstance(r2.counterparty, str) and
                            strip_accents(r1.counterparty) ==
                            strip_accents(r2.counterparty) and
                            strip_accents(r1.counterparty) != "")
                        phone_ev = pd.notna(phone) and (
                            phone in r1.phones_in_text or
                            phone in r2.phones_in_text)
                        if same_sender or phone_ev:
                            found = (r1.Index, r2.Index)
                            break
                    if found:
                        break
                if found:
                    j1, j2 = found
                    bank.loc[[j1, j2], "used_by"] = r["order_id"]
                    orders.loc[i, ["match_status", "matched_txn",
                                   "matched_amount"]] = \
                        ["KHỚP GỘP 2 GIAO DỊCH (cọc + nốt)",
                         f"{bank.loc[j1, 'txn_id']} + {bank.loc[j2, 'txn_id']}",
                         bank.loc[j1, "credit"] + bank.loc[j2, "credit"]]

    orders["lech"] = (orders["expected_bank"] -
                      orders["matched_amount"].fillna(0)).where(
        orders["match_status"] != "KHÔNG TÌM THẤY",
        orders["expected_bank"])

    # Pass 5: 1 giao dịch trả cho 2 đơn (chung nhà / mua 2 đơn) — cùng SĐT hoặc cùng ngày+sales
    nf = orders[orders["match_status"] == "KHÔNG TÌM THẤY"]
    for key_cols in (["phone"], ["order_date", "sales"]):
        nf = orders[orders["match_status"] == "KHÔNG TÌM THẤY"]
        for _, grp in nf.groupby([c for c in key_cols], dropna=True):
            if len(grp) < 2:
                continue
            idx = list(grp.index)
            for a in range(len(idx)):
                for b in range(a + 1, len(idx)):
                    i1, i2 = idx[a], idx[b]
                    if orders.loc[i1, "match_status"] != "KHÔNG TÌM THẤY" or \
                       orders.loc[i2, "match_status"] != "KHÔNG TÌM THẤY":
                        continue
                    total = orders.loc[i1, "expected_bank"] + \
                        orders.loc[i2, "expected_bank"]
                    d = orders.loc[i1, "order_date"]
                    if pd.isna(d):
                        continue
                    cand = bank[free() & (bank["credit"] == total) &
                                (abs((bank["txn_date"] - d).dt.days)
                                 <= split_window)]
                    if len(cand):
                        j = cand.index[0]
                        bank.loc[j, "used_by"] = \
                            f"{orders.loc[i1, 'order_id']}+{orders.loc[i2, 'order_id']}"
                        for ii in (i1, i2):
                            orders.loc[ii, ["match_status", "matched_txn",
                                            "matched_amount"]] = \
                                ["KHỚP CHUNG 1 GIAO DỊCH (2 đơn)",
                                 bank.loc[j, "txn_id"],
                                 orders.loc[ii, "expected_bank"]]
                            orders.loc[ii, "lech"] = 0
    return orders, bank


def error_groups(orders, bank):
    """Tổng hợp lỗi sai theo nhóm, theo tháng."""
    o = orders.copy()
    # đơn trả qua cổng thanh toán: Gateway = VIMO / Ngân Lượng / credit
    is_card = o["gateway"].astype(str).apply(strip_accents).str.contains(
        "VIMO|NGAN LUONG|NGANLUONG|CREDIT|VISA|MASTER", na=False)

    def group_of(r):
        if r["match_status"].startswith("KHỚP ĐÚNG"):
            return "✅ Khớp đúng"
        if r["match_status"].startswith("LỆCH SỐ TIỀN"):
            return "🟡 Lệch số tiền (tìm thấy giao dịch, sai số)"
        if r["match_status"].startswith("KHỚP"):
            return "🟡 Khớp nhưng cần xem (SĐT/lệch ngày/gộp cọc)"
        return "🔴 Không tìm thấy trong sao kê"

    o["error_group"] = o.apply(group_of, axis=1)
    # tách nhóm không tìm thấy theo nguyên nhân khả dĩ
    mask_nf = o["error_group"].str.startswith("🔴")
    o.loc[mask_nf & is_card.values, "error_group"] = \
        "🟠 Không thấy — trả qua thẻ/cổng thanh toán (check file cổng)"

    b = bank.copy()
    b["bank_group"] = np.where(
        b["used_by"].notna(), "✅ Đã gắn với đơn",
        np.where(b["nonrev_type"] != "", "⚪ Không phải doanh thu (" +
                 b["nonrev_type"] + ")", "🔴 Tiền vào KHÔNG có đơn nào nhận"))
    return o, b


# ---------------------------------------------------------------- điền tay audit

def audit_manual_file(manual_df, bank_df):
    """So file điền tay vs sao kê gốc: dòng bị sửa số, bị xóa, bị nhân đôi."""
    m = load_bank(manual_df, "manual")
    g = load_bank(bank_df, "bank")
    m["key"] = m["txn_date"].astype(str) + "|" + m["credit"].astype(str)
    g["key"] = g["txn_date"].astype(str) + "|" + g["credit"].astype(str)
    cm, cg = Counter(m["key"]), Counter(g["key"])
    only_m = m[m["key"].isin(set((cm - cg).elements()))].copy()
    only_g = g[g["key"].isin(set((cg - cm).elements()))].copy()

    edited, deleted = [], only_g.copy()
    g_by_ts = only_g.set_index("txn_date")
    used_ts = set()
    for _, r in only_m.iterrows():
        ts = r["txn_date"]
        if pd.notna(ts) and ts in g_by_ts.index and ts not in used_ts:
            real = g_by_ts.loc[[ts]].iloc[0]
            edited.append({
                "Ngày GD": ts, "Số trong file điền tay": r["credit"],
                "Số thực trên sao kê": real["credit"],
                "Chênh lệch": r["credit"] - real["credit"],
                "Người chuyển": r["counterparty"]})
            used_ts.add(ts)
            deleted = deleted[deleted["txn_date"] != ts]
        else:
            edited.append({
                "Ngày GD": ts if pd.notna(ts) else r["month"],
                "Số trong file điền tay": r["credit"],
                "Số thực trên sao kê": None, "Chênh lệch": None,
                "Người chuyển": r["counterparty"]})
    edited = pd.DataFrame(edited)
    # nhân đôi trong file điền tay
    dup_keys = [k for k, c in cm.items() if c > 1]
    dups = m[m["key"].isin(dup_keys)]
    return edited, deleted, dups
