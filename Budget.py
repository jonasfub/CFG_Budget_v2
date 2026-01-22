import streamlit as st
# --- 导入你新拆分的 3 个文件 ---
import views_dashboard
import views_input
import views_bot

# 1. 页面配置
st.set_page_config(page_title="FCO Cloud ERP", layout="wide", initial_sidebar_state="expanded")

# 2. 全局样式
st.markdown("""
<style>
    .big-font { font-size:20px !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #0068C9; }
    .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    thead tr th:first-child {display:none}
    tbody th {display:none}
</style>
""", unsafe_allow_html=True)

# 3. 侧边栏导航
st.sidebar.title("🌲 FCO Cloud ERP")

# 4. 定义页面映射 (指向新文件里的函数)
pages = {
    "Dashboard": views_dashboard.view_dashboard,
    "1. Log Sales Data": views_input.view_log_sales,
    "2. Budget Planning": lambda: views_input.view_monthly_input("Budget"),
    "3. Actuals Entry": lambda: views_input.view_monthly_input("Actual"),
    "4. Analysis & Invoice": views_dashboard.view_analysis_invoice,
    "5. 3rd Party Invoice Check": views_bot.view_invoice_bot,
    "6. 🛠️ DEBUG MODELS": views_bot.view_debug_models
}

# 5. 渲染导航栏
selection = st.sidebar.radio("Navigate", list(pages.keys()))

# 6. 执行选中的页面
pages[selection]()