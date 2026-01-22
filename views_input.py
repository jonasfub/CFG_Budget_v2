import streamlit as st
import pandas as pd
from datetime import date
import backend 

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# --- Helper: 模拟获取 Compartments (建议在 backend 中真正实现) ---
def get_compartment_options(forest_id):
    # 实际项目中应从 backend.supabase.table("dim_compartments").select("code").eq("forest_id", fid)... 获取
    # 这里基于 Invoice 16027 硬编码示例
    return ["60810", "60812", "60814", "General"]

# --- 1. Log Sales (Updated based on Invoice 16027) ---
def view_log_sales():
    st.title("🚛 Log Sales Data (Transaction Level)")
    st.caption("对应发票 Production Summary 部分，支持负数冲销与自营/代售区分")
    
    forests = backend.get_forest_list()
    if not forests: return
    
    c1, c2 = st.columns([1, 2])
    with c1: 
        sel_forest = st.selectbox("Forest", [f['name'] for f in forests])
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    # 获取基础配置数据
    products = backend.supabase.table("dim_products").select("*").execute().data
    product_codes = [p['grade_code'] for p in products] if products else []
    compartment_opts = get_compartment_options(fid) # [新增] 地块选项
    
    # 获取现有数据
    res = backend.supabase.table("actual_sales_transactions").select("*").eq("forest_id", fid).order("date", desc=True).limit(50).execute()
    df = pd.DataFrame(res.data)
    
    # 初始化空行 (如果没数据)
    if df.empty: 
        df = pd.DataFrame([{
            "date": date.today(), 
            "ticket_number": "", 
            "compartment": compartment_opts[0], # [新增]
            "customer": "C001", 
            "market": "Export",
            "sale_type": "Purchase (Inv)", # [新增] 默认 F360 代售/收购
            "grade_code": "A", 
            "net_tonnes": 0.0, 
            "jas": 0.0, 
            "price": 0.0, 
            "levy_deduction": 0.0, # [新增] 扣费
            "total_value": 0.0
        }])
    else:
        # 确保新字段存在 (防止旧数据报错)
        if 'compartment' not in df.columns: df['compartment'] = compartment_opts[0]
        if 'sale_type' not in df.columns: df['sale_type'] = "Purchase (Inv)"
        if 'levy_deduction' not in df.columns: df['levy_deduction'] = 0.0

    # 动态计算 Conversion Factor (仅展示用)
    df['conversion_factor'] = df.apply(lambda x: x['jas']/x['net_tonnes'] if x['net_tonnes']!=0 else 0, axis=1)

    col_cfg = {
        "id": None, "forest_id": None, "grade_id": None, "created_at": None,
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "ticket_number": st.column_config.TextColumn("Ticket #"),
        "compartment": st.column_config.SelectboxColumn("Block/Cpt", options=compartment_opts, required=True), # [新增]
        "customer": st.column_config.TextColumn("Customer", default="FCO"),
        "market": st.column_config.SelectboxColumn("Market", options=["Export", "Domestic"], default="Export"),
        "sale_type": st.column_config.SelectboxColumn(
            "Sale Type", 
            options=["Purchase (Inv)", "Direct (Non-Inv)", "Adjustment"],
            help="Purchase: F360买断/代售(有金额); Direct: CFGC直销($0); Adjustment: 冲销"
        ), # [新增] 关键逻辑字段
        "grade_code": st.column_config.SelectboxColumn("Grade", options=product_codes, required=True),
        "net_tonnes": st.column_config.NumberColumn("Tonnes", format="%.2f"), # 允许负数
        "jas": st.column_config.NumberColumn("JAS", format="%.2f"),
        "conversion_factor": st.column_config.NumberColumn("Conv.", format="%.3f", disabled=True),
        "price": st.column_config.NumberColumn("Price", format="$%.2f"),
        "levy_deduction": st.column_config.NumberColumn("Levies", format="$%.2f", help="Credit Insurance / Comm. Levy"), # [新增]
        "total_value": st.column_config.NumberColumn("Net Total ($)", format="$%.2f"),
    }
    
    edited = st.data_editor(df, key="log_sales", num_rows="dynamic", width="stretch", column_config=col_cfg)
    
    if st.button("💾 Save Transactions"):
        recs = []
        for _, row in edited.iterrows():
            gid = next((p['id'] for p in products if p['grade_code'] == row.get('grade_code')), None)
            
            # 自动计算 Total Value (如果用户没填)
            # 逻辑：(Tonnes * Price) - Levy
            calc_total = row.get('total_value')
            if calc_total == 0 and row.get('price', 0) != 0:
                calc_total = (row.get('net_tonnes', 0) * row.get('price', 0)) - row.get('levy_deduction', 0)

            recs.append({
                "forest_id": fid, 
                "date": str(row['date']), 
                "ticket_number": row.get('ticket_number'),
                "compartment": row.get('compartment'), # 需确保 DB 有此列
                "sale_type": row.get('sale_type'),     # 需确保 DB 有此列
                "grade_id": gid, 
                "customer": row.get('customer'), 
                "market": row.get('market'),
                "net_tonnes": row.get('net_tonnes'), 
                "jas": row.get('jas'), 
                "price": row.get('price'), 
                "levy_deduction": row.get('levy_deduction', 0), # 需确保 DB 有此列
                "total_value": calc_total
            })
        try:
            # 注意: 请确保 Supabase 表 'actual_sales_transactions' 已经添加了 compartment, sale_type, levy_deduction 字段
            backend.supabase.table("actual_sales_transactions").upsert(recs).execute()
            st.success("Transactions Saved! (Total calculated automatically where 0)")
        except Exception as e: st.error(f"Error: {e} (Check if DB columns exist!)")


# --- 2. Monthly Input (Updated with Budget Pre-fill Logic) ---
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
        tabs = ["📋 Sales Forecast", "🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    else:
        # Actual 模式不需要 Sales Forecast (因为用 Log Sales Transaction 替代了)
        tabs = ["🚛 Log Transport & Volume", "💰 Operational & Harvesting"]
    
    current_tabs = st.tabs(tabs)

    for i, tab_name in enumerate(tabs):
        with current_tabs[i]:
            
            # --- Tab A: Sales Forecast (Budget Only) ---
            if tab_name == "📋 Sales Forecast":
                df = backend.get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                
                # ... (保持原有 Budget 逻辑不变，省略以节省空间) ...
                edited_detail = st.data_editor(df, key=f"d_{mode}", hide_index=True, width="stretch")
                if st.button("Save Forecast", key=f"b_detail_{mode}"):
                    backend.save_monthly_data(edited_detail, "fact_production_volume", "grade_id", fid, target_date, mode)

            # --- Tab B: Transport & Volume ---
            elif tab_name == "🚛 Log Transport & Volume":
                 df = backend.get_monthly_data("fact_production_volume", "dim_products", "grade_id", "grade_code", fid, target_date, mode, ['vol_tonnes', 'vol_jas', 'price_jas', 'amount'])
                 
                 cfg = {"grade_id": None, "grade_code": st.column_config.TextColumn("Grade", disabled=True)}
                 edited = st.data_editor(df, key=f"v_{mode}_{target_date}", hide_index=True, width="stretch", column_config=cfg)
                 
                 if st.button("Save Volume", key=f"b1_{mode}"):
                     if backend.save_monthly_data(edited, "fact_production_volume", "grade_id", fid, target_date, mode): st.success("Saved!")

            # --- Tab C: Operational Costs (CORE UPDATE) ---
            elif tab_name == "💰 Operational & Harvesting":
                 
                 # 1. 获取当前数据
                 df = backend.get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, mode, ['quantity', 'unit_rate', 'total_amount'])
                 
                 # 2. [关键逻辑] Actual 模式下的 Budget 预填
                 if mode == "Actual":
                     # 检查是否为空数据 (假设 total_amount sum 为 0 即未录入)
                     if df['total_amount'].sum() == 0:
                         st.info("💡 智能提示：已自动加载本月【预算单价】。请填入实际数量，系统将自动计算总额。")
                         
                         # 拉取 Budget 数据
                         df_budget = backend.get_monthly_data("fact_operational_costs", "dim_cost_activities", "activity_id", "activity_name", fid, target_date, "Budget", ['unit_rate', 'total_amount'])
                         
                         if not df_budget.empty:
    # 1. 修改 set_index 的列名为 'activity_id'
    bud_rate_map = df_budget.set_index('activity_id')['unit_rate'].to_dict()
    
    # 应用逻辑
    for idx, row in df.iterrows():
        act_name = str(row['activity_name']).lower()
        is_lump_sum = any(x in act_name for x in ['road', 'construct', 'mainten', 'fee', 'lump', 'fixed', 'general'])
        
        # 2. 修改获取映射的键值为 row['activity_id']
        bud_rate = bud_rate_map.get(row['activity_id'], 0.0)
        
        if is_lump_sum:
            df.at[idx, 'unit_rate'] = 0.0
            df.at[idx, 'quantity'] = 1.0 
        else:
            if bud_rate > 0:
                df.at[idx, 'unit_rate'] = bud_rate
                                 
                                 if is_lump_sum:
                                     # 一次性项目：单价置0，总额留空让用户填，数量设为1作为标记
                                     df.at[idx, 'unit_rate'] = 0.0
                                     df.at[idx, 'quantity'] = 1.0 
                                 else:
                                     # 常规项目 (Logging/Cartage)：预填预算单价
                                     if bud_rate > 0:
                                         df.at[idx, 'unit_rate'] = bud_rate
                                         # Quantity 留 0 等待输入

                 # 3. 列配置 (根据发票优化)
                 cfg = {
                     "activity_id": None, 
                     "activity_name": st.column_config.TextColumn("Activity", disabled=True),
                     # Quantity: 对于 Logging 是 Tonnes, 对于 Road 是 1.0 (Items)
                     "quantity": st.column_config.NumberColumn("Actual Qty", help="Logging/Cartage填吨数; 工程类填1.0"),
                     # Unit Rate: 默认显示预算单价
                     "unit_rate": st.column_config.NumberColumn("Unit Rate ($)", format="$%.2f", help="默认来自预算，可手动修正"),
                     # Total: 最终发票金额
                     "total_amount": st.column_config.NumberColumn("Total Cost ($)", format="$%.2f", required=True)
                 }
                 
                 edited = st.data_editor(df, key=f"c_{mode}_{target_date}", hide_index=True, width="stretch", column_config=cfg)
                 
                 # 4. 保存 & 自动计算补全
                 if st.button("Save Costs", key=f"b2_{mode}"):
                     # 自动计算逻辑：如果用户只填了 Qty 和 Rate，没算 Total，帮他算
                     for i, row in edited.iterrows():
                         current_total = row['total_amount']
                         qty = row['quantity']
                         rate = row['unit_rate']
                         
                         # 只有当 Total 为 0 且有单价和数量时才自动计算 (避免覆盖用户手动输入的一次性总额)
                         if current_total == 0 and qty > 0 and rate > 0:
                             edited.at[i, 'total_amount'] = qty * rate
                             
                     if backend.save_monthly_data(edited, "fact_operational_costs", "activity_id", fid, target_date, mode): 
                         st.success("Costs Saved! (Totals auto-calculated based on Rates)")
                         time.sleep(1)
                         st.rerun()