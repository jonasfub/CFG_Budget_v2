import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import time

# --- 1. 系统配置 ---
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #0068C9; }
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    /* 打印发票时的样式 */
    @media print {
        .stApp > header, .stSidebar { display: none; }
        .invoice-box { border: none !important; box-shadow: none !important; }
    }
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

# --- 3. 核心数据函数 ---

def get_forest_list():
    if not supabase: return []
    try:
        return supabase.table("dim_forests").select("*").execute().data
    except:
        return []

# 通用：拉取单月宽表数据 (用于 Page 2 & 3)
def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    if not supabase: return pd.DataFrame()
    
    # 1. 维度骨架
    dims = supabase.table(dim_table).select("*").execute().data
    df_dims = pd.DataFrame(dims)
    if df_dims.empty: return pd.DataFrame()
    
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name'] # 兼容处理

    # 2. 实际数据
    res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
    df_facts = pd.DataFrame(res.data)
    
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

# --- 页面 1: Log Sales Data (新增模块) ---
def page_log_sales():
    st.title("🚛 Log Sales Data (流水录入)")
    st.info("此处录入每一车木材的详细过磅记录 (Transaction Level)")
    
    forests = get_forest_list()
    if not forests: st.warning("数据库连接中..."); return

    # 顶部筛选
    c1, c2 = st.columns([1, 2])
    with c1:
        sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    # 拉取产品列表供下拉菜单使用
    products = supabase.table("dim_products").select("*").execute().data
    product_codes = [p['grade_code'] for p in products] if products else []

    # 拉取现有流水
    res = supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(100).execute()
    df_trans = pd.DataFrame(res.data)
    
    if df_trans.empty:
        # 初始化空表结构
        df_trans = pd.DataFrame([{
            "date": date.today(), "ticket_number": "", "customer": "FCO",
            "grade_code": "A", "net_tonnes": 0.0, "conversion_factor": 1.0, 
            "jas": 0.0, "price": 0.0, "total_value": 0.0
        }])
    else:
        # 补充 Grade Code (因为数据库存的是 ID，这里简化处理直接存 Code 或者需要 Join，演示方便直接假设存了Code或关联)
        # 为演示方便，我们假设 transaction 表里存了 grade_code 冗余，或者我们在前端处理
        # 真实场景应该用 ID，这里为了 Editor 方便，我们在 SQL 建议里加个 grade_code 字段，或者这里只做简单展示
        pass

    # 配置编辑器
    col_cfg = {
        "id": None, "forest_id": None, "created_at": None, "grade_id": None,
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "ticket_number": st.column_config.TextColumn("Ticket #"),
        "grade_code": st.column_config.SelectboxColumn("Grade", options=product_codes, required=True),
        "net_tonnes": st.column_config.NumberColumn("Net (T)", format="%.2f"),
        "jas": st.column_config.NumberColumn("JAS", format="%.2f"),
        "price": st.column_config.NumberColumn("Price ($)", format="$%.2f"),
        "total_value": st.column_config.NumberColumn("Total ($)", format="$%.2f"),
    }

    edited_df = st.data_editor(
        df_trans, 
        key="sales_log_editor", 
        num_rows="dynamic", 
        use_container_width=True,
        column_config=col_cfg
    )

    if st.button("💾 Save Transactions"):
        # 简单保存逻辑
        recs = []
        for _, row in edited_df.iterrows():
            # 查找 Grade ID
            g_id = next((p['id'] for p in products if p['grade_code'] == row.get('grade_code')), None)
            
            recs.append({
                "forest_id": fid,
                "date": str(row['date']),
                "ticket_number": row.get('ticket_number'),
                "grade_id": g_id,
                "customer": row.get('customer'),
                "net_tonnes": row.get('net_tonnes'),
                "jas": row.get('jas'),
                "price": row.get('price'),
                "total_value": row.get('total_value')
            })
        try:
            # 批量插入/更新 (注意：transaction表最好用 id 做 key)
            # 这里简化为只做 Insert，生产环境需要处理 ID
            supabase.table("actual_sales_transactions").upsert(recs).execute()
            st.success("流水记录已保存！")
        except Exception as e:
            st.error(f"保存失败: {e}")

# --- 页面 2 & 3: Budget/Actual Input (保持原样) ---
def page_monthly_input(mode):
    st.title(f"📝 {mode} Entry (Monthly View)")
    forests = get_forest_list()
    if not forests: return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2: year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3: month_str = st.selectbox("Month", MONTHS, key=f"m_{mode}")

    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    st.caption(f"Editing: {sel_forest} | {target_date}")

    tab_vol, tab_cost = st.tabs(["🌲 Volume & Sales", "💰 Operational Costs"])

    with tab_vol:
        df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
        edited = st.data_editor(df, key=f"vol_{mode}_{target_date}", hide_index=True, use_container_width=True)
        if st.button(f"Save {mode} Volume", key=f"b1_{mode}"):
            if save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

    with tab_cost:
        df = get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
        edited = st.data_editor(df, key=f"cost_{mode}_{target_date}", hide_index=True, use_container_width=True)
        if st.button(f"Save {mode} Costs", key=f"b2_{mode}"):
            if save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

# --- 页面 4: Analysis & Invoice (新增模块) ---
def page_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    forests = get_forest_list()
    if not forests: return

    # 1. 顶部控制栏
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key="inv_f")
    with c2: year = st.selectbox("Year", [2025, 2026], key="inv_y")
    with c3: month_str = st.selectbox("Month", MONTHS, key="inv_m")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"

    # 2. 拉取数据 (Budget vs Actual)
    # 这里我们拉取 Operational Costs 和 Volume Revenue
    # Actuals
    act_costs = supabase.table("fact_operational_costs").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
    act_rev = supabase.table("fact_production_volume").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
    
    # Budgets
    bud_costs = supabase.table("fact_operational_costs").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
    bud_rev = supabase.table("fact_production_volume").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data

    # 计算总和
    total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
    total_bud_cost = sum([x['total_amount'] for x in bud_costs]) if bud_costs else 0
    total_act_rev = sum([x['amount'] for x in act_rev]) if act_rev else 0
    total_bud_rev = sum([x['amount'] for x in bud_rev]) if bud_rev else 0

    # --- Part A: 对比分析图表 ---
    st.subheader(f"📊 Budget vs Actual Analysis ({month_str} {year})")
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Revenue Performance", f"${total_act_rev:,.0f}", delta=f"${total_act_rev - total_bud_rev:,.0f} vs Budget")
    k2.metric("Cost Control", f"${total_act_cost:,.0f}", delta=f"${total_bud_cost - total_act_cost:,.0f} (Lower is better)", delta_color="inverse")
    k3.metric("Net Profit", f"${total_act_rev - total_act_cost:,.0f}")

    # 图表
    fig = go.Figure(data=[
        go.Bar(name='Budget', x=['Revenue', 'Costs'], y=[total_bud_rev, total_bud_cost], marker_color='#A9DFBF'),
        go.Bar(name='Actual', x=['Revenue', 'Costs'], y=[total_act_rev, total_act_cost], marker_color='#2874A6')
    ])
    fig.update_layout(barmode='group', title="Financial Variance Analysis")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Part B: 发票生成 (FCO -> CFG) ---
    st.subheader("📑 Generate Invoice (FCO to CFG)")
    
    with st.expander("Invoice Settings", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            mgmt_fee_pct = st.number_input("Management Fee %", 0.0, 20.0, 8.0, 0.5)
            gst_rate = 0.15
        with col_b:
            invoice_no = st.text_input("Invoice No.", f"INV-{year}{MONTH_MAP[month_str]:02d}-{fid}")
            invoice_date = st.date_input("Invoice Date", date.today())

    # 计算
    mgmt_fee_val = total_act_cost * (mgmt_fee_pct / 100)
    subtotal = total_act_cost + mgmt_fee_val
    gst_val = subtotal * gst_rate
    total_due = subtotal + gst_val

    # 渲染发票 HTML
    st.markdown(f"""
    <div style="background-color: white; padding: 40px; border: 1px solid #ddd; box-shadow: 0 4px 8px rgba(0,0,0,0.1); max-width: 800px; margin: auto; font-family: Arial, sans-serif; color: #333;" class="invoice-box">
        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 40px;">
            <div>
                <h1 style="color: #2c3e50; margin: 0;">INVOICE</h1>
                <p style="margin: 5px 0; color: #7f8c8d;">#{invoice_no}</p>
            </div>
            <div style="text-align: right;">
                <h3 style="margin: 0; color: #2c3e50;">FCO Management Ltd</h3>
                <p style="margin: 5px 0; font-size: 14px;">123 Forestry Road, Napier<br>NZBN: 9429000000000<br>GST: 123-456-789</p>
            </div>
        </div>
        
        <div style="margin-bottom: 30px; display: flex; justify-content: space-between;">
            <div>
                <strong style="color: #7f8c8d; font-size: 12px; text-transform: uppercase;">Bill To:</strong><br>
                <strong style="font-size: 16px;">CFG Forestry Group</strong><br>
                Level 1, Timber Tower<br>
                Auckland, New Zealand
            </div>
            <div style="text-align: right;">
                <strong style="color: #7f8c8d; font-size: 12px; text-transform: uppercase;">Date:</strong><br>
                {invoice_date}<br><br>
                <strong style="color: #7f8c8d; font-size: 12px; text-transform: uppercase;">For Period:</strong><br>
                {month_str} {year} - {sel_forest}
            </div>
        </div>

        <table style="width: 100%; border-collapse: collapse; margin-bottom: 30px;">
            <thead>
                <tr style="background-color: #f8f9fa; border-bottom: 2px solid #e9ecef;">
                    <th style="text-align: left; padding: 12px; color: #7f8c8d; font-weight: 600;">DESCRIPTION</th>
                    <th style="text-align: right; padding: 12px; color: #7f8c8d; font-weight: 600;">AMOUNT (NZD)</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid #f1f1f1;">
                    <td style="padding: 12px;">Operational Costs Reimbursement (See attached schedule)</td>
                    <td style="text-align: right; padding: 12px;">${total_act_cost:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f1f1;">
                    <td style="padding: 12px;">Management Fee ({mgmt_fee_pct}%)</td>
                    <td style="text-align: right; padding: 12px;">${mgmt_fee_val:,.2f}</td>
                </tr>
            </tbody>
        </table>

        <div style="display: flex; justify-content: flex-end;">
            <table style="width: 40%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px; text-align: right;">Subtotal:</td>
                    <td style="padding: 8px; text-align: right;">${subtotal:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; text-align: right;">GST (15%):</td>
                    <td style="padding: 8px; text-align: right;">${gst_val:,.2f}</td>
                </tr>
                <tr style="font-size: 18px; font-weight: bold; color: #2c3e50; border-top: 2px solid #2c3e50;">
                    <td style="padding: 12px; text-align: right;">TOTAL DUE:</td>
                    <td style="padding: 12px; text-align: right;">${total_due:,.2f}</td>
                </tr>
            </table>
        </div>
        
        <div style="margin-top: 40px; border-top: 1px solid #eee; padding-top: 20px; text-align: center; color: #95a5a6; font-size: 12px;">
            <p>Please make payment to FCO Management Ltd | Account: 01-0000-0000000-00</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.caption("Tip: Use browser 'Print' (Ctrl+P) and save as PDF to send this invoice.")


# --- 主导航 ---
st.sidebar.title("🌲 FCO Cloud ERP")
nav = st.sidebar.radio("Navigate", [
    "Dashboard", 
    "1. Log Sales Data (流水)", 
    "2. Budget Planning", 
    "3. Actuals Entry", 
    "4. Analysis & Invoice"
])

if nav == "Dashboard":
    # 简单的仪表盘逻辑 (你可以复用之前的 Dashboard 代码，这里简化展示)
    st.title("📊 Executive Dashboard")
    st.info("Welcome to FCO LogicSync OS. Select a module from the sidebar.")
elif nav == "1. Log Sales Data (流水)":
    page_log_sales()
elif nav == "2. Budget Planning":
    page_monthly_input("Budget")
elif nav == "3. Actuals Entry":
    page_monthly_input("Actual")
elif nav == "4. Analysis & Invoice":
    page_analysis_invoice()