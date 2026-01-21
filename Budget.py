def input_page(mode="Budget"):
    st.title(f"📝 {mode} Entry (Monthly)")
    
    forests = get_forest_list()
    if not forests: st.warning("正在加载林地数据..."); return

    # --- 1. 顶部公共筛选器 (Top Bar) ---
    # 这些筛选器对两个 Tab 都生效
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2:
        year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3:
        month_str = st.selectbox("Month", MONTHS, key=f"m_{mode}")

    # 计算目标日期和林地ID
    month_num = MONTH_MAP[month_str]
    target_date = f"{year}-{month_num:02d}-01"
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    st.markdown(f"**Current Editing:** {sel_forest} | {year}-{month_str} ({mode})")
    
    # --- 2. 核心改动：使用 Tabs 替代 Radio ---
    # 这就是你想要的“翻页”效果，而不是点击圆点
    tab_vol, tab_cost = st.tabs(["🌲 Volume & Sales", "💰 Operational Costs"])

    # --- Tab 1: 销量与收入 ---
    with tab_vol:
        st.caption("输入各等级木材的产量和单价")
        value_cols = ['vol_tonnes', 'vol_jas', 'price_jas', 'amount']
        
        df_vol = get_monthly_data(
            "fact_production_volume", "dim_products", 
            "grade_id", "grade_code", 
            fid, target_date, mode, value_cols
        )
        
        col_cfg_vol = {
            "grade_id": None,
            "grade_code": st.column_config.TextColumn("Grade", disabled=True, width="medium"),
            "vol_tonnes": st.column_config.NumberColumn("Vol (T)", format="%.1f"),
            "vol_jas": st.column_config.NumberColumn("Vol (JAS)", format="%.1f"),
            "price_jas": st.column_config.NumberColumn("Price ($/JAS)", format="$%.0f"),
            "amount": st.column_config.NumberColumn("Total ($)", format="$%.0f"),
        }
        
        edited_vol = st.data_editor(
            df_vol, 
            key=f"editor_vol_{mode}_{target_date}", 
            column_config=col_cfg_vol, 
            use_container_width=True, 
            height=500, # 表格高度
            hide_index=True
        )
        
        if st.button(f"💾 Save Volume ({month_str})", type="primary"):
            if save_monthly_data(edited_vol, "fact_production_volume", "grade_id", fid, target_date, mode):
                st.success(f"✅ Saved Volume data for {month_str}!")

    # --- Tab 2: 运营成本 ---
    with tab_cost:
        st.caption("输入各项运营活动成本")
        value_cols_cost = ['quantity', 'unit_rate', 'total_amount']
        
        df_cost = get_monthly_data(
            "fact_operational_costs", "dim_cost_activities", 
            "activity_id", "activity_name", 
            fid, target_date, mode, value_cols_cost
        )
        
        col_cfg_cost = {
            "activity_id": None,
            "activity_name": st.column_config.TextColumn("Activity", disabled=True, width="large"),
            "quantity": st.column_config.NumberColumn("Qty/Vol", format="%.1f"),
            "unit_rate": st.column_config.NumberColumn("Rate", format="$%.2f"),
            "total_amount": st.column_config.NumberColumn("Total ($)", format="$%.0f")
        }
        
        edited_cost = st.data_editor(
            df_cost, 
            key=f"editor_cost_{mode}_{target_date}",
            column_config=col_cfg_cost, 
            use_container_width=True, 
            height=500,
            hide_index=True
        )
        
        if st.button(f"💾 Save Costs ({month_str})", type="primary"):
            if save_monthly_data(edited_cost, "fact_operational_costs", "activity_id", fid, target_date, mode):
                st.success(f"✅ Saved Costs data for {month_str}!")