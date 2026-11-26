import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
import random
import zipfile

st.set_page_config(page_title="Recon Data Generator", layout="wide")

st.title("⚡ 3-Way Reconciliation File Generator")
st.caption("Generates synchronized test feeds for NPCI Raw, Switch, and CBS with matching RRNs, MMID, TID, Accounts, and VPAs.")

# ================= Sidebar Configuration =================
st.sidebar.header("1. Volume & Baseline Settings")
total_txns = st.sidebar.number_input("Total Transactions", min_value=10, max_value=200000, value=1000, step=500)
txn_date = st.sidebar.date_input("Transaction Date", value=datetime.today())
min_amt = st.sidebar.number_input("Min Amount (₹)", value=10.0, step=10.0)
max_amt = st.sidebar.number_input("Max Amount (₹)", value=10000.0, step=50.0)
random_seed = st.sidebar.number_input("Random Seed (0 for random)", min_value=0, max_value=999999, value=42)

st.sidebar.header("2. Mismatch Scenarios (%)")
st.sidebar.caption("Keep at 0% for 100% 3-way match across NPCI, Switch & CBS.")
pct_amount_mismatch = st.sidebar.slider("Amount Mismatch (%)", 0, 15, 0)
pct_status_mismatch = st.sidebar.slider("Status Mismatch (%)", 0, 15, 0)
pct_missing_cbs = st.sidebar.slider("Missing in CBS (%)", 0, 15, 0)
pct_missing_npci = st.sidebar.slider("Missing in NPCI (%)", 0, 15, 0)

# ================= Generator Engine =================
def build_recon_data(n, t_date, min_a, max_a, seed):
    if seed > 0:
        np.random.seed(seed)
        random.seed(seed)

    date_str_ymd = t_date.strftime("%Y-%m-%d")
    julian_prefix = t_date.strftime("%y%j")

    # 1. Unique Master Identifiers (Guaranteed 1-to-1 match across all 3 files)
    bank_suffixes = random.sample(range(100000, 999999), n)
    npci_suffixes = random.sample(range(100000, 999999), n)
    upi_suffixes = random.sample(range(1000000000, 9999999999), n)

    bank_rrns = [f"BNK{julian_prefix}{s}" for s in bank_suffixes]
    npci_rrns = [f"{julian_prefix}{s}" for s in npci_suffixes]
    upi_txn_ids = [f"UPI{t_date.strftime('%Y%m%d')}{s}" for s in upi_suffixes]

    amounts = np.round(np.random.uniform(min_a, max_a, size=n), 2)

    start_time = datetime.combine(t_date, datetime.min.time()) + timedelta(hours=9)
    base_times = [start_time + timedelta(seconds=int(s)) for s in np.random.randint(0, 36000, size=n)]

    # Synchronized Account Numbers, MMID, MID, and TID across all 3 files
    debit_accs = [f"10098{random.randint(10000000, 99999999)}" for _ in range(n)]
    credit_accs = [f"20045{random.randint(10000000, 99999999)}" for _ in range(n)]
    mmids = [f"{random.randint(9000000, 9999999)}" for _ in range(n)]
    merchant_ids = [f"MID_{random.randint(1000, 9999)}" for _ in range(n)]
    terminal_ids = [f"TID_{random.randint(100, 999)}" for _ in range(n)]

    # Custom PRvpa & PEvpa pools matching your exact Excel formulas
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

    # NPCI specific response code list
    npci_resp_codes = ["00", "RB", "U03", "U05", "U06", "U07", "U10", "U11", "U14", "U16", "U17", "U18"]
    statuses = np.random.choice(["SUCCESS", "FAILED", "PENDING"], size=n, p=[0.90, 0.07, 0.03])

    # Master Truth Table
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
        "base_status": statuses,
        "scenario": "MATCH"
    })

    # 2. Inject Scenarios (Only if sliders > 0)
    n_amt = int(n * (pct_amount_mismatch / 100.0))
    n_stat = int(n * (pct_status_mismatch / 100.0))
    n_mcbs = int(n * (pct_missing_cbs / 100.0))
    n_mnpci = int(n * (pct_missing_npci / 100.0))

    shuffled = np.random.permutation(n)
    pos = 0
    df.loc[shuffled[pos:pos+n_amt], "scenario"] = "AMT_MISMATCH"; pos += n_amt
    df.loc[shuffled[pos:pos+n_stat], "scenario"] = "STATUS_MISMATCH"; pos += n_stat
    df.loc[shuffled[pos:pos+n_mcbs], "scenario"] = "MISSING_IN_CBS"; pos += n_mcbs
    df.loc[shuffled[pos:pos+n_mnpci], "scenario"] = "MISSING_IN_NPCI"; pos += n_mnpci

    # ------------------ 1. NPCI FILE GENERATION ------------------
    npci_df = df[df["scenario"] != "MISSING_IN_NPCI"].copy()
    npci_n = len(npci_df)

    def get_npci_code(status):
        if status == "SUCCESS":
            return "00"
        return random.choice([c for c in npci_resp_codes if c != "00"])

    assigned_npci_codes = [get_npci_code(s) for s in npci_df["base_status"]]

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

    # ------------------ 2. SWITCH FILE GENERATION ------------------
    switch_df = df.copy()
    switch_times = switch_df["time"] + pd.to_timedelta(np.random.randint(1, 3, size=len(switch_df)), unit='s')

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
        "Amount": switch_df["amount"],
        "Txn Type (Cr/Dr)": "DR",
        "Txn Mode": "P2M",
        "Initiation Mode": "00",
        "Purpose Code": "00",
        "Response Code": np.where(switch_df["base_status"] == "SUCCESS", "00", "U69"),
        "Status": switch_df["base_status"],
        "Auth Code": [f"ATH{random.randint(10000, 99999)}" for _ in range(len(switch_df))],
        "Merchant ID": switch_df["merchant_id"],
        "Terminal ID": switch_df["terminal_id"],
        "Acquirer IFSC": "HDFC0000001",
        "Issuer IFSC": "SBIN0001234",
        "Channel": "UPI",
        "Reversal Flag": "N"
    })

    # ------------------ 3. CBS FILE GENERATION ------------------
    cbs_df = df[df["scenario"] != "MISSING_IN_CBS"].copy()
    cbs_times = cbs_df["time"] + pd.to_timedelta(np.random.randint(3, 7, size=len(cbs_df)), unit='s')

    cbs_amt = cbs_df["amount"].copy()
    amt_mask = cbs_df["scenario"] == "AMT_MISMATCH"
    cbs_amt.loc[amt_mask] = np.round(
        cbs_amt.loc[amt_mask] + np.random.choice([-10.0, 5.0, 1.5, -2.5], size=amt_mask.sum()), 2
    )

    cbs_status = cbs_df["base_status"].copy()
    stat_mask = cbs_df["scenario"] == "STATUS_MISMATCH"
    cbs_status.loc[stat_mask] = np.where(cbs_status.loc[stat_mask] == "SUCCESS", "FAILED", "SUCCESS")

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
        "Narration/Remarks": "UPI OUTWARD SETTLEMENT",
        "Txn Status": cbs_status,
        "Channel": "UPI",
        "Merchant ID": cbs_df["merchant_id"],
        "Terminal ID": cbs_df["terminal_id"],
        "Settlement Batch": f"BATCH_{t_date.strftime('%Y%m%d')}_01",
        "Reversal Flag": "N"
    })

    return npci_export, switch_export, cbs_export, df


# ================= UI & Export Logic =================
if st.button("🚀 Generate Files in One-Click", type="primary"):
    with st.spinner("Processing feeds according to custom formats..."):
        npci_file, switch_file, cbs_file, truth_log = build_recon_data(
            total_txns, txn_date, min_amt, max_amt, random_seed
        )

        st.success("Files generated successfully matching your exact schemas!")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("NPCI Rows", f"{len(npci_file):,}")
        col2.metric("Switch Rows", f"{len(switch_file):,}")
        col3.metric("CBS Rows", f"{len(cbs_file):,}")
        col4.metric("Injected Exceptions", f"{len(truth_log[truth_log['scenario'] != 'MATCH']):,}")

        # ZIP Buffer containing only the 3 requested files: NPCI, CBS, SWITCH
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

        st.download_button(
            label="📥 Download NPCI, Switch & CBS Files (ZIP)",
            data=zip_buf.getvalue(),
            file_name=f"Recon_Batch_{txn_date.strftime('%Y%m%d')}.zip",
            mime="application/zip"
        )

        st.subheader("Data Previews (First 5 Rows)")
        t1, t2, t3 = st.tabs(["NPCI Preview", "Switch Preview", "CBS Preview"])
        t1.dataframe(npci_file.head(5))
        t2.dataframe(switch_file.head(5))
        t3.dataframe(cbs_file.head(5))
