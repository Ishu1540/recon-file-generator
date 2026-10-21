import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
import random
import zipfile

st.set_page_config(page_title="Recon Data Generator", layout="wide")

st.title("⚡ 3-Way Reconciliation File Generator")
st.caption("Generates coordinated test feeds for NPCI Raw, Switch, and CBS with exact banking schemas.")

# ================= Sidebar Configuration =================
st.sidebar.header("1. Volume & Baseline Settings")
total_txns = st.sidebar.number_input("Total Transactions", min_value=10, max_value=200000, value=1000, step=500)
txn_date = st.sidebar.date_input("Transaction Date", value=datetime.today())
min_amt = st.sidebar.number_input("Min Amount (₹)", value=10.0, step=10.0)
max_amt = st.sidebar.number_input("Max Amount (₹)", value=10000.0, step=50.0)
random_seed = st.sidebar.number_input("Random Seed (0 for random)", min_value=0, max_value=999999, value=42)

st.sidebar.header("2. Mismatch Scenarios (%)")
pct_amount_mismatch = st.sidebar.slider("Amount Mismatch (%)", 0, 15, 3)
pct_status_mismatch = st.sidebar.slider("Status Mismatch (%)", 0, 15, 4)
pct_missing_cbs = st.sidebar.slider("Missing in CBS (%)", 0, 15, 4)
pct_missing_npci = st.sidebar.slider("Missing in NPCI (%)", 0, 15, 2)

# ================= Generator Engine =================
def build_recon_data(n, t_date, min_a, max_a, seed):
    if seed > 0:
        np.random.seed(seed)
        random.seed(seed)

    # 1. Base Master Data
    bank_rrns = [f"BNK{t_date.strftime('%y%j')}{random.randint(100000, 999999)}" for _ in range(n)]
    npci_rrns = [f"{t_date.strftime('%y%j')}{random.randint(100000, 999999)}" for _ in range(n)]
    upi_txn_ids = [f"UPI{t_date.strftime('%Y%m%d')}{random.randint(1000000000, 9999999999)}" for _ in range(n)]
    amounts = np.round(np.random.uniform(min_a, max_a, size=n), 2)
    
    start_time = datetime.combine(t_date, datetime.min.time()) + timedelta(hours=9)
    base_times = [start_time + timedelta(seconds=int(s)) for s in np.random.randint(0, 36000, size=n)]
    
    debit_accs = [f"10098{random.randint(10000000, 99999999)}" for _ in range(n)]
    credit_accs = [f"20045{random.randint(10000000, 99999999)}" for _ in range(n)]
    
    # NPCI specific response code list
    npci_resp_codes = ["00", "RB", "U03", "U05", "U06", "U07", "U10", "U11", "U14", "U16", "U17", "U18"]
    
    # Assign statuses
    statuses = np.random.choice(["SUCCESS", "FAILED", "PENDING"], size=n, p=[0.90, 0.07, 0.03])

    df = pd.DataFrame({
        "bank_rrn": bank_rrns,
        "npci_rrn": npci_rrns,
        "upi_txn_id": upi_txn_ids,
        "amount": amounts,
        "time": base_times,
        "debit_acc": debit_accs,
        "credit_acc": credit_accs,
        "base_status": statuses,
        "scenario": "MATCH"
    })

    # 2. Inject Scenarios
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

    # ------------------ NPCI FILE GENERATION ------------------
    npci_df = df[df["scenario"] != "MISSING_IN_NPCI"].copy()
    npci_n = len(npci_df)

    # Calculate Response Codes
    def get_npci_code(status):
        if status == "SUCCESS":
            return "00"
        return random.choice([c for c in npci_resp_codes if c != "00"])
    
    assigned_npci_codes = [get_npci_code(s) for s in npci_df["base_status"]]

    # VPA Banks pool
    vpa_handles = ["okhdfcbank", "oksbi", "okaxis", "okicici", "paytm", "ybl", "ibl", "axl"]
    pr_vpas = [f"user{random.randint(100, 999)}@{random.choice(vpa_handles)}" for _ in range(npci_n)]
    pe_vpas = [f"merchant{random.randint(1000, 9999):04d}@okbank" for _ in range(npci_n)]

    # Dynamic liteBalanceAMT logic:
    # IF(RANDBETWEEN(1,10)<=7, ROUND(RAND()*500000, 2), RANDBETWEEN(100, 500000))
    lite_balances = []
    for _ in range(npci_n):
        if random.randint(1, 10) <= 7:
            lite_balances.append(round(random.random() * 500000, 2))
        else:
            lite_balances.append(random.randint(100, 500000))

    npci_export = pd.DataFrame({
        "Tlsubtype": "P2M",
        "Tlrrn": npci_df["npci_rrn"],
        "TltxnId": npci_df["upi_txn_id"],
        "Tlresponsecode": assigned_npci_codes,
        "TlDate": t_date.strftime("%Y-%m-%d 00:00:00"),
        "Tltime": npci_df["time"].dt.strftime("%H:%M:%S"),
        "TlsetAmount": npci_df["amount"],
        "BEIfsc": "HDFC0000001",
        "BEaccountNo": npci_df["credit_acc"],
        "REaccountNo": npci_df["debit_acc"],
        "REaccType": "SAVINGS",
        "REid": [f"RE{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "BEid": [f"BE{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "PRid": [f"PR{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "PEid": [f"PE{random.randint(1000, 9999)}" for _ in range(npci_n)],
        "PRvpa": pr_vpas,
        "PEvpa": pe_vpas,
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

    # ------------------ SWITCH FILE GENERATION ------------------
    switch_df = df.copy()
    switch_times = switch_df["time"] + pd.to_timedelta(np.random.randint(1, 3, size=len(switch_df)), unit='s')
    
    switch_export = pd.DataFrame({
        "Txn Date": switch_times.dt.strftime("%Y-%m-%d"),
        "Txn Time": switch_times.dt.strftime("%H:%M:%S"),
        "Bank RRN": switch_df["bank_rrn"],
        "NPCI RRN": switch_df["npci_rrn"],
        "UPI Txn ID": switch_df["upi_txn_id"],
        "STAN": [f"{random.randint(100000, 999999)}" for _ in range(len(switch_df))],
        "Debit Account": switch_df["debit_acc"],
        "Credit Account": switch_df["credit_acc"],
        "Amount": switch_df["amount"],
        "Txn Type (Cr/Dr)": "DR",
        "Txn Mode": "P2M",
        "Initiation Mode": "00",
        "Purpose Code": "00",
        "Response Code": np.where(switch_df["base_status"] == "SUCCESS", "00", "U69"),
        "Status": switch_df["base_status"],
        "Auth Code": [f"ATH{random.randint(10000, 99999)}" for _ in range(len(switch_df))],
        "Merchant ID": [f"MID_{random.randint(1000, 9999)}" for _ in range(len(switch_df))],
        "Terminal ID": [f"TID_{random.randint(100, 999)}" for _ in range(len(switch_df))],
        "Acquirer IFSC": "HDFC0000001",
        "Issuer IFSC": "SBIN0001234",
        "Channel": "UPI",
        "Reversal Flag": "N"
    })

    # ------------------ CBS FILE GENERATION ------------------
    cbs_df = df[df["scenario"] != "MISSING_IN_CBS"].copy()
    cbs_times = cbs_df["time"] + pd.to_timedelta(np.random.randint(3, 7, size=len(cbs_df)), unit='s')
    
    cbs_amt = cbs_df["amount"].copy()
    amt_mask = cbs_df["scenario"] == "AMT_MISMATCH"
    cbs_amt.loc[amt_mask] = np.round(cbs_amt.loc[amt_mask] + np.random.choice([-10.0, 5.0, 1.5, -2.5], size=amt_mask.sum()), 2)
    
    cbs_status = cbs_df["base_status"].copy()
    stat_mask = cbs_df["scenario"] == "STATUS_MISMATCH"
    cbs_status.loc[stat_mask] = "FAILED"
    
    cbs_export = pd.DataFrame({
        "Posting Date": cbs_times.dt.strftime("%Y-%m-%d %H:%M:%S"),
        "Value Date": t_date.strftime("%Y-%m-%d"),
        "Bank RRN": cbs_df["bank_rrn"],
        "NPCI RRN": cbs_df["npci_rrn"],
        "UPI Txn ID": cbs_df["upi_txn_id"],
        "Debit A/c Number": cbs_df["debit_acc"],
        "Credit A/c Number": cbs_df["credit_acc"],
        "Amount": cbs_amt,
        "Dr/Cr Indicator": "DR",
        "GL Code": "GL2400109",
        "Narration/Remarks": "UPI OUTWARD SETTLEMENT",
        "Txn Status": cbs_status,
        "Channel": "UPI",
        "Merchant ID": [f"MID_{random.randint(1000, 9999)}" for _ in range(len(cbs_df))],
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

        # ZIP Buffer
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
                truth_log.to_excel(w, index=False, sheet_name="RECON_KEY")
            z.writestr("Reconciliation_Key_Truth.xlsx", buf4.getvalue())

        st.download_button(
            label="📥 Download All 3 Files + Recon Key (ZIP)",
            data=zip_buf.getvalue(),
            file_name=f"Recon_Batch_{txn_date.strftime('%Y%m%d')}.zip",
            mime="application/zip"
        )

        st.subheader("Data Previews (First 5 Rows)")
        t1, t2, t3 = st.tabs(["NPCI Preview", "Switch Preview", "CBS Preview"])
        t1.dataframe(npci_file.head(5))
        t2.dataframe(switch_file.head(5))
        t3.dataframe(cbs_file.head(5))