import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import streamlit.components.v1 as components  # 关键：用于渲染发票

# --- 1. 系统配置 ---
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="expanded")

# 全局样式优化
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

# --- 3. 独立工具函数：生成发票 HTML (Split Logic) ---
def generate_invoice_html(invoice_no, invoice_date, bill_to, month_str, year, items, subtotal, gst_val, total_due):
    """
    生成专业的 HTML 发票代码字符串。
    CSS 中的花括号 {} 需要写成 {{ }} 以避免与 Python f-string 冲突。
    """
    
    # 构建行项目 HTML
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
            .invoice-box {{
                max-width: 800px;
                margin: auto;
                padding: 30px;
                border: 1px solid #eee;
                box-shadow: 0 0 10px rgba(0, 0, 0, .15);
                font-size: 16px;
                line-height: 24px;
                color: #555;
            }}
            .invoice-box table {{ width: 100%; line-height: inherit; text-align: left; border-collapse: collapse; }}
            .invoice-box table td {{ padding: 5px; vertical-align: top; }}
            .invoice-box table tr.top table td {{ padding-bottom: 20px; }}
            .invoice-box table tr.top table td.title {{ font-size: 45px; line-height: 45px; color: #333; }}
            .invoice-box table tr.information table td {{ padding-bottom: 40px; }}
            .invoice-box table tr.heading td {{ background: #eee; border-bottom: 1px solid #ddd; font-weight: bold; }}
            .invoice-box table tr.details td {{ padding-bottom: 20px; }}
            .invoice-box table tr.item td {{ border-bottom: 1px solid #eee; }}
            .invoice-box table tr.item.last td {{ border-bottom: none; }}
            .invoice-box table tr.total td:nth-child(2) {{ border-top: 2px solid #eee; font-weight: bold; }}
            .text-right {{ text-align: right; }}
        </style>
    </head>
    <body>
        <div class="invoice-box">
            <table cellpadding="0" cellspacing="0">
                <tr class="top">
                    <td colspan="2">
                        <table>
                            <tr>
                                <td class="title">INVOICE</td>
                                <td class="text-right">
                                    Invoice #: {invoice_no}<br>
                                    Date: {invoice_date}<br>
                                    Due: Upon Receipt
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                <tr class="information">
                    <td colspan="2">
                        <table>
                            <tr>
                                <td>
                                    <strong>FCO Management Ltd</strong><br>
                                    123 Forestry Road<br>
                                    Napier, New Zealand<br>
                                    GST: 123-456-789
                                </td>
                                <td class="text-right">
                                    <strong>Bill To:</strong><br>
                                    {bill_to}<br>
                                    Level 1, Timber Tower<br>
                                    Auckland, NZ
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                <tr class="heading">
                    <td>Description</td>
                    <td class="text-right">Amount (NZD)</td>
                </tr>
                
                {rows_html}
                
                <tr class="total">
                    <td></td>
                    <td class="text-right">
                        Subtotal: ${subtotal:,.2f}<br>
                        GST (15%): ${gst_val:,.2f}<br>
                        <strong>Total Due: ${total_due:,.2f}</strong>
                    </td>
                </tr>
            </table>
            <br>
            <p style="font-size:12px; text-align:center; color:#888;">Thank you for your business. Please pay to Acc: 01-0000-0000000-00</p>
        </div>
    </body>
    </html>
    """
    return html_content

# --- 4. 核心数据函数 ---

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
    
    # 兼容字段名
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
            
    # 返回前清理列名
    final_cols = [dim_id_col, dim_name_col] + value_cols
    return df_merged[final_cols]

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

# --- 页面 1: Log Sales Data (流水) ---
def page_log_sales():
    st.title("🚛 Log Sales Data (流水录入)")
    forests = get_forest_list()
    if not forests: st.warning("Connecting..."); return

    c1, c2 = st.columns([1, 2])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    # 拉取产品和流水
    products = supabase.table("dim_products").select("*").execute().data
    product_codes = [p['grade_code'] for p in products] if products else []
    
    res = supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(50).execute()
    df_trans = pd.DataFrame(res.data)
    
    if df_trans.empty:
        df_trans = pd.DataFrame([{
            "date": date.today(), "ticket_number": "", "customer": "FCO",
            "grade_code": "A", "net_tonnes": 0.0, "jas": 0.0, "price": 0.0, "total_value": 0.0
        }])

    col_cfg = {
        "id": None, "forest_id": None, "created_at": None, "grade_id": None,
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "grade_code": st.column_config.SelectboxColumn("Grade", options=product_codes, required=True),
        "net_tonnes": st.column_config.NumberColumn("Net (T)", format="%.2f"),
        "total_value": st.column_config.NumberColumn("Total ($)", format="$%.2f"),
    }

    edited_df = st.data_editor(df_trans, key="sales_editor", num_rows="dynamic", use_container_width=True, column_config=col_cfg)

    if st.button("💾 Save Transactions"):
        recs = []
        for _, row in edited_df.iterrows():
            g_id = next((p['id'] for p in products if p['grade_code'] == row.get('grade_code')), None)
            recs.append({
                "forest_id": fid, "date": str(row['date']), "ticket_number": row.get('ticket_number'),
                "grade_id": g_id, "customer": row.get('customer'), "net_tonnes": row.get('net_tonnes'),
                "jas": row.get('jas'), "price": row.get('price'), "total_value": row.get('total_value')
            })
        try:
            supabase.table("actual_sales_transactions").upsert(recs).execute()
            st.success("Saved!")
        except Exception as e: st.error(f"Error: {e}")

# --- 页面 2 & 3: Monthly Input (带 Tabs) ---
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

    st.markdown(f"**Editing:** {sel_forest} | {target_date}")
    
    # 使用 Tabs 分页
    tab_vol, tab_cost = st.tabs(["🌲 Volume & Sales", "💰 Operational Costs"])

    with tab_vol:
        df = get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
        
        cfg = {
            "grade_id": None, 
            "grade_code": st.column_config.TextColumn("Grade", disabled=True),
            "amount": st.column_config.NumberColumn("Total ($)", format="$%d")
        }
        edited = st.data_editor(df, key=f"vol_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
        
        if st.button(f"Save Volume ({month_str})", key=f"btn_v_{mode}", type="primary"):
            if save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

    with tab_cost:
        df = get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
        
        cfg = {
            "activity_id": None, 
            "activity_name": st.column_config.TextColumn("Activity", disabled=True),
            "total_amount": st.column_config.NumberColumn("Total ($)", format="$%d")
        }
        edited = st.data_editor(df, key=f"cost_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
        
        if st.button(f"Save Costs ({month_str})", key=f"btn_c_{mode}", type="primary"):
            if save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

# --- 页面 4: Analysis & Invoice (完整分析+发票) ---
def page_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    forests = get_forest_list()
    if not forests: return

    # 1. 筛选
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key="inv_f")
    with c2: year = st.selectbox("Year", [2025, 2026], key="inv_y")
    with c3: month_str = st.selectbox("Month", MONTHS, key="inv_m")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"

    # 2. 拉取数据 (Budget vs Actual)
    try:
        act_costs = supabase.table("fact_operational_costs").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        act_rev = supabase.table("fact_production_volume").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_costs = supabase.table("fact_operational_costs").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
        bud_rev = supabase.table("fact_production_volume").select("*").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
    except:
        st.error("Error loading data.")
        return

    # 计算总和
    total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
    total_bud_cost = sum([x['total_amount'] for x in bud_costs]) if bud_costs else 0
    total_act_rev = sum([x['amount'] for x in act_rev]) if act_rev else 0
    total_bud_rev = sum([x['amount'] for x in bud_rev]) if bud_rev else 0

    # Part A: 分析图表
    st.subheader(f"📊 Budget vs Actual ({month_str} {year})")
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Revenue", f"${total_act_rev:,.0f}", delta=f"${total_act_rev - total_bud_rev:,.0f} vs Budget")
    k2.metric("Costs", f"${total_act_cost:,.0f}", delta=f"${total_bud_cost - total_act_cost:,.0f}", delta_color="inverse")
    k3.metric("Profit", f"${total_act_rev - total_act_cost:,.0f}")

    fig = go.Figure(data=[
        go.Bar(name='Budget', x=['Revenue', 'Costs'], y=[total_bud_rev, total_bud_cost], marker_color='#A9DFBF'),
        go.Bar(name='Actual', x=['Revenue', 'Costs'], y=[total_act_rev, total_act_cost], marker_color='#2874A6')
    ])
    fig.update_layout(barmode='group', height=300, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Part B: 发票生成 (使用 components 隔离渲染)
    st.subheader("📑 Invoice Generator")
    
    col_input, col_preview = st.columns([1, 2])
    
    with col_input:
        st.markdown("##### Invoice Settings")
        bill_to = st.text_input("Bill To", "CFG Forestry Group")
        mgmt_fee_pct = st.number_input("Mgmt Fee %", 0.0, 20.0, 8.0, 0.5)
        invoice_no = st.text_input("Inv No.", f"INV-{year}{MONTH_MAP[month_str]:02d}-{fid}")
        invoice_date = st.date_input("Date", date.today())
        
        # 计算
        mgmt_fee_val = total_act_cost * (mgmt_fee_pct / 100)
        subtotal = total_act_cost + mgmt_fee_val
        gst_val = subtotal * 0.15
        total_due = subtotal + gst_val
        
        # 准备数据项
        items = [
            {"desc": f"Operational Costs Reimbursement ({month_str} {year})", "amount": total_act_cost},
            {"desc": f"Management Fee ({mgmt_fee_pct}%)", "amount": mgmt_fee_val}
        ]

    # 生成 HTML
    invoice_html = generate_invoice_html(
        invoice_no, invoice_date, bill_to, month_str, year, 
        items, subtotal, gst_val, total_due
    )

    with col_preview:
        st.markdown("##### Preview")
        # 关键：使用 components.html 渲染，可以完美显示样式
        components.html(invoice_html, height=700, scrolling=True)
        
        st.download_button(
            label="⬇️ Download Invoice (HTML)",
            data=invoice_html,
            file_name=f"{invoice_no}.html",
            mime="text/html"
        )

# --- 主导航 ---
st.sidebar.title("🌲 FCO Cloud ERP")
nav = st.sidebar.radio("Navigate", [
    "1. Log Sales Data (流水)", 
    "2. Budget Planning", 
    "3. Actuals Entry", 
    "4. Analysis & Invoice"
])

if nav == "1. Log Sales Data (流水)": page_log_sales()
elif nav == "2. Budget Planning": page_monthly_input("Budget")
elif nav == "3. Actuals Entry": page_monthly_input("Actual")
elif nav == "4. Analysis & Invoice": page_analysis_invoice()