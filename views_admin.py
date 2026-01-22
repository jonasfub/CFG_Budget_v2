import streamlit as st
import pandas as pd
import backend

def view_admin_upload():
    st.title("🔧 Admin: Upload GL Mappings")
    st.info("上传包含 Forest, Type(Cost/Revenue), Item Name, GL Code, GL Name 的 CSV/Excel")

    uploaded_file = st.file_uploader("Upload Mapping File", type=['csv', 'xlsx'])
    
    if uploaded_file and st.button("🚀 Process & Upload"):
        # 1. 读取文件
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        st.write("Preview:", df.head())
        
        # 2. 获取系统基础数据用于查找 ID
        forests = backend.supabase.table("dim_forests").select("*").execute().data
        activities = backend.supabase.table("dim_cost_activities").select("*").execute().data
        products = backend.supabase.table("dim_products").select("*").execute().data
        
        # 转成字典方便查找: name -> id
        forest_map = {f['name']: f['id'] for f in forests}
        act_map = {a['activity_name']: a['id'] for a in activities}
        prod_map = {p['grade_code']: p['id'] for p in products} # 假设用 Grade Code 匹配
        
        records = []
        errors = []
        
        # 3. 循环处理每一行
        progress = st.progress(0)
        for i, row in df.iterrows():
            try:
                # A. 找 Forest ID
                fid = forest_map.get(row['Forest'])
                if not fid:
                    errors.append(f"Row {i}: Forest '{row['Forest']}' not found.")
                    continue
                
                # B. 找 Item ID
                item_type = row['Type'] # 'Cost' or 'Revenue'
                item_name = row['Item Name']
                item_id = None
                
                if item_type == 'Cost':
                    item_id = act_map.get(item_name)
                    # 模糊匹配尝试 (可选)
                    if not item_id:
                        # 简单的包含匹配
                        for k, v in act_map.items():
                            if k in item_name or item_name in k:
                                item_id = v; break
                elif item_type == 'Revenue':
                    item_id = prod_map.get(item_name)
                
                if not item_id:
                    errors.append(f"Row {i}: Item '{item_name}' ({item_type}) not found in DB.")
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
                errors.append(f"Row {i}: Error {str(e)}")
            
            progress.progress((i+1)/len(df))
            
        # 4. 批量写入 Supabase
        if records:
            try:
                # 你的 dim_gl_mappings 表必须设置了 UNIQUE(forest_id, item_type, item_id) 才能用 Upsert
                backend.supabase.table("dim_gl_mappings").upsert(records, on_conflict="forest_id,item_type,item_id").execute()
                st.success(f"✅ Successfully uploaded {len(records)} mappings!")
            except Exception as e:
                st.error(f"Database Upload Error: {e}")
        
        if errors:
            st.warning(f"⚠️ {len(errors)} rows failed:")
            st.write(errors)