import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import streamlit.components.v1 as components

# --- 1. 系统配置 ---
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="expanded")

# 样式优化
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #0068C9; }
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    /* 隐藏表格索引列 */
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

# --- 3. 核心功能函数 ---

def get_forest_list():
    if not supabase: return []
    try:
        return supabase.table("dim_forests").select("*").execute().data
    except:
        return []

def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    if not supabase: return pd.DataFrame()
    
    # 1. 维度骨架
    try:
        dims = supabase.table(dim_table).select("*").execute().data
        df_dims = pd.DataFrame(dims)
    except: return pd.DataFrame()
    
    if df_dims.empty: return pd.DataFrame()
    
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name']

    # 2. 实际数据
    try:
        res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
        df_facts = pd.DataFrame(res.data)
    except: return pd.DataFrame()
    
    # 3. 合并
    if df_facts.empty:
        df_merged = df_dims[['id', dim_name_col]].rename(columns={'id': dim_id_col})
        for c in value_cols: df_merged[c] = 0.0
    else:
        df_merged = pd.merge(df_dims[['id', dim_name_col]], df_facts, left_on='id', right_on=dim_id_col, how='left')
        for c in value_cols: df_merged[c] = df_merged[c].fillna(0.0)
            
    return df_merged[[dim_id_col, dim_name_col] + value_cols]

def save_monthly_data(edited_df, table_name, dim_id_col, forest_id, target_date, record_type):
    if not supabase or edited_df.empty: return False
    records = []
    for _, row in edited_df.iterrows():
        rec = {
            "forest_id": forest_id, dim_id_col: row[dim_id_col],
            "month": target_date, "record_type": record_type
        }
        for col in row.index:
            if col not in [dim_id_col, 'dim_name', 'grade_code', 'activity_name']:
                rec[col] = row[col]
        records.append(rec)
    try:
        supabase.table(table_name).upsert(records, on_conflict=f"forest_id,{dim_id_col},month,record_type").execute()
        return True
    except: return False

def generate_invoice_html(invoice_no, invoice_date, bill_to, month_str, year, items, subtotal, gst_val, total_due):
    rows_html = ""
    for item in items:
        rows_html += f"""
        <tr class="item">
            <td>{item['desc']}</td>
            <td class="text-right">${item['amount']:,.2f}</td>
        </tr>
        """
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #555; background-color: #fff; padding: 20px; }}
            .invoice-box {{ max-width: 800px; margin: auto; padding: 30px; border: 1px solid #eee; box-shadow: 0 0 10px rgba(0, 0, 0, .15); font-size: 16px; line-height: 24px; color: #555; }}
            .invoice-box table {{ width: 100%; line-height: inherit; text-align: left; border-collapse: collapse; }}
            .invoice-box table td {{ padding: 5px; vertical-align: top; }}
            .invoice-box table tr.top table td {{ padding-bottom: 20px; }}
            .invoice-box table tr.top table td.title {{ font-size: 45px; line-height: 45px; color: #333; }}
            .invoice-box table tr.heading td {{ background: #eee; border-bottom: 1px solid #ddd; font-weight: bold; }}
            .invoice-box table tr.item td {{ border-bottom: 1px solid #eee; }}
            .invoice-box table tr.total td:nth-child(2) {{ border-top: 2px solid #eee; font-weight: bold; }}
            .text-right {{ text-align: right; }}
        </style>
    </head>
    <body>
        <div class="invoice-box">
            <table cellpadding="0" cellspacing="0">
                <tr class="top"><td colspan="2"><table><tr><td class="title">INVOICE</td><td class="text-right">Inv #: {invoice_no}<br>Date: {invoice_date}</td></tr></table></td></tr>
                <tr class="information"><td colspan="2"><table><tr><td><strong>FCO Management Ltd</strong><br>Napier, NZ</td><td class="text-right"><strong>Bill To:</strong><br>{bill_to}</td></tr></table></td></tr>
                <tr class="heading"><td>Description</td><td class="text-right">Amount (NZD)</td></tr>
                {rows_html}
                <tr class="total"><td></td><td class="text-right">Subtotal: ${subtotal:,.2f}<br>GST (15%): ${gst_val:,.2f}<br><strong>Total Due: ${total_due:,.2f}</strong></td></tr>
            </table>
        </div>
    </body>
    </html>
    """
    return html_content

# --- 页面模块 ---

def page_dashboard():
    st.title("📊 Executive Dashboard")
    
    forests = get_forest_list()
    if not forests: st.warning("Connecting to DB..."); return
    
    col1, col2 = st.columns([2, 1])
    with col1: sel_forest = st.selectbox("Forest", ["ALL"] + [f['name'] for f in forests])
    with col2: sel_year = st.selectbox("Year", [2025, 2026])
    
    # 获取数据
    try:
        query_vol = supabase.table("fact_production_volume").select("*").eq("record_type", "Actual")
        query_cost = supabase.table("fact_operational_costs").select("*").eq("record_type", "Actual")
        
        if sel_forest != "ALL":
            fid = next(f['id'] for f in forests if f['name'] == sel_forest)
            query_vol = query_vol.eq("forest_id", fid)
            query_cost = query_cost.eq("forest_id", fid)
            
        df_vol = pd.DataFrame(query_vol.execute().data)
        df_cost = pd.DataFrame(query_cost.execute().data)
        
        # 预处理
        if not df_vol.empty: 
            df_vol['month'] = pd.to_datetime(df_vol['month'])
            df_vol = df_vol[df_vol['month'].dt.year == sel_year]
        if not df_cost.empty:
            df_cost['month'] = pd.to_datetime(df_cost['month'])
            df_cost = df_cost[df_cost['month'].dt.year == sel_year]
            
        rev = df_vol['amount'].sum() if not df_vol.empty else 0
        cost = df_cost['total_amount'].sum() if not df_cost.empty else 0
        margin = rev - cost
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Revenue", f"${rev:,.0f}")
        k2.metric("Total Costs", f"${cost:,.0f}")
        k3.metric("Net Margin", f"${margin:,.0f}", delta=f"{(margin/rev*100) if rev else 0:.1f}%")
        
        st.divider()
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Monthly P&L")
            if not df_vol.empty or not df_cost.empty:
                v_m = df_vol.groupby('month')['amount'].sum().reset_index() if not df_vol.empty else pd.DataFrame()
                c_m = df_cost.groupby('month')['total_amount'].sum().reset_index() if not df_cost.empty else pd.DataFrame()
                merged = pd.merge(v_m, c_m, on='month', how='outer').fillna(0) if not v_m.empty and not c_m.empty else (v_m if not v_m.empty else c_m)
                if not merged.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=merged.get('month'), y=merged.get('amount',0), name='Revenue', marker_color='#27AE60'))
                    fig.add_trace(go.Bar(x=merged.get('month'), y=merged.get('total_amount',0), name='Costs', marker_color='#C0392B'))
                    st.plotly_chart(fig, use_container_width=True)
        
        with c2:
            st.subheader("Cost Breakdown")
            if not df_cost.empty:
                acts = pd.DataFrame(supabase.table("dim_cost_activities").select("*").execute().data)
                if not acts.empty:
                    merged_cost = pd.merge(df_cost, acts, left_on='activity_id', right_on='id')
                    fig2 = px.pie(merged_cost, values='total_amount', names='category', hole=0.4, title="By Category")
                    st.plotly_chart(fig2, use_container_width=True)
                    
    except Exception as e:
        st.error(f"Dashboard Error: {e}")

def page_log_sales():
    st.title("🚛 Log Sales Data (Transaction Level)")
    forests = get_forest_list()
    if not forests: return
    
    c1, c2 = st.columns([1, 2])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    products = supabase.table("dim_products").select("*").execute().data
    codes = [p['grade_code'] for p in products] if products else []
    
    res = supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(50).execute()
    df = pd.DataFrame(res.data)
    if df.empty: df = pd.DataFrame([{"date": date.today(), "grade_code": "A", "net_tonnes": 0.0, "total_value": 0.0}])
    
    col_cfg = {
        "id": None, "forest_id": None, "grade_id": None, "created_at": None,
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "grade_code": st.column_config.SelectboxColumn("Grade", options=codes, required=True),
        "total_value": st.column_config.NumberColumn("Total ($)", format="$%.2f")
    }
    edited = st.data_editor(df, key="log_sales", num_rows="dynamic", use_container_width=True, column_config=col_cfg)
    
    if st.button("Save Transactions"):
        recs = []
        for _, row in edited.iterrows():
            gid = next((p['id'] for p in products if p['grade_code'] == row.get('grade_code')), None)
            recs.append({
                "forest_id": fid, "date": str(row['date']), "ticket_number": row.get('ticket_number'),
                "grade_id": gid, "customer": row.get('customer'), "net_tonnes": row.get('net_tonnes'),
                "jas": row.get('jas'), "price": row.get('price'), "total_value": row.get('total_value')
            })
        try:
            supabase.table("actual_sales_transactions").upsert(recs).execute()
            st.success("Saved!")
        except: st.error("Save failed")

def page_monthly_input(mode):
    st.title(f"📝 {mode} Entry (Monthly)")
    forests = get_forest_list()
    if not forests: return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2: year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3: month_str = st.selectbox("Month", MONTHS, key=f"m_{mode}")

    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    st.markdown(f"**Editing:** {sel_forest} | {target_date}")
    
    # --- 这里修改了 Tab 名称，响应你的 "Log Transport Cost" 需求 ---
    tab_vol, tab_cost = st.tabs(["🚛 Log Transport & Volume", "💰 Operational & Harvesting Costs"])

    with tab_vol:
        st.info("Input Volume / JAS / Price here. (Basis for Transport calculations)")
        df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
        
        cfg = {
            "grade_id": None, 
            "grade_code": st.column_config.TextColumn("Grade", disabled=True),
            "amount": st.column_config.NumberColumn("Amount ($)", format="$%d")
        }
        edited = st.data_editor(df, key=f"vol_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
        
        if st.button(f"Save Volume ({month_str})", key=f"btn_v_{mode}", type="primary"):
            if save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

    with tab_cost:
        st.info("Input Harvesting, Transport, and Operational Costs here.")
        # 这里会显示所有 dim_cost_activities 里的项目，包括我们刚添加的 Harvesting
        df = get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
        
        cfg = {
            "activity_id": None, 
            "activity_name": st.column_config.TextColumn("Activity", disabled=True),
            "total_amount": st.column_config.NumberColumn("Total ($)", format="$%d")
        }
        edited = st.data_editor(df, key=f"cost_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
        
        if st.button(f"Save Costs ({month_str})", key=f"btn_c_{mode}", type="primary"):
            if save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

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

    # 获取数据
    try:
        act_costs = supabase.table("fact_operational_costs").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
    except: total_act_cost = 0

    st.subheader(f"Invoice Generation ({month_str} {year})")
    
    col_input, col_preview = st.columns([1, 2])
    
    with col_input:
        st.markdown("##### Settings")
        bill_to = st.text_input("Bill To", "CFG Forestry Group")
        mgmt_fee_pct = st.number_input("Mgmt Fee %", 0.0, 20.0, 8.0, 0.5)
        invoice_no = st.text_input("Inv No.", f"INV-{year}{MONTH_MAP[month_str]:02d}-{fid}")
        
        mgmt_fee_val = total_act_cost * (mgmt_fee_pct / 100)
        subtotal = total_act_cost + mgmt_fee_val
        gst_val = subtotal * 0.15
        total_due = subtotal + gst_val
        
        items = [
            {"desc": f"Operational & Harvesting Costs ({month_str} {year})", "amount": total_act_cost},
            {"desc": f"Management Fee ({mgmt_fee_pct}%)", "amount": mgmt_fee_val}
        ]

    # 生成 HTML
    invoice_html = generate_invoice_html(invoice_no, date.today(), bill_to, month_str, year, items, subtotal, gst_val, total_due)

    with col_preview:
        components.html(invoice_html, height=700, scrolling=True)
        st.download_button("⬇️ Download HTML", invoice_html, file_name=f"{invoice_no}.html", mime="text/html")

# --- 主导航 ---
st.sidebar.title("🌲 FCO Cloud ERP")
# 这里一定要用字典映射或者准确的字符串匹配
pages = {
    "Dashboard": page_dashboard,
    "1. Log Sales Data (Transaction)": page_log_sales,
    "2. Budget Planning": lambda: page_monthly_input("Budget"),
    "3. Actuals Entry": lambda: page_monthly_input("Actual"),
    "4. Analysis & Invoice": page_analysis_invoice
}

selection = st.sidebar.radio("Navigate", list(pages.keys()))
pages[selection]()