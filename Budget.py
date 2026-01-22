import streamlit as st
import views  # <--- 这行代码会去读取 views.py 文件

# 1. 页面配置 (必须是第一个 Streamlit 命令)
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

# 定义页面映射 (左边是菜单名，右边是 views.py 里的函数)
pages = {
    "Dashboard": views.view_dashboard,
    "1. Log Sales Data": views.view_log_sales,
    "2. Budget Planning": lambda: views.view_monthly_input("Budget"),
    "3. Actuals Entry": lambda: views.view_monthly_input("Actual"),
    "4. Analysis & Invoice": views.view_analysis_invoice,
    "5. 3rd Party Invoice Check": views.view_invoice_bot
}

# 4. 渲染导航栏
selection = st.sidebar.radio("Navigate", list(pages.keys()))

# 5. 执行选中的页面
pages[selection]()