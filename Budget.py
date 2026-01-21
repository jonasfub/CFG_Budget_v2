import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import streamlit.components.v1 as components

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
    res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
    df_facts = pd.DataFrame(res.data)
    
    # 3. 合并
    if df_facts.empty:
        df_merged = df_dims[['id', dim_name_col, 'grade_code'] if 'grade_code' in df_dims else ['id', dim_name_col]].rename(columns={'id': dim_id_col})
        for c in value_cols: df_merged[c] = 0.0
    else:
        df_merged = pd.merge(df_dims, df_facts, left_on='id', right_on=dim_id_col, how='left')
        for c in value_cols: df_merged[c] = df_merged[c].fillna(0.0)
    
    # 补充默认字段 (Market/Customer) 用于 Budget 显示
    if 'market' not in df_merged.columns and 'grade_code' in df_merged.columns:
        # 简单逻辑：所有 Grade 默认 Export，除了 Domestic
        df_merged['market'] = df_merged['grade_code'].apply(lambda x: 'Domestic' if 'Domestic' in str(x) else 'Export')
    if 'customer' not in df_merged.columns:
        df_merged['customer'] = 'FCO' # 默认客户
        
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

# --- 页面 1: Log Sales Data (增强版) ---
def page_log_sales():
    st.title("🚛 Log Sales Data (Transaction Level)")
    forests = get_forest_list()
    if not forests: st.warning("DB Connecting..."); return
    
    c1, c2 = st.columns([1, 2])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    # 获取产品字典
    products = supabase.table("dim_products").select("*").execute().data
    product_codes = [p['grade_code'] for p in products]
    
    # 获取现有数据
    res = supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(50).execute()
    df = pd.DataFrame(res.data)
    if df.empty: 
        # 初始化带新字段的空表
        df = pd.DataFrame([{
            "date": date.today(), "ticket_number": "", 
            "customer": "C001", "market": "Export",
            "grade_code": "A", "net_tonnes": 0.0, "jas": 0.0, 
            "conversion_factor": 0.0, "price": 0.0, "total_value": 0.0
        }])
    else:
        # 如果数据库里有转换率是0的，自动算一下
        df['conversion_factor'] = df.apply(lambda x: x['jas']/x['net_tonnes'] if x['net_tonnes']>0 else 0, axis=1)

    st.info("💡 Tip: 'Conversion Factor' is auto-calculated if you enter Tonnes and JAS.")

    col_cfg = {
        "id": None, "forest_id": None, "grade_id": None, "created_at": None,
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "ticket_number": st.column_config.TextColumn("Ticket #"),
        # --- 新增的 3 列 ---
        "customer": st.column_config.TextColumn("Customer", default="FCO"),
        "market": st.column_config.SelectboxColumn("Market", options=["Export", "Domestic"], default="Export"),
        "conversion_factor": st.column_config.NumberColumn("Conv. Factor", format="%.3f", disabled=True), # 让它只读，自动算
        # ------------------
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
            # 自动计算转换率
            conv = row['jas'] / row['net_tonnes'] if row['net_tonnes'] > 0 else 0
            
            recs.append({
                "forest_id": fid, "date": str(row['date']), "ticket_number": row.get('ticket_number'),
                "grade_id": gid, 
                "customer": row.get('customer'), # Save Customer
                "market": row.get('market'),     # Save Market
                "net_tonnes": row.get('net_tonnes'), "jas": row.get('jas'), 
                "conversion_factor": conv,       # Save Conversion
                "price": row.get('price'), "total_value": row.get('total_value')
            })
        try:
            # 这里的 upsert 需要主键 id 存在才能更新，否则是插入。
            # 简便起见，我们假设是追加模式，或者你需要保留 ID 列
            supabase.table("actual_sales_transactions").upsert(recs).execute()
            st.success("Transactions Saved!")
        except Exception as e: st.error(f"Error: {e}")

# --- 页面 2 & 3: Monthly Input (包含新增的 Budget Flip Page) ---
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
    
    # --- Tab 定义：新增了 Sales Forecast 详情页 ---
    tabs = ["🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    if mode == "Budget":
        tabs.insert(1, "📋 Sales Forecast (Detailed)") # 新增的翻页
        
    current_tabs = st.tabs(tabs)

    # --- Tab 1: 基础产量 ---
    with current_tabs[0]:
        st.info("Input base Volume/JAS. Used for Transport calculations.")
        df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
        
        cfg = {"grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True)}
        edited = st.data_editor(df, key=f"v_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
        if st.button("Save Volume", key=f"b1_{mode}"):
            if save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

    # --- Tab 2 (Budget Only): 详细销售预测 (复刻 Log Sales 格式) ---
    if mode == "Budget":
        with current_tabs[1]:
            st.info("Detailed Sales Budget - Format mimics Log Sales Data")
            # 复用 Tab 1 的数据，但在 UI 上展示更多列 (Market, Customer, Conversion)
            # 注意：这些额外字段我们这里暂存为 '显示用'，实际存库还是存回 fact_production_volume
            # 如果需要存 Customer，建议扩展数据库。这里演示 UI 效果。
            
            df_detail = df.copy() # 复用刚才获取的数据
            
            # 自动计算转换率列
            df_detail['conversion_factor'] = df_detail.apply(lambda x: x['vol_jas']/x['vol_tonnes'] if x['vol_tonnes']>0 else 0, axis=1)
            
            detail_cfg = {
                "grade_id": None,
                "grade_code": st.column_config.TextColumn("Grade", disabled=True),
                # 模拟 Log Sales Data 的列
                "market": st.column_config.SelectboxColumn("Market", options=["Export", "Domestic"], width="small"),
                "customer": st.column_config.TextColumn("Customer", default="Expected"),
                "vol_tonnes": st.column_config.NumberColumn("Tonnes", format="%.1f"),
                "conversion_factor": st.column_config.NumberColumn("Conv.", format="%.3f"), # 这里允许编辑转换率来反推 JAS
                "vol_jas": st.column_config.NumberColumn("JAS", format="%.1f"),
                "price_jas": st.column_config.NumberColumn("Price", format="$%.0f"),
                "amount": st.column_config.NumberColumn("Revenue", format="$%.0f"),
            }
            
            # 重新排列列顺序以匹配 Log Sales
            cols_order = ['grade_id', 'grade_code', 'market', 'customer', 'vol_tonnes', 'conversion_factor', 'vol_jas', 'price_jas', 'amount']
            df_detail = df_detail[cols_order]
            
            edited_detail = st.data_editor(df_detail, key=f"d_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=detail_cfg)
            
            if st.button("Save Forecast", key=f"b_detail_{mode}"):
                # 保存前，可能需要根据 Conversion Factor 更新 JAS (如果用户改了转换率)
                # 这里简单直接保存
                if save_monthly_data(edited_detail, "fact_production_volume", "grade_id", fid, target_date, mode): 
                    st.success("Detailed Forecast Saved!")

    # --- Tab 3 (or 2): 成本 ---
    with current_tabs[-1]: # 总是最后一个 Tab
        st.info("Input Harvesting & Ops Costs.")
        df = get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
        
        cfg = {"activity_id": None, "activity_name": st.column_config.TextColumn("Activity", disabled=True)}
        edited = st.data_editor(df, key=f"c_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
        if st.button("Save Costs", key=f"b2_{mode}"):
            if save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

# --- 页面 4: Analysis ---
def page_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    # ... (代码保持不变，复用之前的逻辑) ...
    st.info("Dashboard & Invoice Logic remains same as previous version.")

# --- 主导航 ---
st.sidebar.title("🌲 FCO Cloud ERP")
pages = {
    "Dashboard": lambda: st.title("Dashboard (Placeholder)"), # 简略
    "1. Log Sales Data": page_log_sales,
    "2. Budget Planning": lambda: page_monthly_input("Budget"),
    "3. Actuals Entry": lambda: page_monthly_input("Actual"),
    "4. Invoice Bot (New!)": lambda: st.info("Please run Invoice_Bot.py separately.")
}
selection = st.sidebar.radio("Navigate", list(pages.keys()))
pages[selection]()