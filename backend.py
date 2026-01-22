import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import time

# --- A. 数据库连接 ---
@st.cache_resource
def init_connection():
    try:
        if "supabase" in st.secrets:
            return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except:
        return None
    return None

supabase = init_connection()

# --- B. Google AI 配置 ---
def init_gemini():
    try:
        if "google" in st.secrets:
            genai.configure(api_key=st.secrets["google"]["api_key"])
            return True
    except:
        return False
    return False

# --- C. 核心数据函数 ---
def get_forest_list():
    if not supabase: return []
    try:
        return supabase.table("dim_forests").select("*").execute().data
    except: return []

def get_monthly_data(table_name, dim_table, dim_id_col, dim_name_col, forest_id, target_date, record_type, value_cols):
    if not supabase: return pd.DataFrame()
    
    # 1. 维度
    dims = supabase.table(dim_table).select("*").execute().data
    df_dims = pd.DataFrame(dims)
    if df_dims.empty: return pd.DataFrame()
    
    if dim_name_col not in df_dims.columns and 'activity_name' in df_dims.columns:
        df_dims[dim_name_col] = df_dims['activity_name']

    # 2. 数据
    try:
        res = supabase.table(table_name).select("*").eq("forest_id", forest_id).eq("record_type", record_type).eq("month", target_date).execute()
        df_facts = pd.DataFrame(res.data)
    except: df_facts = pd.DataFrame()
    
    # 3. 合并与清理
    if df_facts.empty:
        cols_to_keep = ['id', dim_name_col]
        if 'grade_code' in df_dims.columns: cols_to_keep.append('grade_code')
        df_merged = df_dims[cols_to_keep].rename(columns={'id': dim_id_col})
        for c in value_cols: df_merged[c] = 0.0
    else:
        df_merged = pd.merge(df_dims, df_facts, left_on='id', right_on=dim_id_col, how='left')
        for c in value_cols: df_merged[c] = df_merged[c].fillna(0.0)
    
    # 去重与索引重置 (防止 pandas 报错)
    df_merged = df_merged.loc[:, ~df_merged.columns.duplicated()]
    df_merged = df_merged.reset_index(drop=True)

    # 补充默认字段
    if 'market' not in df_merged.columns and 'grade_code' in df_merged.columns:
        df_merged['market'] = df_merged['grade_code'].apply(lambda x: 'Domestic' if 'Domestic' in str(x) else 'Export')
    if 'customer' not in df_merged.columns:
        df_merged['customer'] = 'FCO' 
        
    return df_merged

def save_monthly_data(edited_df, table_name, dim_id_col, forest_id, target_date, record_type):
    if not supabase or edited_df.empty: return False
    records = []
    for _, row in edited_df.iterrows():
        rec = {
            "forest_id": forest_id, dim_id_col: row[dim_id_col],
            "month": target_date, "record_type": record_type
        }
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
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #555; padding: 20px; }}
            .invoice-box {{ max-width: 800px; margin: auto; padding: 30px; border: 1px solid #eee; box-shadow: 0 0 10px rgba(0,0,0,.15); font-size: 16px; line-height: 24px; }}
            .invoice-box table {{ width: 100%; text-align: left; border-collapse: collapse; }}
            .invoice-box table td {{ padding: 5px; vertical-align: top; }}
            .heading td {{ background: #eee; border-bottom: 1px solid #ddd; font-weight: bold; }}
            .total td {{ border-top: 2px solid #eee; font-weight: bold; }}
            .text-right {{ text-align: right; }}
        </style>
    </head>
    <body>
        <div class="invoice-box">
            <table cellpadding="0" cellspacing="0">
                <tr class="top"><td colspan="2"><table><tr><td style="font-size:45px; line-height:45px; color:#333;">INVOICE</td><td class="text-right">Inv #: {invoice_no}<br>Date: {invoice_date}</td></tr></table></td></tr>
                <tr class="information"><td colspan="2"><table><tr><td><strong>FCO Management Ltd</strong><br>Napier, NZ</td><td class="text-right"><strong>Bill To:</strong><br>{bill_to}</td></tr></table></td></tr>
                <tr class="heading"><td>Description</td><td class="text-right">Amount (NZD)</td></tr>
                {rows_html}
                <tr class="total"><td></td><td class="text-right">Total Due: ${total_due:,.2f}</td></tr>
            </table>
        </div>
    </body>
    </html>
    """

# --- E. AI 识别核心逻辑 (修复版) ---
def real_extract_invoice_data(file_obj):
    try:
        # 1. 配置模型
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # 2. 读取文件
        file_obj.seek(0) # 确保从头读取
        file_bytes = file_obj.read()
        
        # 3. 发送指令
        prompt = """
        Analyze this invoice PDF. Extract into JSON:
        1. "vendor_detected": Company name.
        2. "invoice_no": Invoice number.
        3. "date_detected": YYYY-MM-DD.
        4. "amount_detected": Total numeric amount.
        
        Return ONLY valid JSON. Do not include markdown formatting like ```json.
        """
        
        response = model.generate_content([{'mime_type': 'application/pdf', 'data': file_bytes}, prompt])
        
        # 4. 解析结果
        text_response = response.text.strip()
        # 清理可能存在的 markdown 符号
        if text_response.startswith("```"):
            text_response = text_response.split("```")[1].strip()
        if text_response.startswith("json"): 
            text_response = text_response[4:].strip()
        
        data = json.loads(text_response)
        
        # 成功时：添加文件名
        data['filename'] = file_obj.name
        return data

    except Exception as e:
        # 失败时：也要返回文件名！(之前就是漏了这里)
        return {
            "filename": file_obj.name,   # <--- 关键修复：补上文件名
            "vendor_detected": "Error", 
            "invoice_no": "Error",
            "date_detected": "",
            "amount_detected": 0.0,
            "error": str(e)
        }