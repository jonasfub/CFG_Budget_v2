import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import streamlit.components.v1 as components
import time
import random

# --- 1. 系统配置 ---
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #0068C9; }
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    thead tr th:first-child {display:none}
    tbody th {display:none}
</style>
""", unsafe_allow_html=True)

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# --- 2. 数据库连接 ---
@st.cache_resource
def init_connection():
    try:
        if "supabase" in st.secrets:
            return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None
    return None

supabase = init_connection()

# --- 3. 核心工具函数 ---
def get_forest_list():
    if not supabase: return []
    try:
        return supabase.table("dim_forests").select("*").execute().data
    except: return []

def generate_invoice_html(invoice_no, invoice_date, bill_to, month_str, year, items, subtotal, gst_val, total_due):
    rows_html = ""
    for item in items:
        rows_html += f"<tr class='item'><td>{item['desc']}</td><td class='text-right'>${item['amount']:,.2f}</td></tr>"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #555; padding: 20px; }}
            .invoice-box {{ max-width: 800px; margin: auto; padding: 30px; border: 1px solid #eee; box-shadow: 0 0 10px rgba(0,0,0,.15); font-size: 16px; line-height: 24px; }}
            .invoice-box table {{ width: 100%; text-align: left; border-collapse: collapse; }}
            .invoice-box table td {{ padding: 5px; vertical-align: top; }}
            .heading td {{ background: #eee; border-bottom: 1px solid #ddd; font-weight: bold; }}
            .total td {{ border-top: 2px solid #eee; font-weight: bold; }}
            .text-right {{ text-align: right; }}
        </style>
    </head>
    <body>
        <div class="invoice-box">
            <table cellpadding="0" cellspacing="0">
                <tr class="top"><td colspan="2"><table><tr><td style="font-size:45px; line-height:45px; color:#333;">INVOICE</td><td class="text-right">Inv #: {invoice_no}<br>Date: {invoice_date}</td></tr></table></td></tr>
                <tr class="information"><td colspan="2"><table><tr><td><strong>FCO Management Ltd</strong><br>Napier, NZ</td><td class="text-right"><strong>Bill To:</strong><br>{bill_to}</td></tr></table></td></tr>
                <tr class="heading"><td>Description</td><td class="text-right">Amount (NZD)</td></tr>
                {rows_html}
                <tr class="total"><td></td><td class="text-right">Total Due: ${total_due:,.2f}</td></tr>
            </table>
        </div>
    </body>
    </html>
    """

# 修复版 get_monthly_data (解决 duplicate axis 错误)
def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    if not supabase: return pd.DataFrame()
    
    # 1. 维度
    dims = supabase.table(dim_table).select("*").execute().data
    df_dims = pd.DataFrame(dims)
    if df_dims.empty: return pd.DataFrame()
    
    # 兼容处理
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name']

    # 2. 数据
    try:
        res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
        df_facts = pd.DataFrame(res.data)
    except: df_facts = pd.DataFrame()
    
    # 3. 合并
    if df_facts.empty:
        # 如果没有事实数据，直接用维度表
        cols_to_keep = ['id', dim_name_col]
        if 'grade_code' in df_dims.columns: cols_to_keep.append('grade_code')
        
        df_merged = df_dims[cols_to_keep].rename(columns={'id': dim_id_col})
        for c in value_cols: df_merged[c] = 0.0
    else:
        # 正常合并
        df_merged = pd.merge(df_dims, df_facts, left_on='id', right_on=dim_id_col, how='left')
        for c in value_cols: df_merged[c] = df_merged[c].fillna(0.0)
    
    # 关键修复: 重置索引并去重，防止 'cannot reindex on duplicate axis' 错误
    df_merged = df_merged.loc[:, ~df_merged.columns.duplicated()]
    df_merged = df_merged.reset_index(drop=True)

    # 补充默认字段
    if 'market' not in df_merged.columns and 'grade_code' in df_merged.columns:
        df_merged['market'] = df_merged['grade_code'].apply(lambda x: 'Domestic' if 'Domestic' in str(x) else 'Export')
    if 'customer' not in df_merged.columns:
        df_merged['customer'] = 'FCO' # Default
        
    return df_merged

def save_monthly_data(edited_df, table_name, dim_id_col, forest_id, target_date, record_type):
    if not supabase or edited_df.empty: return False
    records = []
    for _, row in edited_df.iterrows():
        rec = {
            "forest_id": forest_id, dim_id_col: row[dim_id_col],
            "month": target_date, "record_type": record_type
        }
        for col in row.index:
            if col in ['vol_tonnes', 'vol_jas', 'price_jas', 'amount', 'quantity', 'unit_rate', 'total_amount']:
                rec[col] = row[col]
        records.append(rec)
    try:
        supabase.table(table_name).upsert(records, on_conflict=f"forest_id,{dim_id_col},month,record_type").execute()
        return True
    except: return False

# --- 页面 1: Log Sales Data ---
def page_log_sales():
    st.title("🚛 Log Sales Data (Transaction Level)")
    forests = get_forest_list()
    if not forests: st.warning("DB Connecting..."); return
    
    c1, c2 = st.columns([1, 2])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    products = supabase.table("dim_products").select("*").execute().data
    product_codes = [p['grade_code'] for p in products]
    
    res = supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(50).execute()
    df = pd.DataFrame(res.data)
    if df.empty: 
        df = pd.DataFrame([{
            "date": date.today(), "ticket_number": "", "customer": "C001", "market": "Export",
            "grade_code": "A", "net_tonnes": 0.0, "jas": 0.0, "conversion_factor": 0.0, "price": 0.0, "total_value": 0.0
        }])
    else:
        df['conversion_factor'] = df.apply(lambda x: x['jas']/x['net_tonnes'] if x['net_tonnes']>0 else 0, axis=1)

    col_cfg = {
        "id": None, "forest_id": None, "grade_id": None, "created_at": None,
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "ticket_number": st.column_config.TextColumn("Ticket #"),
        "customer": st.column_config.TextColumn("Customer", default="FCO"),
        "market": st.column_config.SelectboxColumn("Market", options=["Export", "Domestic"], default="Export"),
        "conversion_factor": st.column_config.NumberColumn("Conv.", format="%.3f", disabled=True),
        "grade_code": st.column_config.SelectboxColumn("Grade", options=product_codes, required=True),
        "net_tonnes": st.column_config.NumberColumn("Tonnes", format="%.2f"),
        "jas": st.column_config.NumberColumn("JAS", format="%.2f"),
        "price": st.column_config.NumberColumn("Price", format="$%.2f"),
        "total_value": st.column_config.NumberColumn("Total ($)", format="$%.2f"),
    }
    
    edited = st.data_editor(df, key="log_sales", num_rows="dynamic", use_container_width=True, column_config=col_cfg)
    
    if st.button("💾 Save Transactions"):
        recs = []
        for _, row in edited.iterrows():
            gid = next((p['id'] for p in products if p['grade_code'] == row.get('grade_code')), None)
            conv = row['jas'] / row['net_tonnes'] if row['net_tonnes'] > 0 else 0
            recs.append({
                "forest_id": fid, "date": str(row['date']), "ticket_number": row.get('ticket_number'),
                "grade_id": gid, "customer": row.get('customer'), "market": row.get('market'),
                "net_tonnes": row.get('net_tonnes'), "jas": row.get('jas'), "conversion_factor": conv,
                "price": row.get('price'), "total_value": row.get('total_value')
            })
        try:
            supabase.table("actual_sales_transactions").upsert(recs).execute()
            st.success("Transactions Saved!")
        except Exception as e: st.error(f"Error: {e}")

# --- 页面 2 & 3: Monthly Input ---
def page_monthly_input(mode):
    st.title(f"📝 {mode} Planning")
    forests = get_forest_list()
    if not forests: return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2: year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3: month_str = st.selectbox("Month", MONTHS, key=f"m_{mode}")

    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    st.markdown(f"**Editing:** {sel_forest} | {target_date}")
    
    # 调整 Tab 顺序: Budget 模式下 Detailed Forecast 在最左侧
    if mode == "Budget":
        tabs = ["📋 Sales Forecast (Detailed)", "🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    else:
        tabs = ["🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
        
    current_tabs = st.tabs(tabs)

    # --- Tab Logic ---
    # Helper to check active tab
    def is_tab(name): return name in tabs and tabs.index(name) == i 

    for i, tab_name in enumerate(tabs):
        with current_tabs[i]:
            
            # --- 1. Detailed Forecast (Budget Only) ---
            if tab_name == "📋 Sales Forecast (Detailed)":
                st.info("Detailed Sales Budget - Format mimics Log Sales Data")
                df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                
                df_detail = df.copy()
                df_detail['conversion_factor'] = df_detail.apply(lambda x: x['vol_jas']/x['vol_tonnes'] if x['vol_tonnes']>0 else 0, axis=1)
                
                detail_cfg = {
                    "grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True),
                    "market": st.column_config.SelectboxColumn("Market", options=["Export", "Domestic"]),
                    "customer": st.column_config.TextColumn("Customer", default="Expected"),
                    "vol_tonnes": st.column_config.NumberColumn("Tonnes", format="%.1f"),
                    "conversion_factor": st.column_config.NumberColumn("Conv.", format="%.3f"),
                    "vol_jas": st.column_config.NumberColumn("JAS", format="%.1f"),
                    "price_jas": st.column_config.NumberColumn("Price", format="$%.0f"),
                    "amount": st.column_config.NumberColumn("Revenue", format="$%.0f"),
                }
                cols_order = ['grade_id', 'grade_code', 'market', 'customer', 'vol_tonnes', 'conversion_factor', 'vol_jas', 'price_jas', 'amount']
                # 确保列存在再排序
                safe_cols = [c for c in cols_order if c in df_detail.columns]
                df_detail = df_detail[safe_cols]
                
                edited_detail = st.data_editor(df_detail, key=f"d_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=detail_cfg)
                
                if st.button("Save Forecast", key=f"b_detail_{mode}"):
                    if save_monthly_data(edited_detail, "fact_production_volume", "grade_id", fid, target_date, mode): 
                        st.success("Detailed Forecast Saved!")

            # --- 2. Log Transport & Volume ---
            elif tab_name == "🚛 Log Transport & Volume":
                st.info("Base Volume/JAS for Transport calculations.")
                df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                cfg = {"grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True)}
                edited = st.data_editor(df, key=f"v_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
                if st.button("Save Volume", key=f"b1_{mode}"):
                    if save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

            # --- 3. Operational & Harvesting ---
            elif tab_name == "💰 Operational & Harvesting":
                st.info("Harvesting & Ops Costs.")
                df = get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
                cfg = {"activity_id": None, "activity_name": st.column_config.TextColumn("Activity", disabled=True)}
                edited = st.data_editor(df, key=f"c_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
                if st.button("Save Costs", key=f"b2_{mode}"):
                    if save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

# --- 页面 4: Analysis ---
def page_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    forests = get_forest_list()
    if not forests: return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key="inv_f")
    with c2: year = st.selectbox("Year", [2025, 2026], key="inv_y")
    with c3: month_str = st.selectbox("Month", MONTHS, key="inv_m")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"

    try:
        act_costs = supabase.table("fact_operational_costs").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
    except: total_act_cost = 0

    st.subheader(f"Invoice Generation ({month_str} {year})")
    col_input, col_preview = st.columns([1, 2])
    with col_input:
        bill_to = st.text_input("Bill To", "CFG Forestry Group")
        mgmt_fee_pct = st.number_input("Mgmt Fee %", 0.0, 20.0, 8.0, 0.5)
        invoice_no = st.text_input("Inv No.", f"INV-{year}{MONTH_MAP[month_str]:02d}-{fid}")
        
        mgmt_fee_val = total_act_cost * (mgmt_fee_pct / 100)
        subtotal = total_act_cost + mgmt_fee_val
        gst_val = subtotal * 0.15
        total_due = subtotal + gst_val
        items = [{"desc": f"Operational & Harvesting Costs ({month_str} {year})", "amount": total_act_cost},
                 {"desc": f"Management Fee ({mgmt_fee_pct}%)", "amount": mgmt_fee_val}]

    invoice_html = generate_invoice_html(invoice_no, date.today(), bill_to, month_str, year, items, subtotal, gst_val, total_due)
    with col_preview:
        components.html(invoice_html, height=700, scrolling=True)
        st.download_button("⬇️ Download HTML", invoice_html, file_name=f"{invoice_no}.html", mime="text/html")

# --- 页面 5: Invoice Bot (已整合) ---
def page_invoice_bot():
    st.title("🤖 3rd Party Invoice Reconciliation Bot")
    st.caption("Upload contractor invoices (PDF) to verify against Actual Costs in ERP.")

    col_upload, col_review = st.columns([1, 2])
    with col_upload:
        uploaded_files = st.file_uploader("Drag PDFs here", type=["pdf"], accept_multiple_files=True)
        if uploaded_files:
            if st.button("🚀 Start AI Analysis"):
                results = []
                progress_bar = st.progress(0)
                for i, file in enumerate(uploaded_files):
                    time.sleep(0.5) # Mock processing
                    # Mock logic
                    vendor = "Unknown"
                    if "Road" in file.name: vendor = "Road Maintenance"
                    elif "Harv" in file.name: vendor = "Groundbase Harvesting"
                    elif "Truck" in file.name: vendor = "Cartage"
                    
                    amount = random.randint(1000, 20000)
                    results.append({
                        "filename": file.name, "vendor_detected": vendor,
                        "invoice_no": f"INV-{random.randint(10000,99999)}",
                        "amount_detected": float(amount)
                    })
                    progress_bar.progress((i + 1) / len(uploaded_files))
                st.session_state['ocr_results'] = results
                st.success("Analysis Complete!")

    with col_review:
        if 'ocr_results' in st.session_state:
            results = st.session_state['ocr_results']
            reconcile_data = []
            for item in results:
                match_status = "❌ Not Found"
                db_amount = 0
                diff = 0
                if supabase:
                    acts = supabase.table("dim_cost_activities").select("id").ilike("activity_name", f"%{item['vendor_detected']}%").execute().data
                    if acts:
                        act_id = acts[0]['id']
                        costs = supabase.table("fact_operational_costs").select("total_amount")\
                            .eq("activity_id", act_id).eq("month", "2025-01-01").eq("record_type", "Actual").execute().data
                        if costs:
                            db_amount = costs[0]['total_amount']
                            diff = item['amount_detected'] - db_amount
                            match_status = "✅ Match" if abs(diff) < 1.0 else "⚠️ Variance"
                
                reconcile_data.append({
                    "File": item['filename'], "Vendor": item['vendor_detected'],
                    "Inv Amt": item['amount_detected'], "ERP Amt": db_amount, "Diff": diff, "Status": match_status
                })
            
            st.dataframe(pd.DataFrame(reconcile_data), use_container_width=True)

# --- 主导航 ---
st.sidebar.title("🌲 FCO Cloud ERP")
pages = {
    "Dashboard": lambda: st.info("Dashboard Placeholder"), # Replace with full dashboard function if needed
    "1. Log Sales Data": page_log_sales,
    "2. Budget Planning": lambda: page_monthly_input("Budget"),
    "3. Actuals Entry": lambda: page_monthly_input("Actual"),
    "4. Analysis & Invoice": page_analysis_invoice,
    "5. 3rd Party Invoice Check": page_invoice_bot
}
selection = st.sidebar.radio("Navigate", list(pages.keys()))
pages[selection]()