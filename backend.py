import streamlit as st
import pandas as pd
from supabase import create_client
from google import genai            # <--- 新版导入方式
from google.genai import types      # <--- 引入类型支持
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

# --- B. Google AI 检查 ---
def check_google_key():
    # 检查 secrets 是否存在
    return "google" in st.secrets and "api_key" in st.secrets["google"]

# --- C. 核心数据函数 (保持不变) ---
def get_forest_list():
    if not supabase: return []
    try:
        return supabase.table("dim_forests").select("*").execute().data
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

# --- E. AI 识别核心逻辑 (新版 SDK 实现) ---
def real_extract_invoice_data(file_obj):
    try:
        # 1. 检查 Key
        if not check_google_key():
            return {"vendor_detected": "Error", "error": "API Key missing", "amount_detected": 0, "filename": file_obj.name}

        # 2. 初始化客户端 (新版写法)
        client = genai.Client(api_key=st.secrets["google"]["api_key"])
        
        # 3. 读取文件
        file_obj.seek(0)
        file_bytes = file_obj.read()
        
        # 4. 构建 Prompt
        prompt_text = """
        Analyze this invoice PDF. Extract into JSON:
        1. "vendor_detected": Company name.
        2. "invoice_no": Invoice number.
        3. "date_detected": YYYY-MM-DD.
        4. "amount_detected": Total numeric amount.
        Return ONLY valid JSON.
        """
        
        # 5. 调用 AI (新版写法：使用 contents 列表包含 Parts)
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=file_bytes, mime_type='application/pdf'),
                        types.Part.from_text(text=prompt_text)
                    ]
                )
            ]
        )
        
        # 6. 解析结果
        text_response = response.text.strip()
        if text_response.startswith("```"):
            text_response = text_response.split("```")[1].strip()
        if text_response.startswith("json"): 
            text_response = text_response[4:].strip()
        
        data = json.loads(text_response)
        data['filename'] = file_obj.name
        return data

    except Exception as e:
        return {
            "filename": file_obj.name,
            "vendor_detected": "Error", 
            "invoice_no": "Error",
            "date_detected": "",
            "amount_detected": 0.0,
            "error": str(e)
        }