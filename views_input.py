import streamlit as st
import pandas as pd
from datetime import date
import backend 

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# --- 1. Log Sales ---
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


# --- 2. Monthly Input ---
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