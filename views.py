# --- View 5: Invoice Bot ---
def view_invoice_bot():
    st.title("🤖 Invoice Bot (Audit & Archive)")
    
    # 尝试初始化 AI，如果没有配置 Key 则提示
    if not backend.init_gemini():
        st.error("⚠️ Google API Key missing! Please update .streamlit/secrets.toml")
        
    supabase = backend.supabase
    
    tab_audit, tab_archive = st.tabs(["🚀 Upload & Audit", "🗄️ Invoice Archive"])
    
    # --- Tab 1: Upload & Audit (带进度条版) ---
    with tab_audit:
        col_upload, col_review = st.columns([1, 2])
        
        with col_upload:
            st.subheader("1. Upload")
            uploaded_files = st.file_uploader("Drag PDFs here", type=["pdf"], accept_multiple_files=True)
            
            # 只有当上传了文件才显示按钮
            if uploaded_files:
                if st.button("🚀 Start AI Analysis", type="primary"):
                    results = []
                    
                    # --- 1. 初始化进度条和状态文本 ---
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    total_files = len(uploaded_files)
                    
                    # --- 2. 开始循环处理 ---
                    for i, file in enumerate(uploaded_files):
                        # 更新状态文字
                        status_text.markdown(f"**Analyzing {i+1}/{total_files}:** `{file.name}`...")
                        
                        # 调用后端 AI 分析
                        data = backend.real_extract_invoice_data(file)
                        
                        # 必须保存 file 对象本身，以便后续归档时上传
                        data['file_obj'] = file
                        results.append(data)
                        
                        # 更新进度条 (i+1 除以 总数)
                        progress_bar.progress((i + 1) / total_files)
                    
                    # --- 3. 完成 ---
                    progress_bar.progress(100) # 确保跑满
                    status_text.success(f"✅ Done! Processed {total_files} invoices.")
                    time.sleep(1) # 稍微停顿一下让用户看到成功提示
                    status_text.empty() # 清除状态文字
                    progress_bar.empty() # 清除进度条
                    
                    # 存入 Session State
                    st.session_state['ocr_results'] = results

        with col_review:
            st.subheader("2. Review & Archive")
            
            if 'ocr_results' in st.session_state:
                results = st.session_state['ocr_results']
                reconcile_data = []
                
                # ... (以下复核表格和归档逻辑保持不变) ...
                for i, item in enumerate(results):
                    # 简化的复核逻辑示例
                    match_status = "⚠️ Variance" # 默认
                    db_amount = 0
                    diff = 0
                    
                    # 尝试去数据库匹配
                    if item.get("vendor_detected") != "Error":
                        acts = backend.supabase.table("dim_cost_activities").select("id").ilike("activity_name", f"%{item['vendor_detected']}%").execute().data
                        if acts:
                            act_id = acts[0]['id']
                            costs = backend.supabase.table("fact_operational_costs").select("total_amount")\
                                .eq("activity_id", act_id).eq("record_type", "Actual").execute().data
                            if costs:
                                db_amount = costs[0]['total_amount']
                                diff = float(item['amount_detected']) - float(db_amount)
                                match_status = "✅ Match" if abs(diff) < 1.0 else "⚠️ Variance"

                    reconcile_data.append({
                        "Select": False,
                        "Index": i,
                        "File": item['filename'], 
                        "Vendor": item['vendor_detected'],
                        "Inv #": item.get('invoice_no', ''),
                        "Inv Amount": item['amount_detected'], 
                        "ERP Amount": db_amount, 
                        "Diff": diff, 
                        "Status": match_status
                    })
                
                # 显示表格
                df_rec = pd.DataFrame(reconcile_data)
                edited_df = st.data_editor(
                    df_rec, 
                    column_config={
                        "Select": st.column_config.CheckboxColumn("Archive?", default=True),
                        "Index": None
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                # 归档按钮
                if st.button("💾 Confirm & Save Selected to Cloud"):
                    save_progress = st.progress(0)
                    save_status = st.empty()
                    
                    selected_rows = edited_df[edited_df["Select"] == True]
                    total_save = len(selected_rows)
                    
                    if total_save > 0:
                        count = 0
                        for idx, row in selected_rows.iterrows():
                            save_status.text(f"Uploading {row['File']}...")
                            
                            # 获取原始数据
                            original_item = results[row['Index']]
                            file_obj = original_item['file_obj']
                            
                            # 上传文件 + 写入数据库
                            # 生成唯一文件名
                            path = f"{int(time.time())}_{row['File']}"
                            file_obj.seek(0)
                            backend.supabase.storage.from_("invoices").upload(path, file_obj.read(), {"content-type": "application/pdf"})
                            public_url = backend.supabase.storage.from_("invoices").get_public_url(path)
                            
                            backend.supabase.table("invoice_archive").insert({
                                "invoice_no": row['Inv #'],
                                "vendor": row['Vendor'],
                                "amount": row['Inv Amount'],
                                "file_name": row['File'],
                                "file_url": public_url,
                                "status": "Verified" if "Match" in row['Status'] else "Manual Check"
                            }).execute()
                            
                            count += 1
                            save_progress.progress(count / total_save)
                        
                        save_status.success("Archived successfully!")
                        time.sleep(1.5)
                        save_status.empty()
                        save_progress.empty()
                    else:
                        st.warning("No invoices selected.")

    with tab_archive:
        # ... (Tab 2 保持不变) ...
        view_invoice_archive() # 假设你把它封装成了函数，或者直接把代码贴在这里

# 辅助函数：Tab 2 的内容 (如果之前没封装，可以贴在 view_invoice_bot 里面)
def view_invoice_archive():
    st.subheader("🗄️ Invoice Digital Cabinet")
    search = st.text_input("Search Vendor/Invoice #")
    # ... (查询逻辑同前) ...