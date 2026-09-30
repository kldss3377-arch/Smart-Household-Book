import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import io

# -------------------------------------------------------------
# 1. 페이지 설정 및 로그인 인증 게이트웨이
# -------------------------------------------------------------
st.set_page_config(
    page_title="스마트 가계부 & 자산 분석 시스템",
    page_icon="💰",
    layout="wide"
)

# 수정 코드 (로컬 및 웹 배포 환경 모두 안전하게 동작)
try:
    APP_PASSWORD = st.secrets.get("APP_PASSWORD", "1234")
except Exception:
    APP_PASSWORD = "1234"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def login_screen():
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col_center, _ = st.columns([1, 1.2, 1])
    with col_center:
        st.markdown("### 🔐 스마트 가계부 로그인")
        st.info("개인 금융 데이터 보호를 위해 비밀번호를 입력해 주세요.")
        input_pw = st.text_input("접속 비밀번호", type="password", key="login_pw_input")
        if st.button("로그인", use_container_width=True):
            if input_pw == APP_PASSWORD:
                st.session_state.authenticated = True
                st.success("인증에 성공했습니다.")
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")

if not st.session_state.authenticated:
    login_screen()
    st.stop()

# -------------------------------------------------------------
# 2. 로컬 SQLite DB 관리 함수
# -------------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect("household.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fixed_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        name TEXT,
        amount INTEGER,
        payment_method TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS variable_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER,
        type TEXT,
        date TEXT,
        name TEXT,
        amount INTEGER,
        category TEXT
    )""")
    conn.commit()

    # 초기 기본 데이터 주입
    cur.execute("SELECT COUNT(*) FROM categories")
    if cur.fetchone()[0] == 0:
        base_cats = ["급여", "식비", "외식", "교통", "차량", "쇼핑", "생활", "교육", "의료", "문화", "여가", "경조사", "기부", "급여외수입", "기타"]
        cur.executemany("INSERT INTO categories (name) VALUES (?)", [(c,) for c in base_cats])

    cur.execute("SELECT COUNT(*) FROM fixed_items")
    if cur.fetchone()[0] == 0:
        base_fixed = [
            ('수입', '본인 급여', 4800000, '-'),
            ('수입', '배우자 급여', 1200000, '-'),
            ('지출', '주택담보대출', 1100000, '자동이체'),
            ('지출', '관리비/공과금', 280000, '자동이체'),
            ('지출', '보험료(통합)', 320000, '카드납부'),
            ('지출', '통신비/인터넷', 150000, '자동이체'),
            ('지출', '정기구독료', 45000, '카드결제')
        ]
        cur.executemany("INSERT INTO fixed_items (type, name, amount, payment_method) VALUES (?, ?, ?, ?)", base_fixed)

    cur.execute("SELECT COUNT(*) FROM variable_records")
    if cur.fetchone()[0] == 0:
        base_vars = [
            (1, '수입', '01-10', '연말정산 환급', 350000, '급여외수입'),
            (1, '수입', '01-20', '중고물품 판매', 50000, '기타'),
            (1, '지출', '01-03', '식자재 및 장보기', 185000, '식비'),
            (1, '지출', '01-07', '주말 가족외식', 92000, '외식'),
            (1, '지출', '01-12', '주유비', 85000, '교통'),
            (1, '지출', '01-15', '겨울 외투 구매', 160000, '쇼핑'),
            (1, '지출', '01-18', '도서 구입', 35000, '문화'),
            (1, '지출', '01-25', '생활용품 구매', 48000, '생활')
        ]
        cur.executemany("INSERT INTO variable_records (month, type, date, name, amount, category) VALUES (?, ?, ?, ?, ?, ?)", base_vars)

    conn.commit()
    conn.close()

init_db()

def get_categories():
    conn = get_db_connection()
    df = pd.read_sql("SELECT name FROM categories", conn)
    conn.close()
    return df['name'].tolist()

def get_fixed_items():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM fixed_items", conn)
    conn.close()
    return df

def get_variable_records():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM variable_records", conn)
    conn.close()
    return df

# -------------------------------------------------------------
# 3. 수지 계산 함수 (총지출 = 고정지출 + 변동지출)
# -------------------------------------------------------------
def calculate_monthly_summary():
    df_fix = get_fixed_items()
    df_var = get_variable_records()
    
    tot_fixed_inc = df_fix[df_fix['type'] == '수입']['amount'].sum()
    tot_fixed_exp = df_fix[df_fix['type'] == '지출']['amount'].sum()
    
    summary = []
    accumulated_savings = 0
    for m in range(1, 13):
        m_df = df_var[df_var['month'] == m] if not df_var.empty else pd.DataFrame()
        var_inc = m_df[m_df['type'] == '수입']['amount'].sum() if not m_df.empty else 0
        var_exp = m_df[m_df['type'] == '지출']['amount'].sum() if not m_df.empty else 0
        
        tot_inc = tot_fixed_inc + var_inc
        tot_exp = tot_fixed_exp + var_exp
        net_savings = tot_inc - tot_exp
        accumulated_savings += net_savings
        savings_rate = (net_savings / tot_inc * 100) if tot_inc > 0 else 0
        
        summary.append({
            "월": f"{m}월",
            "총 수입": tot_inc,
            "총 지출": tot_exp,
            "고정 지출": tot_fixed_exp,
            "변동 지출": var_exp,
            "당월 순저축": net_savings,
            "누적 순저축": accumulated_savings,
            "저축률(%)": round(savings_rate, 2)
        })
    return pd.DataFrame(summary)

# -------------------------------------------------------------
# 4. 사이드바 메뉴 및 공통 작업
# -------------------------------------------------------------
st.sidebar.title("📌 가계부 시스템")
menu = st.sidebar.radio(
    "메뉴 선택",
    ["연간 통합 대시보드", "월별 수입/지출 내역 관리", "고정 수입/지출 관리", "분류(카테고리) 설정", "심층 통계 분석"]
)

# 로그아웃 버튼
if st.sidebar.button("🔒 로그아웃"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💾 데이터 엑셀 내보내기")
df_summary_export = calculate_monthly_summary()
df_var_all = get_variable_records()
df_fix_all = get_fixed_items()
output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df_summary_export.to_excel(writer, sheet_name='연간요약', index=False)
    if not df_var_all.empty:
        df_var_all.to_excel(writer, sheet_name='변동내역전체', index=False)
    df_fix_all.to_excel(writer, sheet_name='고정항목설정', index=False)
    pd.DataFrame({"분류명": get_categories()}).to_excel(writer, sheet_name='분류목록', index=False)

st.sidebar.download_button(
    label="현재 가계부 엑셀 다운로드",
    data=output.getvalue(),
    file_name="가계부_연간_관리대장.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)

# -------------------------------------------------------------
# 메뉴 1: 연간 통합 대시보드
# -------------------------------------------------------------
if menu == "연간 통합 대시보드":
    st.title("📊 연간 수입 / 지출 통합 대시보드")
    df_summary = calculate_monthly_summary()
    
    tot_year_inc = df_summary["총 수입"].sum()
    tot_year_exp = df_summary["총 지출"].sum()
    tot_year_sav = df_summary["당월 순저축"].sum()
    avg_sav_rate = (tot_year_sav / tot_year_inc * 100) if tot_year_inc > 0 else 0
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("연간 총수입", f"{tot_year_inc:,} 원")
    col2.metric("연간 총지출", f"{tot_year_exp:,} 원")
    col3.metric("연간 순저축", f"{tot_year_sav:,} 원")
    col4.metric("연간 평균 저축률", f"{avg_sav_rate:.1f} %")
    
    st.divider()
    
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(x=df_summary["월"], y=df_summary["총 수입"], name="총 수입", marker_color="#2962FF"))
    fig_bar.add_trace(go.Bar(x=df_summary["월"], y=df_summary["총 지출"], name="총 지출", marker_color="#FF5252"))
    fig_bar.add_trace(go.Scatter(x=df_summary["월"], y=df_summary["당월 순저축"], name="순저축", mode="lines+markers", marker_color="#00C853"))
    fig_bar.update_layout(title="월별 수입, 지출 및 순저축 추이", barmode="group", hovermode="x unified", margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig_bar, use_container_width=True)
    
    c1, c2 = st.columns(2)
    with c1:
        exp_comp = pd.DataFrame({
            "구분": ["고정 지출", "변동 지출"],
            "금액": [df_summary["고정 지출"].sum(), df_summary["변동 지출"].sum()]
        })
        fig_pie1 = px.pie(exp_comp, names="구분", values="금액", title="고정 지출 vs 변동 지출 비율", hole=0.45, color_discrete_sequence=["#FF7043", "#FFA726"])
        st.plotly_chart(fig_pie1, use_container_width=True)
        
    with c2:
        df_var_exp = df_var_all[df_var_all['type'] == '지출'] if not df_var_all.empty else pd.DataFrame()
        if not df_var_exp.empty:
            cat_sum = df_var_exp.groupby("category")["amount"].sum().reset_index()
            fig_pie2 = px.pie(cat_sum, names="category", values="amount", title="변동 지출 카테고리별 비중", hole=0.45)
            st.plotly_chart(fig_pie2, use_container_width=True)
        else:
            st.info("등록된 변동 지출 내역이 없습니다.")
            
    st.subheader("📑 월별 상세 수지 분석표")
    st.dataframe(df_summary.style.format({
        "총 수입": "{:,}원", "총 지출": "{:,}원", "고정 지출": "{:,}원",
        "변동 지출": "{:,}원", "당월 순저축": "{:,}원", "누적 순저축": "{:,}원", "저축률(%)": "{:.2f}%"
    }), use_container_width=True)

# -------------------------------------------------------------
# 메뉴 2: 월별 수입/지출 내역 관리
# -------------------------------------------------------------
elif menu == "월별 수입/지출 내역 관리":
    selected_month = st.sidebar.selectbox("조회/관리할 월 선택", [f"{i}월" for i in range(1, 13)])
    month_int = int(selected_month.replace("월", ""))
    
    st.title(f"🗓️ {selected_month} 가계부 내역 관리")
    
    df_fix = get_fixed_items()
    tot_fixed_inc = df_fix[df_fix['type'] == '수입']['amount'].sum()
    tot_fixed_exp = df_fix[df_fix['type'] == '지출']['amount'].sum()
    
    all_recs = get_variable_records()
    m_records = all_recs[all_recs["month"] == month_int] if not all_recs.empty else pd.DataFrame()
    
    m_var_inc = m_records[m_records["type"] == "수입"]["amount"].sum() if not m_records.empty else 0
    m_var_exp = m_records[m_records["type"] == "지출"]["amount"].sum() if not m_records.empty else 0
    
    m_tot_inc = tot_fixed_inc + m_var_inc
    m_tot_exp = tot_fixed_exp + m_var_exp
    m_net = m_tot_inc - m_tot_exp
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("총 수입", f"{m_tot_inc:,} 원", delta=f"변동 +{m_var_inc:,}")
    kpi2.metric("총 지출", f"{m_tot_exp:,} 원", delta=f"고정 {tot_fixed_exp:,} + 변동 {m_var_exp:,}", delta_color="inverse")
    kpi3.metric("당월 순저축", f"{m_net:,} 원")
    kpi4.metric("당월 저축률", f"{(m_net/m_tot_inc*100):.1f} %" if m_tot_inc > 0 else "0 %")
    
    st.divider()
    current_categories = get_categories()

    if 'editing_record_id' not in st.session_state:
        st.session_state.editing_record_id = None

    if st.session_state.editing_record_id is not None:
        edit_row = all_recs[all_recs["id"] == st.session_state.editing_record_id]
        if not edit_row.empty:
            edit_item = edit_row.iloc[0]
            st.warning(f"✏️ [내역 수정] 항목 ID #{edit_item['id']} 수정 중입니다.")
            with st.form("edit_record_form"):
                col_type, col_date, col_name, col_amt, col_cat = st.columns([1.2, 1.2, 2.5, 2, 1.8])
                new_type = col_type.selectbox("구분", ["지출", "수입"], index=0 if edit_item["type"] == "지출" else 1)
                new_date = col_date.text_input("일자 (MM-DD)", edit_item["date"])
                new_name = col_name.text_input("항목명", edit_item["name"])
                new_amt = col_amt.number_input("금액 (원)", min_value=0, value=int(edit_item["amount"]), step=1000)
                cat_idx = current_categories.index(edit_item["category"]) if edit_item["category"] in current_categories else 0
                new_cat = col_cat.selectbox("분류", current_categories, index=cat_idx)
                
                b_save, b_cancel = st.columns(2)
                if b_save.form_submit_button("수정 내용 저장", use_container_width=True):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("UPDATE variable_records SET type=?, date=?, name=?, amount=?, category=? WHERE id=?", 
                                (new_type, new_date, new_name, new_amt, new_cat, int(edit_item['id'])))
                    conn.commit()
                    conn.close()
                    st.session_state.editing_record_id = None
                    st.success("내역 수정 완료")
                    st.rerun()
                if b_cancel.form_submit_button("수정 취소", use_container_width=True):
                    st.session_state.editing_record_id = None
                    st.rerun()

    st.subheader(f"➕ {selected_month} 새로운 내역 추가")
    with st.form("add_record_form", clear_on_submit=True):
        col_type, col_date, col_name, col_amt, col_cat = st.columns([1.2, 1.2, 2.5, 2, 1.8])
        rec_type = col_type.selectbox("구분", ["지출", "수입"])
        rec_date = col_date.text_input("일자 (MM-DD)", f"{month_int:02d}-01")
        rec_name = col_name.text_input("항목명", placeholder="예: 급여, 마트 장보기")
        rec_amt = col_amt.number_input("금액 (원)", min_value=0, step=1000)
        rec_cat = col_cat.selectbox("분류", current_categories)
        
        if st.form_submit_button("내역 등록하기", use_container_width=True):
            if rec_name and rec_amt > 0:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO variable_records (month, type, date, name, amount, category) VALUES (?, ?, ?, ?, ?, ?)",
                            (month_int, rec_type, rec_date, rec_name, rec_amt, rec_cat))
                conn.commit()
                conn.close()
                st.success(f"'{rec_name}' 등록 완료")
                st.rerun()
            else:
                st.error("항목명과 유효한 금액을 입력해 주세요.")

    st.subheader(f"📝 {selected_month} 등록 내역 목록")
    if not m_records.empty:
        h1, h2, h3, h4, h5, h6, h7 = st.columns([1.2, 1.2, 3, 2, 1.8, 1, 1])
        h1.markdown("**일자**"); h2.markdown("**구분**"); h3.markdown("**항목명**"); h4.markdown("**금액**"); h5.markdown("**분류**"); h6.markdown("**수정**"); h7.markdown("**삭제**")
        for idx, row in m_records.iterrows():
            c1, c2, c3, c4, c5, c6, c7 = st.columns([1.2, 1.2, 3, 2, 1.8, 1, 1])
            c1.text(row["date"])
            c2.markdown(f"<span style='color:{'#2962FF' if row['type']=='수입' else '#FF5252'}; font-weight:bold;'>{row['type']}</span>", unsafe_allow_html=True)
            c3.text(row["name"])
            c4.text(f"{row['amount']:,} 원")
            c5.text(row["category"])
            if c6.button("✏️", key=f"edit_btn_{row['id']}"):
                st.session_state.editing_record_id = row['id']
                st.rerun()
            if c7.button("🗑️", key=f"del_rec_{row['id']}"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM variable_records WHERE id=?", (int(row['id']),))
                conn.commit()
                conn.close()
                st.rerun()
    else:
        st.info("해당 월에 등록된 변동 내역이 없습니다.")

# -------------------------------------------------------------
# 메뉴 3: 고정 수입/지출 관리
# -------------------------------------------------------------
elif menu == "고정 수입/지출 관리":
    st.title("⚙️ 고정 수입 및 고정 지출 설정")
    df_fix = get_fixed_items()
    col_l, col_r = st.columns(2)
    
    with col_l:
        st.subheader("💵 고정 수입 항목")
        with st.form("add_finc_form", clear_on_submit=True):
            f_inc_name = st.text_input("고정 수입 항목명", placeholder="예: 본인 급여")
            f_inc_amt = st.number_input("월 수입 금액 (원)", min_value=0, step=10000)
            if st.form_submit_button("고정 수입 추가", use_container_width=True):
                if f_inc_name and f_inc_amt > 0:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO fixed_items (type, name, amount, payment_method) VALUES ('수입', ?, ?, '-')", (f_inc_name, f_inc_amt))
                    conn.commit()
                    conn.close()
                    st.rerun()
        
        inc_items = df_fix[df_fix['type'] == '수입']
        st.markdown(f"**월 고정 수입 합계: `{inc_items['amount'].sum():,} 원`**")
        for idx, item in inc_items.iterrows():
            with st.expander(f"{item['name']} : {item['amount']:,} 원"):
                with st.form(f"finc_{item['id']}"):
                    un = st.text_input("항목명", value=item['name'])
                    ua = st.number_input("월 금액 (원)", min_value=0, value=int(item['amount']), step=10000)
                    b1, b2 = st.columns(2)
                    if b1.form_submit_button("변경 저장"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("UPDATE fixed_items SET name=?, amount=? WHERE id=?", (un, ua, int(item['id'])))
                        conn.commit()
                        conn.close()
                        st.rerun()
                    if b2.form_submit_button("삭제", type="secondary"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("DELETE FROM fixed_items WHERE id=?", (int(item['id']),))
                        conn.commit()
                        conn.close()
                        st.rerun()

    with col_r:
        st.subheader("💳 고정 지출 항목")
        pay_methods = ["자동이체", "카드납부", "카드결제", "현금", "기타"]
        with st.form("add_fexp_form", clear_on_submit=True):
            f_exp_name = st.text_input("고정 지출 항목명", placeholder="예: 주택담보대출")
            f_exp_amt = st.number_input("월 지출 금액 (원)", min_value=0, step=10000)
            f_exp_pay = st.selectbox("결제방식", pay_methods)
            if st.form_submit_button("고정 지출 추가", use_container_width=True):
                if f_exp_name and f_exp_amt > 0:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO fixed_items (type, name, amount, payment_method) VALUES ('지출', ?, ?, ?)", (f_exp_name, f_exp_amt, f_exp_pay))
                    conn.commit()
                    conn.close()
                    st.rerun()
        
        exp_items = df_fix[df_fix['type'] == '지출']
        st.markdown(f"**월 고정 지출 합계: `{exp_items['amount'].sum():,} 원`**")
        for idx, item in exp_items.iterrows():
            with st.expander(f"{item['name']} ({item['payment_method']}) : {item['amount']:,} 원"):
                with st.form(f"fexp_{item['id']}"):
                    un = st.text_input("항목명", value=item['name'])
                    ua = st.number_input("월 금액 (원)", min_value=0, value=int(item['amount']), step=10000)
                    up = st.selectbox("결제방식", pay_methods, index=pay_methods.index(item['payment_method']) if item['payment_method'] in pay_methods else 0)
                    b1, b2 = st.columns(2)
                    if b1.form_submit_button("변경 저장"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("UPDATE fixed_items SET name=?, amount=?, payment_method=? WHERE id=?", (un, ua, up, int(item['id'])))
                        conn.commit()
                        conn.close()
                        st.rerun()
                    if b2.form_submit_button("삭제", type="secondary"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("DELETE FROM fixed_items WHERE id=?", (int(item['id']),))
                        conn.commit()
                        conn.close()
                        st.rerun()

# -------------------------------------------------------------
# 메뉴 4: 분류(카테고리) 설정
# -------------------------------------------------------------
elif menu == "분류(카테고리) 설정":
    st.title("🏷️ 분류(카테고리) 항목 설정")
    cats = get_categories()
    c_add, c_list = st.columns([1, 1.5])
    
    with c_add:
        st.subheader("➕ 새 분류 항목 추가")
        with st.form("add_cat_form", clear_on_submit=True):
            new_c = st.text_input("분류 이름")
            if st.form_submit_button("분류 추가", use_container_width=True):
                if new_c.strip() and new_c.strip() not in cats:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO categories (name) VALUES (?)", (new_c.strip(),))
                    conn.commit()
                    conn.close()
                    st.rerun()
                else:
                    st.warning("유효한 이름이 아니거나 이미 존재하는 분류입니다.")
                    
    with c_list:
        st.subheader(f"📋 등록된 분류 목록 ({len(cats)}개)")
        for c in cats:
            with st.expander(f"📁 {c}"):
                with st.form(f"cat_edit_{c}"):
                    renamed = st.text_input("분류명 변경", value=c)
                    cb1, cb2 = st.columns(2)
                    if cb1.form_submit_button("이름 변경 저장"):
                        if renamed.strip() and renamed.strip() != c:
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("UPDATE categories SET name=? WHERE name=?", (renamed.strip(), c))
                            cur.execute("UPDATE variable_records SET category=? WHERE category=?", (renamed.strip(), c))
                            conn.commit()
                            conn.close()
                            st.rerun()
                    if cb2.form_submit_button("분류 삭제", type="secondary"):
                        if len(cats) > 1:
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("DELETE FROM categories WHERE name=?", (c,))
                            cur.execute("UPDATE variable_records SET category='기타' WHERE category=?", (c,))
                            conn.commit()
                            conn.close()
                            st.rerun()
                        else:
                            st.error("최소 1개 이상의 분류가 필요합니다.")

# -------------------------------------------------------------
# 메뉴 5: 심층 통계 분석 (신규 추가된 전문 차트 섹션)
# -------------------------------------------------------------
elif menu == "심층 통계 분석":
    st.title("📈 가계 심층 통계 & 재무 분석")
    df_summary = calculate_monthly_summary()
    df_var = get_variable_records()
    df_fix = get_fixed_items()
    
    # 1. 누적 자산(순저축) 형성 곡선 (Area Chart)
    st.subheader("1️⃣ 누적 순저축 자산 형성 추이")
    fig_cum = px.area(
        df_summary, 
        x="월", 
        y="누적 순저축", 
        title="연간 자산 누적 곡선 (단위: 원)",
        color_discrete_sequence=["#00C853"]
    )
    fig_cum.update_traces(mode="lines+markers")
    st.plotly_chart(fig_cum, use_container_width=True)
    
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        # 2. 월별 저축률 트렌드 (Line + Threshold)
        st.subheader("2️⃣ 월별 저축률(%) 변화 추이")
        fig_rate = go.Figure()
        fig_rate.add_trace(go.Scatter(
            x=df_summary["월"], 
            y=df_summary["저축률(%)"], 
            mode='lines+markers+text',
            text=df_summary["저축률(%)"].apply(lambda x: f"{x:.1f}%"),
            textposition="top center",
            line=dict(color="#2962FF", width=3),
            name="저축률"
        ))
        # 평균 저축률 가이드 라인 추가
        avg_rate = df_summary["저축률(%)"].mean()
        fig_rate.add_hline(y=avg_rate, line_dash="dash", line_color="orange", annotation_text=f"연간 평균 ({avg_rate:.1f}%)")
        fig_rate.update_layout(yaxis=dict(title="저축률 (%)", range=[0, 100]))
        st.plotly_chart(fig_rate, use_container_width=True)

    with col_chart2:
        # 3. 변동 지출 카테고리별 누적 지출 랭킹 (Horizontal Bar)
        st.subheader("3️⃣ 카테고리별 누적 지출 순위 (Top Spending)")
        var_exp = df_var[df_var['type'] == '지출'] if not df_var.empty else pd.DataFrame()
        if not var_exp.empty:
            cat_ranked = var_exp.groupby("category")["amount"].sum().reset_index()
            cat_ranked = cat_ranked.sort_values(by="amount", ascending=True)
            fig_rank = px.bar(
                cat_ranked, 
                x="amount", 
                y="category", 
                orientation='h',
                text="amount",
                color="amount",
                color_continuous_scale="Reds"
            )
            fig_rank.update_traces(texttemplate='%{text:,}원', textposition='outside')
            fig_rank.update_layout(xaxis_title="총 지출액 (원)", yaxis_title="분류", coloraxis_showscale=False)
            st.plotly_chart(fig_rank, use_container_width=True)
        else:
            st.info("지출 내역이 충분하지 않습니다.")

    # 4. 결제 수단별 고정 지출 분포
    st.subheader("4️⃣ 고정 지출 결제 방식 비중")
    fix_exp = df_fix[df_fix['type'] == '지출']
    if not fix_exp.empty:
        pay_sum = fix_exp.groupby("payment_method")["amount"].sum().reset_index()
        fig_pay = px.bar(pay_sum, x="payment_method", y="amount", text="amount", color="payment_method", title="결제 수단별 월 고정지출액")
        fig_pay.update_traces(texttemplate='%{text:,}원', textposition='outside')
        st.plotly_chart(fig_pay, use_container_width=True)
