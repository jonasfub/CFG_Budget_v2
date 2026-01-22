import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai  # <--- 改回使用这个标准库，兼容性最好
import json
import time
import re

# --- A. 数据库连接 ---
@st.cache_resource
def init_connection():
    try:
        if "supabase" in st.secrets:
            return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None
    return None

supabase = init_connection()

# --- B. Google AI 检查 ---
def check_google_key():
    return "google" in st.secrets and "api_key" in st.secrets["google"]

# --- C. 核心数据函数 (保持不变) ---
def get_forest_list():
    if not supabase: return []
    try: return supabase.table("dim_forests").select("*").execute().data
    except: return []

def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    if not supabase: return pd.DataFrame()
    dims = supabase.table(dim_table).select("*").execute().data
    df_dims = pd.DataFrame(dims)
    if df_dims.empty: return pd.DataFrame()
    
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name']

    try:
        res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
        df_facts = pd.DataFrame(res.data)
    except: df_facts = pd.DataFrame()
    
    if df_facts.empty:
        cols_to_keep = ['id', dim_name_col]
        if 'grade_code' in df_dims.columns: cols_to_keep.append('grade_code')
        df_merged = df_dims[cols_to_keep].rename(columns={'id': dim_id_col})
        for c in value_cols: df_merged[c] = 0.0
    else:
        df_merged = pd.merge(df_dims, df_facts, left_on='id', right_on=dim_id_col, how='left')
        for c in value_cols: df_merged[c] = df_merged[c].fillna(0.0)
    
    df_merged = df_merged.loc[:, ~df_merged.columns.duplicated()]
    df_merged = df_merged.reset_index(drop=True)

    if 'market' not in df_merged.columns and 'grade_code' in df_merged.columns:
        df_merged['market'] = df_merged['grade_code'].apply(lambda x: 'Domestic' if 'Domestic' in str(x) else 'Export')
    if 'customer' not in df_merged.columns: df_merged['customer'] = 'FCO' 
    return df_merged

def save_monthly_data(edited_df, table_name, dim_id_col, forest_id, target_date, record_type):
    if not supabase or edited_df.empty: return False
    records = []
    for _, row in edited_df.iterrows():
        rec = { "forest_id": forest_id, dim_id_col: row[dim_id_col], "month": target_date, "record_type": record_type }
        for col in row.index:
            if col in ['vol_tonnes', 'vol_jas', 'price_jas', 'amount', 'quantity', 'unit_rate', 'total_amount']:
                rec[col] = row[col]
        records.append(rec)
    try:
        supabase.table(table_name).upsert(records, on_conflict=f"forest_id,{dim_id_col},month,record_type").execute()
        return True
    except: return False

# --- D. 发票 HTML 生成 ---
def generate_invoice_html(invoice_no, invoice_date, bill_to, month_str, year, items, subtotal, gst_val, total_due):
    rows_html = ""
    for item in items:
        rows_html += f"<tr class='item'><td>{item['desc']}</td><td class='text-right'>${item['amount']:,.2f}</td></tr>"
    return f"""
    <!DOCTYPE html>
    <html><head><style>body {{ font-family: Arial; padding: 20px; }} .invoice-box {{ max-width: 800px; margin: auto; border: 1px solid #eee; padding: 30px; }} table {{ width: 100%; }} .text-right {{ text-align: right; }} .item td {{ border-bottom: 1px solid #eee; }} .total td {{ border-top: 2px solid #eee; font-weight: bold; }}</style></head><body><div class="invoice-box"><table><tr><td><h1>INVOICE</h1></td><td class="text-right">#{invoice_no}<br>{invoice_date}</td></tr><tr><td><strong>FCO Management</strong></td><td class="text-right"><strong>Bill To:</strong><br>{bill_to}</td></tr>{rows_html}<tr class="total"><td></td><td class="text-right">Total: ${total_due:,.2f}</td></tr></table></div></body></html>
    """

# --- E. AI 识别核心逻辑 (稳定兼容版) ---
def real_extract_invoice_data(file_obj):
    try:
        if not check_google_key():
            return {"vendor_detected": "Error", "error_msg": "API Key missing", "amount_detected": 0, "filename": file_obj.name}

        # 1. 配置 (这是最稳健的写法)
        genai.configure(api_key=st.secrets["google"]["api_key"])
        
       # --- 修改开始 ---
        # 尝试使用更具体的模型名称，这通常能解决 404 错误
        # 备选方案: 'gemini-1.5-flash-001' 或 'gemini-1.5-flash-latest'
        try:
            model = genai.GenerativeModel('gemini-1.5-flash-latest') 
        except:
            # 如果 Flash 依然失败，回退到 Pro (成本稍高但兼容性最好)
            model = genai.GenerativeModel('gemini-1.5-flash')
        # --- 修改结束 ---
        
        # 3. 读取文件
        file_obj.seek(0)
        file_bytes = file_obj.read()
        
        # 4. 构建 Prompt
        prompt_text = """
        Analyze this invoice PDF. Extract into JSON:
        1. "vendor_detected": Company name.
        2. "invoice_no": Invoice number.
        3. "date_detected": YYYY-MM-DD.
        4. "amount_detected": Total numeric amount (float).
        
        Important: Return ONLY the JSON object. No markdown.
        """
        
        # 5. 调用生成 (parts 列表写法)
        response = model.generate_content([
            {'mime_type': 'application/pdf', 'data': file_bytes},
            prompt_text
        ])
        
        # 6. 解析
        raw_text = response.text
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        
        if match:
            json_str = match.group(0)
            data = json.loads(json_str)
            data['filename'] = file_obj.name
            # 容错处理
            if "amount_detected" not in data: data["amount_detected"] = 0.0
            if "invoice_no" not in data: data["invoice_no"] = "Unknown"
            if isinstance(data["amount_detected"], str):
                # 尝试把 "$1,234.56" 变成 float
                clean_amt = data["amount_detected"].replace('$','').replace(',','')
                try: data["amount_detected"] = float(clean_amt)
                except: data["amount_detected"] = 0.0
            
            return data
        else:
            return {
                "filename": file_obj.name,
                "vendor_detected": "Error", 
                "error_msg": f"No JSON. Raw: {raw_text[:50]}...",
                "amount_detected": 0.0
            }

    except Exception as e:
        return {
            "filename": file_obj.name,
            "vendor_detected": "Error", 
            "error_msg": str(e),
            "amount_detected": 0.0
        }

# 在 backend.py 添加这个调试函数
def list_available_models():
    genai.configure(api_key=st.secrets["google"]["api_key"])
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name) # 这会在 Streamlit 的后台 Logs 里打印出来的模型列表