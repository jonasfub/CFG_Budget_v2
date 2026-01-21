import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import time

# --- 1. 系统初始化 ---
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="expanded")

# 样式优化
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #0068C9; }
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    /* 隐藏部分不需要的索引列 */
    thead tr th:first-child {display:none}
    tbody th {display:none}
</style>
""", unsafe_allow_html=True)

# 基础常量
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# 连接 Supabase
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"⚠️ 连接失败: {e}")
        return None

supabase = init_connection()

# --- 2. 核心引擎：单月数据读写 (Monthly Logic) ---

def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    """
    拉取指定月份的数据。如果该月没数据，自动创建一个包含所有 Grade/Activity 的空模板。
    """
    if not supabase: return pd.DataFrame()

    # 1. 拉取所有维度 (Grade 或 Activity) 作为骨架
    dims = supabase.table(dim_table).select("*").execute().data
    df_dims = pd.DataFrame(dims)
    
    # 兼容处理: 有些表叫 grade_code, 有些叫 activity_name
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name']
    
    # 2. 拉取该月已保存的实际数据
    response = supabase.table(table_name).select("*")\
        .eq("forest_id", forest_id)\
        .eq("record_type", record_type)\
        .eq("month", target_date)\
        .execute()
    
    df_facts = pd.DataFrame(response.data)
    
    # 3. 合并 (Left Join): 保证即使没数据的 Grade 也会显示出来让用户填
    if df_facts.empty:
        # 如果完全没数据，直接用维度表造一个空表
        df_merged = df_dims[[ 'id', dim_name_col ]].rename(columns={'id': dim_id_col})
        for col in value_cols:
            df_merged[col] = 0.0
    else:
        # 合并维度信息
        df_merged = pd.merge(
            df_dims[['id', dim_name_col]], 
            df_facts, 
            left_on='id', 
            right_on=dim_id_col, 
            how='left'
        )
        # 填充空值为0
        for col in value_cols:
            df_merged[col] = df_merged[col].fillna(0.0)
            
    # 只保留需要的列
    final_cols = [dim_id_col, dim_name_col] + value_cols
    return df_merged[final_cols]

def save_monthly_data(edited_df, table_name, dim_id_col, forest_id, target_date, record_type):
    """
    保存单月数据到 Supabase
    """
    if not supabase or edited_df.empty: return

    records = []
    # 遍历每一行数据
    for _, row in edited_df.iterrows():
        # 过滤掉全0行 (可选: 如果你希望清理数据库垃圾数据)
        # 这里我们保留全0行以便覆盖更新
        
        record = {
            "forest_id": forest_id,
            dim_id_col: row[dim_id_col],
            "month": target_date,
            "record_type": record_type
        }
        
        # 动态添加所有数值列
        for col in row.index:
            if col not in [dim_id_col, 'dim_name', 'grade_code', 'activity_name']:
                record[col] = row[col]
        
        records.append(record)
    
    # 执行 Upsert (依靠数据库的 Unique 约束来更新或插入)
    # 约束条件: forest_id + dim_id + month + type 必须唯一
    try:
        constraint = f"forest_id,{dim_id_col},month,record_type"
        supabase.table(table_name).upsert(records, on_conflict=constraint).execute()
        return True
    except Exception as e:
        st.error(f"保存失败: {e}")
        return False

# --- 3. 页面逻辑 ---

def get_forest_list():
    if not supabase: return []
    res = supabase.table("dim_forests").select("*").execute()
    return res.data

def main_dashboard():
    st.title("📊 FCO Executive Dashboard")
    
    forests = get_forest_list()
    if not forests: st.warning("请检查数据库连接"); return
    
    # 筛选
    col_f, col_y = st.columns([2, 1])
    with col_f:
        sel_forest = st.selectbox("选择林地", ["ALL"] + [f['name'] for f in forests])
    with col_y:
        sel_year = st.selectbox("年份", [2025, 2026])
        
    # 获取数据 (聚合)
    # 为了演示性能，这里拉取全年数据后在 Pandas 聚合
    query_vol = supabase.table("fact_production_volume").select("*").eq("record_type", "Actual")
    query_cost = supabase.table("fact_operational_costs").select("*").eq("record_type", "Actual")
    
    if sel_forest != "ALL":
        fid = next(f['id'] for f in forests if f['name'] == sel_forest)
        query_vol = query_vol.eq("forest_id", fid)
        query_cost = query_cost.eq("forest_id", fid)
        
    # 增加年份筛选 (简单字符串匹配)
    df_vol = pd.DataFrame(query_vol.execute().data)
    df_cost = pd.DataFrame(query_cost.execute().data)
    
    if not df_vol.empty: 
        df_vol['month'] = pd.to_datetime(df_vol['month'])
        df_vol = df_vol[df_vol['month'].dt.year == sel_year]
        
    if not df_cost.empty:
        df_cost['month'] = pd.to_datetime(df_cost['month'])
        df_cost = df_cost[df_cost['month'].dt.year == sel_year]

    # KPI 计算
    rev = df_vol['amount'].sum() if not df_vol.empty else 0
    cost = df_cost['total_amount'].sum() if not df_cost.empty else 0
    margin = rev - cost
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Revenue (YTD)", f"${rev:,.0f}")
    k2.metric("Costs (YTD)", f"${cost:,.0f}")
    k3.metric("Margin", f"${margin:,.0f}", delta=f"{(margin/rev*100) if rev else 0:.1f}%")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Monthly P&L")
        if not df_vol.empty or not df_cost.empty:
            v_m = df_vol.groupby('month')['amount'].sum().reset_index() if not df_vol.empty else pd.DataFrame()
            c_m = df_cost.groupby('month')['total_amount'].sum().reset_index() if not df_cost.empty else pd.DataFrame()
            
            if not v_m.empty and not c_m.empty:
                merged = pd.merge(v_m, c_m, on='month', how='outer').fillna(0)
            elif not v_m.empty:
                merged = v_m.assign(total_amount=0)
            else:
                merged = c_m.assign(amount=0)
                
            if not merged.empty:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=merged['month'], y=merged.get('amount',0), name='Revenue', marker_color='#2ca02c'))
                fig.add_trace(go.Bar(x=merged['month'], y=merged.get('total_amount',0), name='Costs', marker_color='#d62728'))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("暂无数据")
    
    with c2:
        st.subheader("Cost Breakdown")
        if not df_cost.empty:
            acts = pd.DataFrame(supabase.table("dim_cost_activities").select("*").execute().data)
            if not acts.empty:
                cost_merged = pd.merge(df_cost, acts, left_on='activity_id', right_on='id', how='left')
                pie_df = cost_merged.groupby('category')['total_amount'].sum().reset_index()
                fig2 = px.pie(pie_df, values='total_amount', names='category', hole=0.4)
                st.plotly_chart(fig2, use_container_width=True)


def input_page(mode="Budget"):
    st.title(f"📝 {mode} Entry (Monthly)")
    
    forests = get_forest_list()
    if not forests: st.warning("正在加载林地数据..."); return

    # --- 顶部筛选器 (Top Bar) ---
    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
    with c1:
        sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key=f"f_{mode}")
    with c2:
        year = st.selectbox("Year", [2025, 2026], key=f"y_{mode}")
    with c3:
        month_str = st.selectbox("Month", MONTHS, key=f"m_{mode}") # 这里就是你要的“按月建立Page”
    with c4:
        # 输入类型切换
        input_type = st.radio("Type", ["Volume & Sales", "Operational Costs"], horizontal=True, key=f"t_{mode}")

    # 计算目标日期
    month_num = MONTH_MAP[month_str]
    target_date = f"{year}-{month_num:02d}-01"
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)

    st.markdown(f"**Current Editing:** {sel_forest} | {year}-{month_str} ({mode})")
    st.divider()

    # --- 核心数据编辑器 ---
    
    if input_type == "Volume & Sales":
        # 1. Volume 录入界面
        value_cols = ['vol_tonnes', 'vol_jas', 'price_jas', 'amount']
        
        df = get_monthly_data(
            "fact_production_volume", "dim_products", 
            "grade_id", "grade_code", 
            fid, target_date, mode, value_cols
        )
        
        # 配置列显示 (隐藏ID，锁定Grade名)
        col_cfg = {
            "grade_id": None,
            "grade_code": st.column_config.TextColumn("Grade", disabled=True, width="medium"),
            "vol_tonnes": st.column_config.NumberColumn("Vol (T)", format="%.1f"),
            "vol_jas": st.column_config.NumberColumn("Vol (JAS)", format="%.1f"),
            "price_jas": st.column_config.NumberColumn("Price ($/JAS)", format="$%.0f"),
            "amount": st.column_config.NumberColumn("Total ($)", format="$%.0f"),
        }
        
        edited_df = st.data_editor(
            df, 
            key=f"editor_vol_{mode}_{target_date}", # Key 包含日期，确保切换月份时表格刷新
            column_config=col_cfg, 
            use_container_width=True, 
            height=600,
            hide_index=True
        )
        
        if st.button(f"💾 Save Volume ({month_str})"):
            if save_monthly_data(edited_df, "fact_production_volume", "grade_id", fid, target_date, mode):
                st.success(f"✅ Saved {month_str} Volume data!")

    else:
        # 2. Costs 录入界面
        value_cols = ['quantity', 'unit_rate', 'total_amount']
        
        df = get_monthly_data(
            "fact_operational_costs", "dim_cost_activities", 
            "activity_id", "activity_name", 
            fid, target_date, mode, value_cols
        )
        
        col_cfg = {
            "activity_id": None,
            "activity_name": st.column_config.TextColumn("Activity", disabled=True, width="large"),
            "quantity": st.column_config.NumberColumn("Qty/Vol", format="%.1f"),
            "unit_rate": st.column_config.NumberColumn("Rate", format="$%.2f"),
            "total_amount": st.column_config.NumberColumn("Total ($)", format="$%.0f")
        }
        
        edited_df = st.data_editor(
            df, 
            key=f"editor_cost_{mode}_{target_date}",
            column_config=col_cfg, 
            use_container_width=True, 
            height=600,
            hide_index=True
        )
        
        if st.button(f"💾 Save Costs ({month_str})"):
            if save_monthly_data(edited_df, "fact_operational_costs", "activity_id", fid, target_date, mode):
                st.success(f"✅ Saved {month_str} Costs data!")

# --- 4. 导航 ---
st.sidebar.title("FCO ERP")
nav = st.sidebar.radio("Go to", ["Dashboard", "Budget Input", "Actual Input"])

if nav == "Dashboard": main_dashboard()
elif nav == "Budget Input": input_page("Budget")
elif nav == "Actual Input": input_page("Actual")