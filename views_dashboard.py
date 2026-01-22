import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit.components.v1 as components
from datetime import date
import backend 

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_MAP = {m: i+1 for i, m in enumerate(MONTHS)}

# --- 1. Dashboard ---
def view_dashboard():
    st.title("📊 Executive Dashboard")
    
    forests = backend.get_forest_list()
    if not forests: 
        st.warning("正在连接数据库或数据库为空...")
        return
    
    c1, c2 = st.columns([2, 1])
    with c1: 
        sel_forest = st.selectbox("Forest", ["ALL"] + [f['name'] for f in forests])
    with c2: 
        sel_year = st.selectbox("Year", [2025, 2026])
    
    try:
        q_vol = backend.supabase.table("fact_production_volume").select("*").eq("record_type", "Actual")
        if sel_forest != "ALL":
            fid = next(f['id'] for f in forests if f['name'] == sel_forest)
            q_vol = q_vol.eq("forest_id", fid)
        vol_data = q_vol.execute().data
        df_vol = pd.DataFrame(vol_data)

        q_cost = backend.supabase.table("fact_operational_costs").select("*").eq("record_type", "Actual")
        if sel_forest != "ALL":
            if 'fid' in locals():
                q_cost = q_cost.eq("forest_id", fid)
            else:
                 fid = next(f['id'] for f in forests if f['name'] == sel_forest)
                 q_cost = q_cost.eq("forest_id", fid)

        cost_data = q_cost.execute().data
        df_cost = pd.DataFrame(cost_data)

        rev = 0
        cost = 0
        
        if not df_vol.empty:
            df_vol['month'] = pd.to_datetime(df_vol['month'])
            df_vol = df_vol[df_vol['month'].dt.year == sel_year]
            rev = df_vol['amount'].sum()
        
        if not df_cost.empty:
            df_cost['month'] = pd.to_datetime(df_cost['month'])
            df_cost = df_cost[df_cost['month'].dt.year == sel_year]
            cost = df_cost['total_amount'].sum()
            
        margin = rev - cost

        k1, k2, k3 = st.columns(3)
        k1.metric("Total Revenue", f"${rev:,.0f}")
        k2.metric("Total Costs", f"${cost:,.0f}")
        k3.metric("Net Profit", f"${margin:,.0f}", delta=f"{(margin/rev*100) if rev else 0:.1f}%")

        st.divider()

        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader("Monthly P&L Trend")
            if not df_vol.empty or not df_cost.empty:
                v_m = df_vol.groupby('month')['amount'].sum().reset_index() if not df_vol.empty else pd.DataFrame()
                c_m = df_cost.groupby('month')['total_amount'].sum().reset_index() if not df_cost.empty else pd.DataFrame()
                
                if not v_m.empty: v_m.rename(columns={'amount': 'Revenue'}, inplace=True)
                if not c_m.empty: c_m.rename(columns={'total_amount': 'Costs'}, inplace=True)

                if not v_m.empty and not c_m.empty:
                    merged = pd.merge(v_m, c_m, on='month', how='outer').fillna(0)
                elif not v_m.empty:
                    merged = v_m.assign(Costs=0)
                else:
                    merged = c_m.assign(Revenue=0)
                
                if not merged.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=merged['month'], y=merged.get('Revenue',0), name='Revenue', marker_color='#27AE60'))
                    fig.add_trace(go.Bar(x=merged['month'], y=merged.get('Costs',0), name='Costs', marker_color='#C0392B'))
                    st.plotly_chart(fig, width="stretch")
            else:
                st.info("No data available yet.")

        with col_chart2:
            st.subheader("Cost Breakdown")
            if not df_cost.empty:
                try:
                    acts = pd.DataFrame(backend.supabase.table("dim_cost_activities").select("*").execute().data)
                    if not acts.empty:
                        merged_cost = pd.merge(df_cost, acts, left_on='activity_id', right_on='id')
                        fig2 = px.pie(merged_cost, values='total_amount', names='category', hole=0.4)
                        st.plotly_chart(fig2, width="stretch")
                except:
                    st.info("Could not load categories.")
            else:
                st.info("No cost data.")

    except Exception as e:
        st.error(f"Error loading dashboard: {e}")

# --- 2. Analysis & Invoice ---
def view_analysis_invoice():
    st.title("📈 Analysis & Invoicing")
    
    forests = backend.get_forest_list()
    if not forests: return
    
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: sel_forest = st.selectbox("Forest", [f['name'] for f in forests], key="inv_f")
    with c2: year = st.selectbox("Year", [2025, 2026], key="inv_y")
    with c3: month_str = st.selectbox("Month", MONTHS, key="inv_m")
    
    fid = next(f['id'] for f in forests if f['name'] == sel_forest)
    target_date = f"{year}-{MONTH_MAP[month_str]:02d}-01"

    st.subheader(f"📊 Budget vs Actual ({month_str} {year})")
    try:
        act_costs = backend.supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_costs = backend.supabase.table("fact_operational_costs").select("total_amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data
        act_revs = backend.supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Actual").execute().data
        bud_revs = backend.supabase.table("fact_production_volume").select("amount").eq("forest_id", fid).eq("month", target_date).eq("record_type", "Budget").execute().data

        total_act_cost = sum([x['total_amount'] for x in act_costs]) if act_costs else 0
        total_bud_cost = sum([x['total_amount'] for x in bud_costs]) if bud_costs else 0
        total_act_rev = sum([x['amount'] for x in act_revs]) if act_revs else 0
        total_bud_rev = sum([x['amount'] for x in bud_revs]) if bud_revs else 0
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Revenue", f"${total_act_rev:,.0f}", delta=f"${total_act_rev - total_bud_rev:,.0f} vs Budget")
        k2.metric("Costs", f"${total_act_cost:,.0f}", delta=f"${total_bud_cost - total_act_cost:,.0f} (vs Budget)", delta_color="inverse")
        k3.metric("Net Profit", f"${total_act_rev - total_act_cost:,.0f}")

        fig = go.Figure(data=[
            go.Bar(name='Budget', x=['Revenue', 'Costs'], y=[total_bud_rev, total_bud_cost], marker_color='#A9DFBF'),
            go.Bar(name='Actual', x=['Revenue', 'Costs'], y=[total_act_rev, total_act_cost], marker_color='#2874A6')
        ])
        fig.update_layout(barmode='group', height=300, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig, width="stretch")

    except Exception as e:
        st.error(f"Error loading analysis: {e}")
        total_act_cost = 0

    st.divider()

    st.subheader(f"📑 Invoice Generator")
    col_input, col_preview = st.columns([1, 2])
    with col_input:
        bill_to = st.text_input("Bill To", "CFG Forestry Group")
        mgmt_fee_pct = st.number_input("Mgmt Fee %", 0.0, 20.0, 8.0, 0.5)
        invoice_no = st.text_input("Inv No.", f"INV-{year}{MONTH_MAP[month_str]:02d}-{fid}")
        
        mgmt_fee_val = total_act_cost * (mgmt_fee_pct / 100)
        subtotal = total_act_cost + mgmt_fee_val
        gst_val = subtotal * 0.15
        total_due = subtotal + gst_val
        items = [{"desc": f"Operational & Harvesting Costs ({month_str} {year})", "amount": total_act_cost},
                 {"desc": f"Management Fee ({mgmt_fee_pct}%)", "amount": mgmt_fee_val}]

    invoice_html = backend.generate_invoice_html(invoice_no, date.today(), bill_to, month_str, year, items, subtotal, gst_val, total_due)
    with col_preview:
        components.html(invoice_html, height=700, scrolling=True)
        st.download_button("⬇️ Download HTML", invoice_html, file_name=f"{invoice_no}.html", mime="text/html")