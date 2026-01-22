import streamlit as st
import pandas as pd
import backend
import time

def view_admin_upload():
    st.title("⚙️ Admin: Chart of Accounts Setup")
    st.markdown("### 上传会计科目映射表 (GL Mapping)")
    st.info("请上传包含以下列的 Excel/CSV: `Forest`, `Type` (Cost/Revenue), `Item Name`, `GL Code`, `GL Name`")

    uploaded_file = st.file_uploader("Upload Mapping File", type=['csv', 'xlsx'])
    
    if uploaded_file and st.button("🚀 Process & Upload", type="primary"):
        # 1. 读取文件
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.write("👀 文件预览 (前5行):", df.head())
            
            # 2. 获取系统基础数据用于查找 ID
            with st.spinner("正在同步数据库基础信息..."):
                forests = backend.supabase.table("dim_forests").select("*").execute().data
                activities = backend.supabase.table("dim_cost_activities").select("*").execute().data
                products = backend.supabase.table("dim_products").select("*").execute().data
            
            # 转成字典方便查找: name -> id
            forest_map = {f['name']: f['id'] for f in forests}
            act_map = {a['activity_name']: a['id'] for a in activities}
            prod_map = {p['grade_code']: p['id'] for p in products} 
            
            records = []
            errors = []
            
            # 3. 循环处理每一行
            progress_bar = st.progress(0)
            for i, row in df.iterrows():
                try:
                    # A. 找 Forest ID
                    fid = forest_map.get(row['Forest'])
                    if not fid:
                        errors.append(f"Row {i+1}: Forest '{row['Forest']}' 未找到 (请检查拼写)")
                        continue
                    
                    # B. 找 Item ID
                    item_type = row['Type'] # 'Cost' or 'Revenue'
                    item_name = row['Item Name']
                    item_id = None
                    
                    if item_type == 'Cost':
                        item_id = act_map.get(item_name)
                        # 模糊匹配尝试 (可选)
                        if not item_id:
                            for k, v in act_map.items():
                                if k in item_name or item_name in k:
                                    item_id = v; break
                    elif item_type == 'Revenue':
                        item_id = prod_map.get(item_name)
                    
                    if not item_id:
                        errors.append(f"Row {i+1}: Item '{item_name}' ({item_type}) 系统里没有这个项目")
                        continue
                    
                    # C. 构建记录
                    records.append({
                        "forest_id": fid,
                        "item_type": item_type,
                        "item_id": item_id,
                        "gl_code": str(row['GL Code']),
                        "gl_name": row['GL Name']
                    })
                    
                except Exception as e:
                    errors.append(f"Row {i+1}: 数据格式错误 {str(e)}")
                
                progress_bar.progress((i+1)/len(df))
                
            # 4. 批量写入 Supabase
            if records:
                try:
                    # 你的 dim_gl_mappings 表必须设置了 UNIQUE(forest_id, item_type, item_id) 才能用 Upsert
                    backend.supabase.table("dim_gl_mappings").upsert(records, on_conflict="forest_id,item_type,item_id").execute()
                    st.success(f"✅ 成功导入 {len(records)} 条会计科目映射！")
                    time.sleep(2)
                except Exception as e:
                    st.error(f"数据库写入失败: {e}")
            
            if errors:
                st.warning(f"⚠️ 有 {len(errors)} 行数据处理失败:")
                st.dataframe(pd.DataFrame(errors, columns=["Error Log"]), use_container_width=True)

        except Exception as e:
            st.error(f"文件读取失败: {e}")