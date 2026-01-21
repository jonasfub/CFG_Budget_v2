import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import time

# --- 1. 系统初始化 ---
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="collapsed")

# 漂亮的 CSS 样式
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #0068C9; }
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# 连接 Supabase
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        st.error("⚠️ 未配置 Secrets! 请在 .streamlit/secrets.toml 中配置 Supabase URL 和 Key。")
        return None

supabase = init_connection()

# --- 2. 核心引擎：Excel <-> Database 转换器 ---

def get_data_as_excel_view(table_name, dim_table, dim_col, dim_id_col, forest_id, year, record_type, value_cols):
    """
    通用函数：将数据库的长表转换为 Excel 宽表
    """
    if not supabase: return pd.DataFrame()

    # A. 拉取现有数据
    response = supabase.table(table_name).select(
        f"*, {dim_table}({dim_col})"
    ).eq("forest_id", forest_id).eq("record_type", record_type).execute()
    
    df = pd.DataFrame(response.data)
    
    # B. 如果没数据，初始化空模板
    if df.empty:
        # 拉取所有维度 (Grade 或 Activity)
        dims = supabase.table(dim_table).select("*").execute().data
        init_rows = []
        for d in dims:
            init_rows.append({dim_id_col: d['id'], "dim_name": d.get(dim_col) or d.get('activity_name')})
        df_pivot = pd.DataFrame(init_rows)
        # 补全月份列
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        for m in months:
            for v_col in value_cols:
                df_pivot[f"{m}_{v_col}"] = 0.0
        return df_pivot

    # C. 数据存在，进行 Pivot (透视)
    df['month'] = pd.to_datetime(df['month'])
    df = df[df['month'].dt.year == year]
    
    # 获取维度名称
    df['dim_name'] = df[dim_table].apply(lambda x: x.get(dim_col) or x.get('activity_name') if x else "Unknown")
    df['month_str'] = df['month'].dt.strftime('%b') # Jan, Feb
    
    # 透视
    pivot = df.pivot_table(
        index=[dim_id_col, 'dim_name'],
        columns='month_str',
        values=value_cols,
        aggfunc='sum'
    ).fillna(0)
    
    # 展平列名 (MultiIndex -> Jan_vol...)
    pivot.columns = [f"{col[1]}_{col[0]}" for col in pivot.columns]
    pivot = pivot.reset_index()
    
    # D. 重新排序列 (Jan 必须在 Feb 前面)
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    final_cols = [dim_id_col, 'dim_name']
    for m in months:
        for v in value_cols:
            c_name = f"{m}_{v}"
            if c_name in pivot.columns:
                final_cols.append(c_name)
            else:
                pivot[c_name] = 0.0 # 补全缺失月份
                final_cols.append(c_name)
                
    return pivot[final_cols]

def save_excel_view_to_db(edited_df, table_name, dim_id_col, forest_id, year, record_type):
    """
    通用函数：将 Excel 宽表保存回数据库
    """
    if not supabase or edited_df.empty: return

    # 1. Melt (逆透视)
    # 找出所有月份数据列
    val_vars = [c for c in edited_df.columns if "_" in c and c not in [dim_id_col, 'dim_name']]
    melted = edited_df.melt(
        id_vars=[dim_id_col], 
        value_vars=val_vars,
        var_name='month_metric', 
        value_name='val'
    )
    
    # 2. 解析 (Jan_vol -> Month=1, Col=vol)
    melted[['month_str', 'metric']] = melted['month_metric'].str.split('_', n=1, expand=True)
    
    # 3. 再透视回长表的一行 (Row = ID + Month)
    long_df = melted.pivot_table(
        index=[dim_id_col, 'month_str'],
        columns='metric',
        values='val'
    ).reset_index()
    
    # 4. 构造 Upsert 数据
    month_map = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                 'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
    
    records = []
    for _, row in long_df.iterrows():
        m_num = month_map.get(row['month_str'])
        if not m_num: continue
        
        # 检查是否全为0 (如果是全0数据，为了节省空间可以不存，或者存0覆盖旧数据)
        # 这里选择存入，以支持“清零”操作
        
        record = {
            "forest_id": forest_id,
            dim_id_col: row[dim_id_col],
            "month": f"{year}-{m_num:02d}-01",
            "record_type": record_type
        }
        # 动态添加所有指标列
        for col in long_df.columns:
            if col not in [dim_id_col, 'month_str']:
                record[col] = row[col]
        
        records.append(record)
        
    # 5. 执行 Upsert
    # 这里的 on_conflict 必须对应 SQL 里设置的 unique 约束
    constraint = f"forest_id,{dim_id_col},month,record_type"
    response = supabase.table(table_name).upsert(records, on_conflict=constraint).execute()
    return response

# --- 3. 页面逻辑 ---

def get_forest_list():
    if not supabase: return []
    res = supabase.table("dim_forests").select("*").execute()
    return res.data

def main_dashboard():
    st.title("📊 FCO Executive Dashboard")
    
    forests = get_forest_list()
    if not forests: st.warning("数据库为空"); return
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        sel_forest_name = st.selectbox("选择林地 (Forest)", ["ALL"] + [f['name'] for f in forests])
    
    # 获取 P&L 数据
    query_vol = supabase.table("fact_production_volume").select("*").eq("record_type", "Actual")
    query_cost = supabase.table("fact_operational_costs").select("*").eq("record_type", "Actual")
    
    if sel_forest_name != "ALL":
        fid = next(f['id'] for f in forests if f['name'] == sel_forest_name)
        query_vol = query_vol.eq("forest_id", fid)
        query_cost = query_cost.eq("forest_id", fid)
        
    df_vol = pd.DataFrame(query_vol.execute().data)
    df_cost = pd.DataFrame(query_cost.execute().data)
    
    # 计算 KPI
    rev = df_vol['amount'].sum() if not df_vol.empty else 0
    cost = df_cost['total_amount'].sum() if not df_cost.empty else 0
    vol = df_vol['vol_tonnes'].sum() if not df_vol.empty else 0
    profit = rev - cost
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("总产量 (Tonnes)", f"{vol:,.0f} T")
    k2.metric("总收入 (Revenue)", f"${rev:,.0f}")
    k3.metric("总成本 (Costs)", f"${cost:,.0f}")
    k4.metric("净利润 (Net)", f"${profit:,.0f}", delta=f"{(profit/rev*100) if rev else 0:.1f}%")
    
    st.divider()
    
    # 绘制 P&L 图表
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Monthly P&L")
        if not df_vol.empty or not df_cost.empty:
            # 简单聚合
            if not df_vol.empty:
                v_month = df_vol.groupby('month')['amount'].sum().reset_index()
            else:
                v_month = pd.DataFrame(columns=['month', 'amount'])
                
            if not df_cost.empty:
                c_month = df_cost.groupby('month')['total_amount'].sum().reset_index()
            else:
                c_month = pd.DataFrame(columns=['month', 'total_amount'])
            
            merged = pd.merge(v_month, c_month, on='month', how='outer').fillna(0)
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=merged['month'], y=merged['amount'], name='Revenue', marker_color='#2E86C1'))
            fig.add_trace(go.Bar(x=merged['month'], y=merged['total_amount'], name='Costs', marker_color='#E74C3C'))
            st.plotly_chart(fig, use_container_width=True)
            
    with c2:
        st.subheader("Cost Structure")
        if not df_cost.empty:
            # 需关联 Activity Name 才能看懂
            acts = pd.DataFrame(supabase.table("dim_cost_activities").select("*").execute().data)
            cost_detail = pd.merge(df_cost, acts, left_on='activity_id', right_on='id')
            pie_df = cost_detail.groupby('category')['total_amount'].sum().reset_index()
            fig2 = px.pie(pie_df, values='total_amount', names='category', hole=0.4)
            st.plotly_chart(fig2, use_container_width=True)

def input_page(mode="Budget"):
    st.title(f"📝 {mode} Data Entry")
    
    # 1. 筛选器
    forests = get_forest_list()
    c1, c2, c3 = st.columns(3)
    with c1:
        sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2:
        year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3:
        input_type = st.radio("Input Type", ["Volume & Revenue", "Operational Costs"], horizontal=True, key=f"t_{mode}")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    
    # 2. 核心逻辑：加载 Excel 视图
    if input_type == "Volume & Revenue":
        # 配置 Volume 表的列
        value_cols = ['vol_tonnes', 'vol_jas', 'price_jas', 'amount']
        
        df_view = get_data_as_excel_view(
            table_name="fact_production_volume",
            dim_table="dim_products",
            dim_col="grade_code",
            dim_id_col="grade_id",
            forest_id=fid, year=year, record_type=mode, value_cols=value_cols
        )
        
        st.info("💡 提示: 直接修改下方表格，点击 Save 保存。列名格式: Jan_vol_tonnes 表示 1月产量(吨)")
        
        # 配置列格式 (让它好看点)
        col_cfg = {"dim_name": st.column_config.TextColumn("Grade", disabled=True, width="small")}
        for col in df_view.columns:
            if "price" in col or "amount" in col:
                col_cfg[col] = st.column_config.NumberColumn(col, format="$%.0f")
            elif "vol" in col:
                col_cfg[col] = st.column_config.NumberColumn(col, format="%.1f")
        
        # 渲染编辑器
        edited = st.data_editor(df_view, height=600, use_container_width=True, column_config=col_cfg, num_rows="fixed")
        
        if st.button(f"💾 Save {mode} Volume"):
            with st.spinner("Saving to Cloud..."):
                save_excel_view_to_db(edited, "fact_production_volume", "grade_id", fid, year, mode)
            st.success("✅ Saved!")

    else:
        # 配置 Costs 表的列
        value_cols = ['quantity', 'unit_rate', 'total_amount']
        
        df_view = get_data_as_excel_view(
            table_name="fact_operational_costs",
            dim_table="dim_cost_activities",
            dim_col="activity_name",
            dim_id_col="activity_id",
            forest_id=fid, year=year, record_type=mode, value_cols=value_cols
        )
        
        st.info(f"💡 提示: 输入 {mode} 成本数据。Category 和 Op Code 已自动关联。")
        
        col_cfg = {"dim_name": st.column_config.TextColumn("Activity", disabled=True, width="medium")}
        for col in df_view.columns:
            if "amount" in col:
                col_cfg[col] = st.column_config.NumberColumn(col, format="$%.0f")
        
        edited = st.data_editor(df_view, height=600, use_container_width=True, column_config=col_cfg, num_rows="fixed")
        
        if st.button(f"💾 Save {mode} Costs"):
            with st.spinner("Saving to Cloud..."):
                save_excel_view_to_db(edited, "fact_operational_costs", "activity_id", fid, year, mode)
            st.success("✅ Saved!")

# --- 4. 导航 ---
st.sidebar.title("FCO ERP")
nav = st.sidebar.radio("Go to", ["Dashboard", "Budget Input", "Actual Input"])

if nav == "Dashboard": main_dashboard()
elif nav == "Budget Input": input_page("Budget")
elif nav == "Actual Input": input_page("Actual")