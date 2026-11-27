import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
import random
import zipfile

st.set_page_config(page_title="3-Way UPI Recon Data Generator", layout="wide")

st.title("⚡ Realistic 3-Way UPI Reconciliation File Generator")
st.caption("Generates synchronized NPCI, Switch, and CBS files with clean bucket separation for TCC102, TCC103, RB Reversals, Partial Matches, Duplicates, and Single/Dual-Leg Unmatched records.")

# ================= Sidebar Configuration =================
st.sidebar.header("1. Volume & Baseline Settings")
total_txns = st.sidebar.number_input("Total Master Transactions", min_value=50, max_value=200000, value=2000, step=500)
txn_date = st.sidebar.date_input("Transaction Date", value=datetime.today())
min_amt = st.sidebar.number_input("Min Amount (₹)", value=10.0, step=10.0)
max_amt = st.sidebar.number_input("Max Amount (₹)", value=10000.0, step=50.0)
random_seed = st.sidebar.number_input("Random Seed (0 for random)", min_value=0, max_value=999999, value=42)

st.sidebar.header("2. TCC & RB Reversal Scenarios (%)")
pct_tcc102 = st.sidebar.slider("TCC 102 (NPCI 00, Switch Failed, Missing CBS) %", 0.0, 10.0, 1.5, 0.5)
pct_tcc103 = st.sidebar.slider("TCC 103 (NPCI & Switch 00, Missing CBS) %", 0.0, 10.0, 1.5, 0.5)
pct_rb_matched = st.sidebar.slider("RB - Matched Reversal (NPCI RB, Sw Failed, CBS Reversed) %", 0.0, 10.0, 1.5, 0.5)
pct_rb_cbs_unrev = st.sidebar.slider("RB - Unreversed in CBS (NPCI RB, Sw Failed, CBS Success) %", 0.0, 10.0, 1.0, 0.5)
pct_rb_both_unrev = st.sidebar.slider("RB - Unreversed in Switch & CBS (NPCI RB, Sw & CBS Success) %", 0.0, 10.0, 1.0, 0.5)

st.sidebar.header("3. Partial Match, Missing Leg & Duplicates (%)")
pct_partial_cbs = st.sidebar.slider("Partial Match - CBS Amount/Status Diff %", 0.0, 10.0, 1.5, 0.5)
pct_partial_switch = st.sidebar.slider("Partial Match - Switch Amount/Status Diff %", 0.0, 10.0, 1.0, 0.5)
pct_partial_both = st.sidebar.slider("Partial Match - Both CBS & Switch Diff %", 0.0, 10.0, 1.0, 0.5)
pct_not_in_switch = st.sidebar.slider("Partial Matched - Not in Switch (NPCI & CBS Only) %", 0.0, 10.0, 2.0, 0.5)
pct_not_in_switch_cbs = st.sidebar.slider("Partial Matched - Not in Switch & CBS (NPCI Only) %", 0.0, 10.0, 2.0, 0.5)
pct_cbs_switch_only = st.sidebar.slider("Unmatched - CBS & Switch Only (Not in NPCI) %", 0.0, 10.0, 1.5, 0.5)
pct_cbs_only = st.sidebar.slider("Unmatched - CBS Only %", 0.0, 10.0, 2.0, 0.5)
pct_switch_only = st.sidebar.slider("Unmatched - Switch Only %", 0.0, 10.0, 2.0, 0.5)
pct_duplicates = st.sidebar.slider("Duplicate Entries (NPCI / CBS / Switch) %", 0.0, 10.0, 1.0, 0.5)


# ================= Generator Engine =================
def build_recon_data(n, t_date, min_a, max_a, seed):
    if seed > 0:
        np.random.seed(seed)
        random.seed(seed)

    date_str_ymd = t_date.strftime("%Y-%m-%d")
    julian_prefix = t_date.strftime("%y%j")

    # 1. Master Unique Identifiers (1-to-1 base alignment across all 3 files)
    bank_suffixes = random.sample(range(100000, 999999), n)
    npci_suffixes = random.sample(range(100000, 999999), n)
    upi_suffixes = random.sample(range(1000000000, 9999999999), n)

    bank_rrns = [f"BNK{julian_prefix}{s}" for s in bank_suffixes]
    npci_rrns = [f"{julian_prefix}{s}" for s in npci_suffixes]
    upi_txn_ids = [f"UPI{t_date.strftime('%Y%m%d')}{s}" for s in upi_suffixes]

    amounts = np.round(np.random.uniform(min_a, max_a, size=n), 2)
    start_time = datetime.combine(t_date, datetime.min.time()) + timedelta(hours=9)
    base_times = [start_time + timedelta(seconds=int(s)) for s in np.random.randint(0, 36000, size=n)]

    # Synchronized Accounts, MMID, MID, TID across all 3 files
    debit_accs = [f"10098{random.randint(10000000, 99999999)}" for _ in range(n)]
    credit_accs = [f"20045{random.randint(10000000, 99999999)}" for _ in range(n)]
    mmids = [f"{random.randint(9000000, 9999999)}" for _ in range(n)]
    merchant_ids = [f"MID_{random.randint(1000, 9999)}" for _ in range(n)]
    terminal_ids = [f"TID_{random.randint(100, 999)}" for _ in range(n)]

    # Exact PRvpa & PEvpa pools
    prvpa_handles = ["@okhdfcbank", "@oksbi", "@okicici", "@paytm", "@ybl"]
    pr_vpas = [f"user{random.randint(100, 999)}{random.choice(prvpa_handles)}" for _ in range(n)]

    pevpa_pool = [
        "bloomify@icici",
        "quickbasket@ICICI",
        "rangolihome@ICICI",
        "anveshan@ICICI",
        "wheatstone@icici",
        "KesarJ@icici",
        "meridian@icici",
        "anandikirana@ICICI"
    ]
    pe_vpas = [random.choice(pevpa_pool) for _ in range(n)]

    # Default all master transactions to clean SUCCESS so random base failures don't bleed into recon buckets
    df = pd.DataFrame({
        "bank_rrn": bank_rrns,
        "npci_rrn": npci_rrns,
        "upi_txn_id": upi_txn_ids,
        "amount": amounts,
        "time": base_times,
        "debit_acc": debit_accs,
        "credit_acc": credit_accs,
        "mmid": mmids,
        "merchant_id": merchant_ids,
        "terminal_id": terminal_ids,
        "pr_vpa": pr_vpas,
        "pe_vpa": pe_vpas,
        "base_status": "SUCCESS",
        "expected_recon_status": "FULLY_MATCHED"
    })

    # 2. Assign Strictly Isolated Reconciliation Scenarios
    scenario_specs = [
        ("TCC102_NPCI_00_SW_FAIL_NO_CBS", pct_tcc102),
        ("TCC103_NPCI_00_SW_00_NO_CBS", pct_tcc103),
        ("RB_MATCHED_REVERSAL", pct_rb_matched),
        ("RB_UNREVERSED_IN_CBS", pct_rb_cbs_unrev),
        ("RB_UNREVERSED_IN_SWITCH_AND_CBS", pct_rb_both_unrev),
        ("PARTIAL_MATCH_CBS_DIFF", pct_partial_cbs),
        ("PARTIAL_MATCH_SWITCH_DIFF", pct_partial_switch),
        ("PARTIAL_MATCH_BOTH_CBS_SW_DIFF", pct_partial_both),
        ("PARTIAL_MATCHED_NOT_IN_SWITCH", pct_not_in_switch),
        ("PARTIAL_MATCHED_NOT_IN_SWITCH_AND_CBS", pct_not_in_switch_cbs),
        ("UNMATCHED_CBS_AND_SWITCH_ONLY", pct_cbs_switch_only),
        ("UNMATCHED_CBS_ONLY", pct_cbs_only),
        ("UNMATCHED_SWITCH_ONLY", pct_switch_only),
        ("DUPLICATE_ENTRY", pct_duplicates),
    ]

    shuffled = np.random.permutation(n)
    pos = 0
    for label, pct in scenario_specs:
        cnt = int(n * (pct / 100.0))
        if pos + cnt <= n and cnt > 0:
            df.loc[shuffled[pos:pos + cnt], "expected_recon_status"] = label
            pos += cnt

    # ------------------ 1. BUILD NPCI FILE ------------------
    npci_exclude = [
        "UNMATCHED_SWITCH_ONLY",
        "UNMATCHED_CBS_ONLY",
        "UNMATCHED_CBS_AND_SWITCH_ONLY"
    ]
    npci_df = df[~df["expected_recon_status"].isin(npci_exclude)].copy()

    # Inject NPCI duplicates (only from DUPLICATE_ENTRY bucket)
    dup_pool = npci_df[npci_df["expected_recon_status"] == "DUPLICATE_ENTRY"]
    if len(dup_pool) > 0:
        npci_dups = dup_pool.sample(frac=0.5, random_state=seed if seed > 0 else None).copy()
        npci_df = pd.concat([npci_df, npci_dups], ignore_index=True)

    npci_n = len(npci_df)
    rb_scenarios = {"RB_MATCHED_REVERSAL", "RB_UNREVERSED_IN_CBS", "RB_UNREVERSED_IN_SWITCH_AND_CBS"}
    assigned_npci_codes = [
        "RB" if scen in rb_scenarios else "00"
        for scen in npci_df["expected_recon_status"]
    ]

    lite_balances = [
        round(random.random() * 500000, 2) if random.randint(1, 10) <= 7 else random.randint(100, 500000)
        for _ in range(npci_n)
    ]

    npci_export = pd.DataFrame({
        "Tlsubtype": "P2M",
        "Bank_RRN": npci_df["bank_rrn"],
        "Tlrrn": npci_df["npci_rrn"],
        "TltxnId": npci_df["upi_txn_id"],
        "Tlresponsecode": assigned_npci_codes,
        "TlDate": f"{date_str_ymd} 00:00:00",
        "Tltime": npci_df["time"].dt.strftime("%H:%M:%S"),
        "TlsetAmount": npci_df["amount"],
        "BEIfsc": "HDFC0000001",
        "BEaccountNo": npci_df["credit_acc"],
        "REaccountNo": npci_df["debit_acc"],
        "MMID": npci_df["mmid"],
        "Merchant_ID": npci_df["merchant_id"],
        "Terminal_ID": npci_df["terminal_id"],
        "REaccType": "SAVINGS",
        "REid": [f"RE{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "BEid": [f"BE{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "PRid": [f"PR{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "PEid": [f"PE{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "PRvpa": npci_df["pr_vpa"],
        "PEvpa": npci_df["pe_vpa"],
        "TIumn": [f"UMN{random.randint(10000000, 99999999)}" for _ in range(npci_n)],
        "TcInitiation Mode": [random.randint(1, 20) for _ in range(npci_n)],
        "TCPurpose": None,
        "REaccType.1": 1,
        "BEaccType": "SAVINGS",
        "prmcc": "5411",
        "TlMapperID": [f"MAP{random.randint(10000, 99999)}" for _ in range(npci_n)],
        "PEmee": [random.randint(2000, 9999) for _ in range(npci_n)],
        "LRN": [f"LRN{random.randint(100000, 999999)}" for _ in range(npci_n)],
        "FuelSurcharge": 0.00,
        "GSTonFuelsurcharge": 0.00,
        "LiteRefNoPayee": [f"LNP{random.randint(2000, 9999)}" for _ in range(npci_n)],
        "liteBalanceAMT": lite_balances
    })

    # ------------------ 2. BUILD SWITCH FILE ------------------
    switch_exclude = [
        "UNMATCHED_CBS_ONLY",
        "PARTIAL_MATCHED_NOT_IN_SWITCH",
        "PARTIAL_MATCHED_NOT_IN_SWITCH_AND_CBS"
    ]
    switch_df = df[~df["expected_recon_status"].isin(switch_exclude)].copy()

    # Inject Switch duplicates
    sw_dup_pool = switch_df[switch_df["expected_recon_status"] == "DUPLICATE_ENTRY"]
    if len(sw_dup_pool) > 0:
        sw_dups = sw_dup_pool.sample(frac=0.3, random_state=(seed + 1) if seed > 0 else None).copy()
        switch_df = pd.concat([switch_df, sw_dups], ignore_index=True)

    switch_times = switch_df["time"] + pd.to_timedelta(np.random.randint(1, 3, size=len(switch_df)), unit='s')
    switch_amt = switch_df["amount"].copy()
    switch_status = pd.Series("SUCCESS", index=switch_df.index, dtype=object)
    switch_resp_code = pd.Series("00", index=switch_df.index, dtype=object)
    switch_rev_flag = pd.Series("N", index=switch_df.index, dtype=object)

    # TCC 102: Switch shows FAILED (U69 timeout), NPCI settled 00, CBS missing
    tcc102_mask = switch_df["expected_recon_status"] == "TCC102_NPCI_00_SW_FAIL_NO_CBS"
    switch_status.loc[tcc102_mask] = "FAILED"
    switch_resp_code.loc[tcc102_mask] = "U69"

    # RB cases where Switch recorded the RB reversal
    rb_sw_rev_mask = switch_df["expected_recon_status"].isin([
        "RB_MATCHED_REVERSAL",
        "RB_UNREVERSED_IN_CBS"
    ])
    switch_status.loc[rb_sw_rev_mask] = "FAILED"
    switch_resp_code.loc[rb_sw_rev_mask] = "RB"
    switch_rev_flag.loc[rb_sw_rev_mask] = "Y"

    # Partial Match in Switch (or Both)
    sw_partial_mask = switch_df["expected_recon_status"].isin([
        "PARTIAL_MATCH_SWITCH_DIFF",
        "PARTIAL_MATCH_BOTH_CBS_SW_DIFF"
    ])
    switch_amt.loc[sw_partial_mask] = np.round(
        switch_amt.loc[sw_partial_mask] + np.random.choice([1.0, -1.0, 2.5, -5.0], size=sw_partial_mask.sum()), 2
    )

    switch_export = pd.DataFrame({
        "Txn Date": date_str_ymd,
        "Txn Time": switch_times.dt.strftime("%H:%M:%S"),
        "Bank RRN": switch_df["bank_rrn"],
        "NPCI RRN": switch_df["npci_rrn"],
        "UPI Txn ID": switch_df["upi_txn_id"],
        "STAN": [f"{random.randint(100000, 999999)}" for _ in range(len(switch_df))],
        "Debit Account": switch_df["debit_acc"],
        "Credit Account": switch_df["credit_acc"],
        "MMID": switch_df["mmid"],
        "PRvpa": switch_df["pr_vpa"],
        "PEvpa": switch_df["pe_vpa"],
        "Amount": switch_amt,
        "Txn Type (Cr/Dr)": "DR",
        "Txn Mode": "P2M",
        "Initiation Mode": "00",
        "Purpose Code": "00",
        "Response Code": switch_resp_code,
        "Status": switch_status,
        "Auth Code": [f"ATH{random.randint(10000, 99999)}" for _ in range(len(switch_df))],
        "Merchant ID": switch_df["merchant_id"],
        "Terminal ID": switch_df["terminal_id"],
        "Acquirer IFSC": "HDFC0000001",
        "Issuer IFSC": "SBIN0001234",
        "Channel": "UPI",
        "Reversal Flag": switch_rev_flag
    })

    # ------------------ 3. BUILD CBS FILE ------------------
    # Strict rule: TCC 102 & TCC 103 have ZERO rows in CBS
    cbs_exclude = [
        "TCC102_NPCI_00_SW_FAIL_NO_CBS",
        "TCC103_NPCI_00_SW_00_NO_CBS",
        "PARTIAL_MATCHED_NOT_IN_SWITCH_AND_CBS",
        "UNMATCHED_SWITCH_ONLY"
    ]
    cbs_df = df[~df["expected_recon_status"].isin(cbs_exclude)].copy()

    # Inject CBS duplicates
    cbs_dup_pool = cbs_df[cbs_df["expected_recon_status"] == "DUPLICATE_ENTRY"]
    if len(cbs_dup_pool) > 0:
        cbs_dups = cbs_dup_pool.sample(frac=0.3, random_state=(seed + 2) if seed > 0 else None).copy()
        cbs_df = pd.concat([cbs_df, cbs_dups], ignore_index=True)

    cbs_times = cbs_df["time"] + pd.to_timedelta(np.random.randint(3, 7, size=len(cbs_df)), unit='s')
    cbs_amt = cbs_df["amount"].copy()
    cbs_status = pd.Series("SUCCESS", index=cbs_df.index, dtype=object)
    cbs_rev_flag = pd.Series("N", index=cbs_df.index, dtype=object)

    # RB_MATCHED_REVERSAL: CBS reversed cleanly
    rb_cbs_matched_mask = cbs_df["expected_recon_status"] == "RB_MATCHED_REVERSAL"
    cbs_status.loc[rb_cbs_matched_mask] = "REVERSED"
    cbs_rev_flag.loc[rb_cbs_matched_mask] = "Y"

    # Partial Match in CBS (or Both)
    cbs_partial_mask = cbs_df["expected_recon_status"].isin([
        "PARTIAL_MATCH_CBS_DIFF",
        "PARTIAL_MATCH_BOTH_CBS_SW_DIFF"
    ])
    cbs_amt.loc[cbs_partial_mask] = np.round(
        cbs_amt.loc[cbs_partial_mask] + np.random.choice([-10.0, 5.0, 1.5, -2.5], size=cbs_partial_mask.sum()), 2
    )

    cbs_export = pd.DataFrame({
        "Posting Date": f"{date_str_ymd} " + cbs_times.dt.strftime("%H:%M:%S"),
        "Value Date": date_str_ymd,
        "Bank RRN": cbs_df["bank_rrn"],
        "NPCI RRN": cbs_df["npci_rrn"],
        "UPI Txn ID": cbs_df["upi_txn_id"],
        "Debit A/c Number": cbs_df["debit_acc"],
        "Credit A/c Number": cbs_df["credit_acc"],
        "MMID": cbs_df["mmid"],
        "PRvpa": cbs_df["pr_vpa"],
        "PEvpa": cbs_df["pe_vpa"],
        "Amount": cbs_amt,
        "Dr/Cr Indicator": "DR",
        "GL Code": "GL2400109",
        "Narration/Remarks": np.where(cbs_rev_flag == "Y", "UPI RB REVERSAL CREDIT", "UPI OUTWARD SETTLEMENT"),
        "Txn Status": cbs_status,
        "Channel": "UPI",
        "Merchant ID": cbs_df["merchant_id"],
        "Terminal ID": cbs_df["terminal_id"],
        "Settlement Batch": f"BATCH_{t_date.strftime('%Y%m%d')}_01",
        "Reversal Flag": cbs_rev_flag
    })

    # Shuffle output row order independently
    npci_export = npci_export.sample(frac=1, random_state=seed if seed > 0 else None).reset_index(drop=True)
    switch_export = switch_export.sample(frac=1, random_state=seed if seed > 0 else None).reset_index(drop=True)
    cbs_export = cbs_export.sample(frac=1, random_state=seed if seed > 0 else None).reset_index(drop=True)

    return npci_export, switch_export, cbs_export, df


# ================= UI & Export Logic =================
if st.button("🚀 Generate Realistic Recon Files", type="primary"):
    with st.spinner("Generating NPCI, Switch, and CBS files with clean bucket isolation..."):
        npci_file, switch_file, cbs_file, truth_log = build_recon_data(
            total_txns, txn_date, min_amt, max_amt, random_seed
        )

        st.success("3-Way Reconciliation datasets generated successfully!")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("NPCI Rows", f"{len(npci_file):,}")
        col2.metric("Switch Rows", f"{len(switch_file):,}")
        col3.metric("CBS Rows", f"{len(cbs_file):,}")
        col4.metric("Fully Matched Master Txns", f"{(truth_log['expected_recon_status'] == 'FULLY_MATCHED').sum():,}")

        st.subheader("📊 Generated Reconciliation Breakdown (Master Reference)")
        summary_df = (
            truth_log["expected_recon_status"]
            .value_counts()
            .reset_index()
        )
        summary_df.columns = ["Reconciliation Outcome", "Transaction Count"]
        st.dataframe(summary_df, use_container_width=True)

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
            buf1 = io.BytesIO()
            with pd.ExcelWriter(buf1, engine="xlsxwriter") as w:
                npci_file.to_excel(w, index=False, sheet_name="NPCI_RAW")
            z.writestr("NPCI_Recon_File.xlsx", buf1.getvalue())

            buf2 = io.BytesIO()
            with pd.ExcelWriter(buf2, engine="xlsxwriter") as w:
                switch_file.to_excel(w, index=False, sheet_name="SWITCH_TXNS")
            z.writestr("Switch_Recon_File.xlsx", buf2.getvalue())

            buf3 = io.BytesIO()
            with pd.ExcelWriter(buf3, engine="xlsxwriter") as w:
                cbs_file.to_excel(w, index=False, sheet_name="CBS_POSTING")
            z.writestr("CBS_Recon_File.xlsx", buf3.getvalue())

            buf4 = io.BytesIO()
            with pd.ExcelWriter(buf4, engine="xlsxwriter") as w:
                truth_log.to_excel(w, index=False, sheet_name="MASTER_RECON_KEY")
            z.writestr("Master_Recon_Reference_Key.xlsx", buf4.getvalue())

        st.download_button(
            label="📥 Download NPCI, Switch, CBS & Master Reference Key (ZIP)",
            data=zip_buf.getvalue(),
            file_name=f"UPI_3Way_Recon_{txn_date.strftime('%Y%m%d')}.zip",
            mime="application/zip"
        )

        st.subheader("Data Previews (First 5 Rows)")
        t1, t2, t3 = st.tabs(["NPCI Preview", "Switch Preview", "CBS Preview"])
        t1.dataframe(npci_file.head(5))
        t2.dataframe(switch_file.head(5))
        t3.dataframe(cbs_file.head(5))
