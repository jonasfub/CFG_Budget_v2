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

def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    if not supabase: return pd.DataFrame()
    
    # 1. 维度
    dims = supabase.table(dim_table).select("*").execute().data
    df_dims = pd.DataFrame(dims)
    if df_dims.empty: return pd.DataFrame()
    
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name']

    # 2. 数据
    try:
        res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
        df_facts = pd.DataFrame(res.data)
    except: df_facts = pd.DataFrame()
    
    # 3. 合并
    if df_facts.empty:
        cols_to_keep = ['id', dim_name_col]
        if 'grade_code' in df_dims.columns: cols_to_keep.append('grade_code')
        df_merged = df_dims[cols_to_keep].rename(columns={'id': dim_id_col})
        for c in value_cols: df_merged[c] = 0.0
    else:
        df_merged = pd.merge(df_dims, df_facts, left_on='id', right_on=dim_id_col, how='left')
        for c in value_cols: df_merged[c] = df_merged[c].fillna(0.0)
    
    df_merged = df_merged.loc[:, ~df_merged.columns.duplicated()]
    df_merged = df_merged.reset_index(drop=True)

    if 'market' not in df_merged.columns and 'grade_code' in df_merged.columns:
        df_merged['market'] = df_merged['grade_code'].apply(lambda x: 'Domestic' if 'Domestic' in str(x) else 'Export')
    if 'customer' not in df_merged.columns:
        df_merged['customer'] = 'FCO' 
        
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

# --- 页面 0: Dashboard (已修复，内容回归) ---
def page_dashboard():
    st.title("📊 Executive Dashboard")
    
    forests = get_forest_list()
    if not forests: st.warning("Loading Data..."); return
    
    c1, c2 = st.columns([2, 1])
    with c1: sel_forest = st.selectbox("Forest", ["ALL"] + [f['name'] for f in forests])
    with c2: sel_year = st.selectbox("Year", [2025, 2026])
    
    # 拉取 YTD 数据
    try:
        # 1. 收入
        q_vol = supabase.table("fact_production_volume").select("*").eq("record_type", "Actual")
        if sel_forest != "ALL":
            fid = next(f['id'] for f in forests if f['name'] == sel_forest)
            q_vol = q_vol.eq("forest_id", fid)
        vol_data = q_vol.execute().data
        df_vol = pd.DataFrame(vol_data)

        # 2. 成本
        q_cost = supabase.table("fact_operational_costs").select("*").eq("record_type", "Actual")
        if sel_forest != "ALL":
            q_cost = q_cost.eq("forest_id", fid)
        cost_data = q_cost.execute().data
        df_cost = pd.DataFrame(cost_data)

        # 预处理
        rev = 0
        cost = 0
        if not df_vol.empty:
            df_vol['month'] = pd.to_datetime(df_vol['month'])
            df_vol = df_vol[df_vol['month'].dt.year == sel_year]
            rev = df_vol['amount'].sum()
        
        if not df_cost.empty:
            df_cost['month'] = pd.to_datetime(df_cost['month'])
            df_cost = df_cost[df_cost['month'].dt.year == sel_year]
            cost = df_cost['total_amount'].sum()
            
        margin = rev - cost

        # KPI 卡片
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Revenue", f"${rev:,.0f}")
        k2.metric("Total Costs", f"${cost:,.0f}")
        k3.metric("Net Profit", f"${margin:,.0f}", delta=f"{(margin/rev*100) if rev else 0:.1f}%")

        st.divider()

        # 图表
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader("Monthly P&L Trend")
            if not df_vol.empty or not df_cost.empty:
                v_m = df_vol.groupby('month')['amount'].sum().reset_index() if not df_vol.empty else pd.DataFrame()
                c_m = df_cost.groupby('month')['total_amount'].sum().reset_index() if not df_cost.empty else pd.DataFrame()
                
                if not v_m.empty: v_m.rename(columns={'amount': 'Revenue'}, inplace=True)
                if not c_m.empty: c_m.rename(columns={'total_amount': 'Costs'}, inplace=True)

                if not v_m.empty and not c_m.empty:
                    merged = pd.merge(v_m, c_m, on='month', how='outer').fillna(0)
                elif not v_m.empty:
                    merged = v_m.assign(Costs=0)
                else:
                    merged = c_m.assign(Revenue=0)
                
                if not merged.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=merged['month'], y=merged.get('Revenue',0), name='Revenue', marker_color='#27AE60'))
                    fig.add_trace(go.Bar(x=merged['month'], y=merged.get('Costs',0), name='Costs', marker_color='#C0392B'))
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data available yet.")

        with col_chart2:
            st.subheader("Cost Breakdown")
            if not df_cost.empty:
                acts = pd.DataFrame(supabase.table("dim_cost_activities").select("*").execute().data)
                if not acts.empty:
                    merged_cost = pd.merge(df_cost, acts, left_on='activity_id', right_on='id')
                    fig2 = px.pie(merged_cost, values='total_amount', names='category', hole=0.4)
                    st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No cost data.")

    except Exception as e:
        st.error(f"Error loading dashboard: {e}")


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
    
    if mode == "Budget":
        tabs = ["📋 Sales Forecast (Detailed)", "🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    else:
        tabs = ["🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
        
    current_tabs = st.tabs(tabs)

    for i, tab_name in enumerate(tabs):
        with current_tabs[i]:
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
                safe_cols = [c for c in cols_order if c in df_detail.columns]
                df_detail = df_detail[safe_cols]
                
                edited_detail = st.data_editor(df_detail, key=f"d_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=detail_cfg)
                
                if st.button("Save Forecast", key=f"b_detail_{mode}"):
                    if save_monthly_data(edited_detail, "fact_production_volume", "grade_id", fid, target_date, mode): 
                        st.success("Detailed Forecast Saved!")

            elif tab_name == "🚛 Log Transport & Volume":
                st.info("Base Volume/JAS for Transport calculations.")
                df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                cfg = {"grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True)}
                edited = st.data_editor(df, key=f"v_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
                if st.button("Save Volume", key=f"b1_{mode}"):
                    if save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

            elif tab_name == "💰 Operational & Harvesting":
                st.info("Harvesting & Ops Costs.")
                df = get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
                cfg = {"activity_id": None, "activity_name": st.column_config.TextColumn("Activity", disabled=True)}
                edited = st.data_editor(df, key=f"c_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
                if st.button("Save Costs", key=f"b2_{mode}"):
                    if save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

# --- 页面 4: Analysis & Invoice (对比分析 + 发票) ---
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

    # --- Part 1: 对比分析 (回归!) ---
    st.subheader(f"📊 Budget vs Actual ({month_str} {year})")
    
    try:
        # 获取成本
        act_costs = supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_costs = supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
        
        # 获取收入
        act_revs = supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_revs = supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data

        total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
        total_bud_cost = sum([x['total_amount'] for x in bud_costs]) if bud_costs else 0
        total_act_rev = sum([x['amount'] for x in act_revs]) if act_revs else 0
        total_bud_rev = sum([x['amount'] for x in bud_revs]) if bud_revs else 0
        
        # 显示指标
        k1, k2, k3 = st.columns(3)
        k1.metric("Revenue", f"${total_act_rev:,.0f}", delta=f"${total_act_rev - total_bud_rev:,.0f} vs Budget")
        k2.metric("Costs", f"${total_act_cost:,.0f}", delta=f"${total_bud_cost - total_act_cost:,.0f} (vs Budget)", delta_color="inverse")
        k3.metric("Net Profit", f"${total_act_rev - total_act_cost:,.0f}")

        # 显示对比图
        fig = go.Figure(data=[
            go.Bar(name='Budget', x=['Revenue', 'Costs'], y=[total_bud_rev, total_bud_cost], marker_color='#A9DFBF'),
            go.Bar(name='Actual', x=['Revenue', 'Costs'], y=[total_act_rev, total_act_cost], marker_color='#2874A6')
        ])
        fig.update_layout(barmode='group', height=300, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error loading analysis: {e}")
        total_act_cost = 0 # Fallback

    st.divider()

    # --- Part 2: 发票生成 ---
    st.subheader(f"📑 Invoice Generator")
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

# --- 升级版: 页面 5: Invoice Bot (含存储与归档功能) ---
def page_invoice_bot():
    st.title("🤖 Invoice Bot (Audit & Archive)")
    st.caption("Flow: Upload -> AI Check -> Reconcile -> Archive to Cloud Storage")

    # 分页：一个是录入复核，一个是历史查询
    tab_audit, tab_archive = st.tabs(["🚀 Upload & Audit", "🗄️ Invoice Archive"])

    # --- Tab 1: 上传与复核 ---
    with tab_audit:
        col_upload, col_review = st.columns([1, 2])
        
        with col_upload:
            st.subheader("1. Upload")
            uploaded_files = st.file_uploader("Drag PDFs here", type=["pdf"], accept_multiple_files=True)
            
            if uploaded_files:
                if st.button("🚀 Start Analysis"):
                    results = []
                    progress_bar = st.progress(0)
                    for i, file in enumerate(uploaded_files):
                        time.sleep(0.5) # Mock AI speed
                        
                        # Mock AI Logic
                        vendor = "Unknown"
                        if "Road" in file.name: vendor = "Road Maintenance"
                        elif "Harv" in file.name: vendor = "Groundbase Harvesting"
                        elif "Truck" in file.name: vendor = "Cartage"
                        
                        amount = random.randint(1000, 20000)
                        
                        # 将文件对象本身暂存，以便后续上传
                        results.append({
                            "file_obj": file, 
                            "filename": file.name, 
                            "vendor_detected": vendor,
                            "invoice_no": f"INV-{random.randint(10000,99999)}",
                            "date_detected": str(date.today()),
                            "amount_detected": float(amount)
                        })
                        progress_bar.progress((i + 1) / len(uploaded_files))
                    
                    st.session_state['ocr_results'] = results
                    st.success(f"Analyzed {len(results)} invoices.")

        with col_review:
            st.subheader("2. Review & Archive")
            
            if 'ocr_results' in st.session_state:
                results = st.session_state['ocr_results']
                reconcile_data = []
                
                # 准备展示数据
                for i, item in enumerate(results):
                    # 复核逻辑
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
                    
                    # 存入列表供展示
                    reconcile_data.append({
                        "Select": False, # 用于勾选
                        "Index": i,
                        "File": item['filename'], 
                        "Vendor": item['vendor_detected'],
                        "Inv #": item['invoice_no'],
                        "Inv Amount": item['amount_detected'], 
                        "ERP Amount": db_amount, 
                        "Diff": diff, 
                        "Status": match_status
                    })
                
                # 使用 Data Editor 允许用户勾选要归档的发票
                df_rec = pd.DataFrame(reconcile_data)
                
                st.info("Check the boxes below for invoices you want to approve and store in the cloud.")
                edited_df = st.data_editor(
                    df_rec, 
                    column_config={
                        "Select": st.column_config.CheckboxColumn("Archive?", default=True),
                        "Index": None # 隐藏索引列
                    },
                    disabled=["File", "Vendor", "Inv #", "Inv Amount", "ERP Amount", "Diff", "Status"],
                    hide_index=True,
                    use_container_width=True
                )
                
                # --- 核心：保存到云端 ---
                if st.button("💾 Confirm & Save Selected to Cloud"):
                    success_count = 0
                    progress_save = st.progress(0)
                    
                    selected_rows = edited_df[edited_df["Select"] == True]
                    total_files = len(selected_rows)
                    
                    if total_files == 0:
                        st.warning("No invoices selected.")
                    else:
                        for idx, row in selected_rows.iterrows():
                            original_index = row['Index']
                            item_data = results[original_index]
                            file_obj = item_data['file_obj']
                            
                            try:
                                # 1. 上传文件到 Supabase Storage
                                # 生成唯一文件名防止覆盖: timestamp_filename
                                file_path = f"{int(time.time())}_{item_data['filename']}"
                                file_obj.seek(0) # 重置文件指针
                                file_content = file_obj.read()
                                
                                supabase.storage.from_("invoices").upload(
                                    path=file_path, 
                                    file=file_content, 
                                    file_options={"content-type": "application/pdf"}
                                )
                                
                                # 2. 获取公开访问链接
                                public_url = supabase.storage.from_("invoices").get_public_url(file_path)
                                
                                # 3. 写入数据库 archive 表
                                record = {
                                    "invoice_no": item_data['invoice_no'],
                                    "vendor": item_data['vendor_detected'],
                                    "amount": item_data['amount_detected'],
                                    "date_on_invoice": item_data['date_detected'],
                                    "file_name": item_data['filename'],
                                    "file_url": public_url,
                                    "status": "Verified" if "Match" in row['Status'] else "Manual Check"
                                }
                                supabase.table("invoice_archive").insert(record).execute()
                                success_count += 1
                                
                            except Exception as e:
                                st.error(f"Failed to save {item_data['filename']}: {e}")
                            
                            progress_save.progress((success_count) / total_files)
                        
                        if success_count > 0:
                            st.success(f"🎉 Successfully archived {success_count} invoices! Check 'Invoice Archive' tab.")
                            # 清空 session state 以重置 (可选)
                            # del st.session_state['ocr_results'] 

    # --- Tab 2: 历史档案查询 ---
    with tab_archive:
        st.subheader("🗄️ Invoice Digital Cabinet")
        
        # 搜索栏
        col_search, _ = st.columns([1, 2])
        with col_search:
            search_vendor = st.text_input("Search Vendor / Invoice #", placeholder="Type to filter...")
        
        # 拉取数据
        try:
            query = supabase.table("invoice_archive").select("*").order("created_at", desc=True)
            if search_vendor:
                # 简单的模糊搜索
                query = query.or_(f"vendor.ilike.%{search_vendor}%,invoice_no.ilike.%{search_vendor}%")
            
            res = query.execute().data
            df_archive = pd.DataFrame(res)
            
            if not df_archive.empty:
                # 格式化显示
                st.dataframe(
                    df_archive,
                    column_config={
                        "file_url": st.column_config.LinkColumn("PDF Link", display_text="Download PDF"),
                        "created_at": st.column_config.DatetimeColumn("Archived Date", format="YYYY-MM-DD HH:mm"),
                        "amount": st.column_config.NumberColumn("Amount", format="$%.2f")
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No archived invoices found.")
                
        except Exception as e:
            st.error("Connecting to archive database...")


# --- 主导航 ---
st.sidebar.title("🌲 FCO Cloud ERP")
pages = {
    "Dashboard": page_dashboard,
    "1. Log Sales Data": page_log_sales,
    "2. Budget Planning": lambda: page_monthly_input("Budget"),
    "3. Actuals Entry": lambda: page_monthly_input("Actual"),
    "4. Analysis & Invoice": page_analysis_invoice,
    "5. 3rd Party Invoice Check": page_invoice_bot
}
selection = st.sidebar.radio("Navigate", list(pages.keys()))
pages[selection]()