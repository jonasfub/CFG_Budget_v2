import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit.components.v1 as components
from datetime import date
import time
import backend # <--- 导入后端模块

# 全局常量
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# --- View 1: Dashboard ---
def view_dashboard():
    st.title("📊 Executive Dashboard")
    forests = backend.get_forest_list()
    if not forests: st.warning("Loading..."); return
    
    c1, c2 = st.columns([2, 1])
    with c1: sel_forest = st.selectbox("Forest", ["ALL"] + [f['name'] for f in forests])
    with c2: sel_year = st.selectbox("Year", [2025, 2026])
    
    # ... (这里放入之前 page_dashboard 的其余代码，把 supabase 调用改成 backend.supabase) ...
    # 为了节省篇幅，核心逻辑是把 supabase.table... 
    # 替换为调用 backend.supabase.table... 或者直接在 view 里也创建一个 supabase 引用
    # 建议：在 view 里写：supabase = backend.supabase
    
    supabase = backend.supabase
    # ... (其余 Dashboard 代码) ...
    # 示例结束

# --- View 2: Log Sales ---
def view_log_sales():
    st.title("🚛 Log Sales Data (Transaction Level)")
    supabase = backend.supabase
    forests = backend.get_forest_list()
    if not forests: return
    
    # ... (复制 page_log_sales 的代码) ...
    # 注意：涉及 supabase 操作的代码不需要变
    
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

# --- View 3: Monthly Input ---
def view_monthly_input(mode):
    st.title(f"📝 {mode} Planning")
    forests = backend.get_forest_list()
    if not forests: return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2: year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3: month_str = st.selectbox("Month", MONTHS, key=f"m_{mode}")

    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    # 引用 backend 的数据获取函数
    if mode == "Budget":
        tabs = ["📋 Sales Forecast (Detailed)", "🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    else:
        tabs = ["🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    
    current_tabs = st.tabs(tabs)

    for i, tab_name in enumerate(tabs):
        with current_tabs[i]:
            if tab_name == "📋 Sales Forecast (Detailed)":
                df = backend.get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                # ... (处理逻辑同前，只需把 save_monthly_data 换成 backend.save_monthly_data) ...
                # 示例:
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
                    if backend.save_monthly_data(edited_detail, "fact_production_volume", "grade_id", fid, target_date, mode): 
                        st.success("Detailed Forecast Saved!")

            elif tab_name == "🚛 Log Transport & Volume":
                 df = backend.get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                 cfg = {"grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True)}
                 edited = st.data_editor(df, key=f"v_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
                 if st.button("Save Volume", key=f"b1_{mode}"):
                     if backend.save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

            elif tab_name == "💰 Operational & Harvesting":
                 df = backend.get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
                 cfg = {"activity_id": None, "activity_name": st.column_config.TextColumn("Activity", disabled=True)}
                 edited = st.data_editor(df, key=f"c_{mode}_{target_date}", hide_index=True, use_container_width=True, column_config=cfg)
                 if st.button("Save Costs", key=f"b2_{mode}"):
                     if backend.save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")

# --- View 4: Analysis & Invoice ---
def view_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    forests = backend.get_forest_list()
    supabase = backend.supabase
    if not forests: return
    
    # ... (复制之前 page_analysis_invoice 的代码) ...
    # 记得替换 generate_invoice_html -> backend.generate_invoice_html
    # 记得替换 components -> streamlit.components.v1
    
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key="inv_f")
    with c2: year = st.selectbox("Year", [2025, 2026], key="inv_y")
    with c3: month_str = st.selectbox("Month", MONTHS, key="inv_m")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"

    # Part 1: 对比分析
    try:
        act_costs = supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_costs = supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
        act_revs = supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_revs = supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data

        total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
        total_bud_cost = sum([x['total_amount'] for x in bud_costs]) if bud_costs else 0
        total_act_rev = sum([x['amount'] for x in act_revs]) if act_revs else 0
        total_bud_rev = sum([x['amount'] for x in bud_revs]) if bud_revs else 0
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Revenue", f"${total_act_rev:,.0f}", delta=f"${total_act_rev - total_bud_rev:,.0f} vs Budget")
        k2.metric("Costs", f"${total_act_cost:,.0f}", delta=f"${total_bud_cost - total_act_cost:,.0f} (vs Budget)", delta_color="inverse")
        k3.metric("Net Profit", f"${total_act_rev - total_act_cost:,.0f}")

        fig = go.Figure(data=[
            go.Bar(name='Budget', x=['Revenue', 'Costs'], y=[total_bud_rev, total_bud_cost], marker_color='#A9DFBF'),
            go.Bar(name='Actual', x=['Revenue', 'Costs'], y=[total_act_rev, total_act_cost], marker_color='#2874A6')
        ])
        fig.update_layout(barmode='group', height=300, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")
        total_act_cost = 0

    st.divider()

    # Part 2: 发票生成
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

    invoice_html = backend.generate_invoice_html(invoice_no, date.today(), bill_to, month_str, year, items, subtotal, gst_val, total_due)
    with col_preview:
        components.html(invoice_html, height=700, scrolling=True)
        st.download_button("⬇️ Download HTML", invoice_html, file_name=f"{invoice_no}.html", mime="text/html")

# --- View 5: Invoice Bot ---
def view_invoice_bot():
    st.title("🤖 Invoice Bot (Audit & Archive)")
    backend.init_gemini() # 初始化 AI
    supabase = backend.supabase
    
    # ... (复制 page_invoice_bot 代码，调用 backend.real_extract_invoice_data) ...
    # 示例结构：
    tab_audit, tab_archive = st.tabs(["🚀 Upload & Audit", "🗄️ Invoice Archive"])
    
    with tab_audit:
        uploaded_files = st.file_uploader("Drag PDFs here", type=["pdf"], accept_multiple_files=True)
        if uploaded_files and st.button("🚀 Start Analysis"):
             results = []
             for file in uploaded_files:
                 data = backend.real_extract_invoice_data(file)
                 data['file_obj'] = file
                 results.append(data)
             st.session_state['ocr_results'] = results
        
        if 'ocr_results' in st.session_state:
             # ... (复核表格逻辑) ...
             # 注意：保存到 storage 时调用 backend.supabase.storage...
             pass
    
    with tab_archive:
        # ... (查询逻辑) ...
        pass