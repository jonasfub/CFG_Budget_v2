import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit.components.v1 as components
from datetime import date
import time
import backend 

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# --- View 1: Dashboard ---
def view_dashboard():
    st.title("📊 Executive Dashboard")
    
    forests = backend.get_forest_list()
    if not forests: 
        st.warning("正在连接数据库或数据库为空...")
        return
    
    c1, c2 = st.columns([2, 1])
    with c1: 
        sel_forest = st.selectbox("Forest", ["ALL"] + [f['name'] for f in forests])
    with c2: 
        sel_year = st.selectbox("Year", [2025, 2026])
    
    try:
        q_vol = backend.supabase.table("fact_production_volume").select("*").eq("record_type", "Actual")
        if sel_forest != "ALL":
            fid = next(f['id'] for f in forests if f['name'] == sel_forest)
            q_vol = q_vol.eq("forest_id", fid)
        vol_data = q_vol.execute().data
        df_vol = pd.DataFrame(vol_data)

        q_cost = backend.supabase.table("fact_operational_costs").select("*").eq("record_type", "Actual")
        if sel_forest != "ALL":
            if 'fid' in locals():
                q_cost = q_cost.eq("forest_id", fid)
            else:
                 fid = next(f['id'] for f in forests if f['name'] == sel_forest)
                 q_cost = q_cost.eq("forest_id", fid)

        cost_data = q_cost.execute().data
        df_cost = pd.DataFrame(cost_data)

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

        k1, k2, k3 = st.columns(3)
        k1.metric("Total Revenue", f"${rev:,.0f}")
        k2.metric("Total Costs", f"${cost:,.0f}")
        k3.metric("Net Profit", f"${margin:,.0f}", delta=f"{(margin/rev*100) if rev else 0:.1f}%")

        st.divider()

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
                    st.plotly_chart(fig, width="stretch")
            else:
                st.info("No data available yet.")

        with col_chart2:
            st.subheader("Cost Breakdown")
            if not df_cost.empty:
                try:
                    acts = pd.DataFrame(backend.supabase.table("dim_cost_activities").select("*").execute().data)
                    if not acts.empty:
                        merged_cost = pd.merge(df_cost, acts, left_on='activity_id', right_on='id')
                        fig2 = px.pie(merged_cost, values='total_amount', names='category', hole=0.4)
                        st.plotly_chart(fig2, width="stretch")
                except:
                    st.info("Could not load categories.")
            else:
                st.info("No cost data.")

    except Exception as e:
        st.error(f"Error loading dashboard: {e}")


# --- View 2: Log Sales ---
def view_log_sales():
    st.title("🚛 Log Sales Data (Transaction Level)")
    
    forests = backend.get_forest_list()
    if not forests: return
    
    c1, c2 = st.columns([1, 2])
    with c1: 
        sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    products = backend.supabase.table("dim_products").select("*").execute().data
    product_codes = [p['grade_code'] for p in products] if products else []
    
    res = backend.supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(50).execute()
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
    
    edited = st.data_editor(df, key="log_sales", num_rows="dynamic", width="stretch", column_config=col_cfg)
    
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
            backend.supabase.table("actual_sales_transactions").upsert(recs).execute()
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
    
    if mode == "Budget":
        tabs = ["📋 Sales Forecast (Detailed)", "🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    else:
        tabs = ["🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    
    current_tabs = st.tabs(tabs)

    for i, tab_name in enumerate(tabs):
        with current_tabs[i]:
            
            if tab_name == "📋 Sales Forecast (Detailed)":
                df = backend.get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                
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
                
                edited_detail = st.data_editor(df_detail, key=f"d_{mode}_{target_date}", hide_index=True, width="stretch", column_config=detail_cfg)
                
                if st.button("Save Forecast", key=f"b_detail_{mode}"):
                    if backend.save_monthly_data(edited_detail, "fact_production_volume", "grade_id", fid, target_date, mode): 
                        st.success("Detailed Forecast Saved!")

            elif tab_name == "🚛 Log Transport & Volume":
                 df = backend.get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                 
                 cfg = {"grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True)}
                 edited = st.data_editor(df, key=f"v_{mode}_{target_date}", hide_index=True, width="stretch", column_config=cfg)
                 
                 if st.button("Save Volume", key=f"b1_{mode}"):
                     if backend.save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

            elif tab_name == "💰 Operational & Harvesting":
                 df = backend.get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
                 
                 cfg = {"activity_id": None, "activity_name": st.column_config.TextColumn("Activity", disabled=True)}
                 edited = st.data_editor(df, key=f"c_{mode}_{target_date}", hide_index=True, width="stretch", column_config=cfg)
                 
                 if st.button("Save Costs", key=f"b2_{mode}"):
                     if backend.save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): st.success("Saved!")


# --- View 4: Analysis & Invoice ---
def view_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    
    forests = backend.get_forest_list()
    supabase = backend.supabase
    if not forests: return
    
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key="inv_f")
    with c2: year = st.selectbox("Year", [2025, 2026], key="inv_y")
    with c3: month_str = st.selectbox("Month", MONTHS, key="inv_m")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"

    st.subheader(f"📊 Budget vs Actual ({month_str} {year})")
    try:
        act_costs = backend.supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_costs = backend.supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
        act_revs = backend.supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_revs = backend.supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data

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
        st.plotly_chart(fig, width="stretch")

    except Exception as e:
        st.error(f"Error loading analysis: {e}")
        total_act_cost = 0

    st.divider()

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


# --- View 5: Invoice Bot (Multi-Invoice Support) ---
# --- 替换 views.py 中的 view_invoice_bot 函数 (完整版) ---

# --- 请将此函数完全替换 views.py 中的 view_invoice_bot ---

def view_invoice_bot():
    st.title("🤖 Invoice Bot (Audit & Archive)")
    
    # 检查 API Key
    if not backend.check_google_key():
        st.error("⚠️ Google API Key missing! Please check .streamlit/secrets.toml")
        return
    
    tab_audit, tab_archive = st.tabs(["🚀 Upload & Audit", "🗄️ Invoice Archive"])
    
    # --- Tab 1: 上传与审计 ---
    with tab_audit:
        col_upload, col_review = st.columns([1, 2])
        
        with col_upload:
            st.subheader("1. Upload")
            uploaded_files = st.file_uploader("Drag PDFs here", type=["pdf"], accept_multiple_files=True)
            
            if uploaded_files:
                if st.button("🚀 Start AI Analysis", type="primary"):
                    results = []
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total_files = len(uploaded_files)
                    
                    for i, file in enumerate(uploaded_files):
                        status_text.markdown(f"**Analyzing {i+1}/{total_files}:** `{file.name}`...")
                        
                        # 调用后端读取 (现在后端会返回一个列表)
                        data_list = backend.real_extract_invoice_data(file)
                        
                        # 将文件对象绑定回去，以便后续保存使用
                        for item in data_list:
                            item['file_obj'] = file
                            
                        results.extend(data_list)
                        
                        progress_bar.progress((i + 1) / total_files)
                    
                    progress_bar.progress(100)
                    status_text.success("✅ Analysis Complete!")
                    time.sleep(1)
                    status_text.empty()
                    progress_bar.empty()
                    st.session_state['ocr_results'] = results

        with col_review:
            st.subheader("2. Review & Archive")
            
            if 'ocr_results' in st.session_state:
                results = st.session_state['ocr_results']
                reconcile_data = []
                
                for i, item in enumerate(results):
                    # --- [关键修复] 变量必须在逻辑开始前初始化 ---
                    match_status = "❌ Not Found"
                    db_amount = 0.0
                    diff = 0.0
                    # ----------------------------------------
                    
                    # 1. 检查 AI 是否报错
                    if item.get("vendor_detected") == "Error":
                        match_status = "❌ AI Error"
                        # 即使出错，db_amount 也要保持为 0.0，防止下面引用报错
                    else:
                        # 2. 数据库匹配逻辑
                        # 先根据 Vendor 名字去 dim_cost_activities 找 ID
                        # 注意：这里用了 ilike 模糊匹配
                        acts = backend.supabase.table("dim_cost_activities").select("id").ilike("activity_name", f"%{item['vendor_detected']}%").execute().data
                        
                        if acts:
                            act_id = acts[0]['id']
                            # 再去 fact_operational_costs 表找 Actual 费用
                            # 这里逻辑是：查找同 Activity 下的所有 Actual 记录 (实际项目中可能需要加月份过滤)
                            costs = backend.supabase.table("fact_operational_costs").select("total_amount")\
                                .eq("activity_id", act_id).eq("record_type", "Actual").execute().data
                            
                            if costs:
                                # 如果找到多条，这里简化取第一条，或者求和
                                db_amount = float(costs[0]['total_amount'])
                                diff = float(item['amount_detected']) - db_amount
                                
                                # 判断差异是否在允许范围内 (比如 $1.00)
                                if abs(diff) < 1.0: 
                                    match_status = "✅ Match"
                                else: 
                                    match_status = "⚠️ Variance"

                    # 3. 构造显示数据行
                    reconcile_data.append({
                        "Select": False, 
                        "Index": i, # 用于后续找回原始数据
                        "File": item.get('filename'), 
                        "Vendor": item.get('vendor_detected'),
                        "Date": item.get('invoice_date'),       # 新增字段
                        "Desc": item.get('description'),        # 新增字段
                        "Inv #": item.get('invoice_no', ''), 
                        "Inv Amount": item.get('amount_detected', 0), 
                        "ERP Amount": db_amount,    # 这里的 db_amount 肯定已经被初始化过
                        "Diff": diff,               # diff 也是
                        "Status": match_status
                    })
                
                df_rec = pd.DataFrame(reconcile_data)
                
                if not df_rec.empty:
                    # 显示可编辑表格 (Data Editor)
                    edited_df = st.data_editor(
                        df_rec, 
                        column_config={
                            "Select": st.column_config.CheckboxColumn("Archive?", default=True), 
                            "Index": None, # 隐藏索引列
                            "Date": st.column_config.DateColumn("Inv Date", format="YYYY-MM-DD"),
                            "Desc": st.column_config.TextColumn("Summary", width="medium"),
                            "Inv Amount": st.column_config.NumberColumn(format="$%.2f"),
                            "ERP Amount": st.column_config.NumberColumn(format="$%.2f"),
                            "Diff": st.column_config.NumberColumn(format="$%.2f"),
                        },
                        hide_index=True, 
                        width="stretch"
                    )
                    
                    # 4. 保存按钮逻辑
                    if st.button("💾 Confirm & Save"):
                        save_status = st.empty()
                        selected_rows = edited_df[edited_df["Select"] == True]
                        
                        if not selected_rows.empty:
                            save_status.info("Saving...")
                            for idx, row in selected_rows.iterrows():
                                try:
                                    # 从 session_state 找回原始对象 (为了拿 file_obj)
                                    original_item = results[row['Index']]
                                    file_obj = original_item['file_obj']
                                    
                                    # 重置文件指针 (因为可能被读过)
                                    file_obj.seek(0)
                                    
                                    # 上传 PDF 到 Storage
                                    # 文件名加时间戳防止重名
                                    path = f"{int(time.time())}_{row['Index']}_{row['File']}"
                                    backend.supabase.storage.from_("invoices").upload(path, file_obj.read(), {"content-type": "application/pdf"})
                                    
                                    # 获取公开链接
                                    public_url = backend.supabase.storage.from_("invoices").get_public_url(path)
                                    
                                    # 写入 Database (包含新增的 date 和 description)
                                    backend.supabase.table("invoice_archive").insert({
                                        "invoice_no": row['Inv #'], 
                                        "vendor": row['Vendor'], 
                                        "invoice_date": str(row['Date']),  
                                        "description": row['Desc'],        
                                        "amount": row['Inv Amount'],
                                        "file_name": row['File'], 
                                        "file_url": public_url, 
                                        "status": "Verified"
                                    }).execute()
                                except Exception as e:
                                    st.error(f"Error saving {row['File']}: {e}")
                            
                            save_status.success("Saved successfully!")
                        else:
                            st.warning("No invoices selected.")
            else:
                st.info("Please upload invoices in step 1.")

    # --- Tab 2: 档案查看 ---
    with tab_archive:
        st.subheader("🗄️ Invoice Digital Cabinet")
        search = st.text_input("Search Vendor/Invoice #")
        
        try:
            query = backend.supabase.table("invoice_archive").select("*").order("created_at", desc=True)
            if search: 
                query = query.or_(f"vendor.ilike.%{search}%,invoice_no.ilike.%{search}%")
            
            res = query.execute().data
            
            if res:
                st.dataframe(
                    pd.DataFrame(res), 
                    column_config={
                        "file_url": st.column_config.LinkColumn("Link", display_text="Download"),
                        "amount": st.column_config.NumberColumn(format="$%.2f"),
                        "invoice_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD")
                    }, 
                    width="stretch", 
                    hide_index=True
                )
            else: 
                st.info("No archives found.")
        except Exception as e: 
            st.error(f"Error loading archive: {e}")


# --- View 6: Debug Models (Optional) ---
def view_debug_models():
    st.title("🛠️ Google Model Debugger")
    
    if "google" not in st.secrets or "api_key" not in st.secrets["google"]:
        st.error("❌ Google API Key not found in secrets!")
        return

    import google.generativeai as genai
    genai.configure(api_key=st.secrets["google"]["api_key"])
    
    st.write("Checking available models...")
    
    try:
        models = list(genai.list_models())
        chat_models = [m for m in models if 'generateContent' in m.supported_generation_methods]
        
        st.success(f"✅ Found {len(chat_models)} models:")
        
        model_data = []
        for m in chat_models:
            model_data.append({
                "Model Name": m.name,
                "Display Name": m.display_name,
            })
            
        st.dataframe(pd.DataFrame(model_data), use_container_width=True)
        st.info("Copy the 'Model Name' (e.g., models/gemini-1.5-flash) into backend.py")
        
    except Exception as e:
        st.error(f"❌ Connection Failed: {str(e)}")