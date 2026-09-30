import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import io

# -------------------------------------------------------------
# 1. 페이지 설정
# -------------------------------------------------------------
st.set_page_config(
    page_title="스마트 가계부 & 대/소분류 자산 분석 시스템",
    page_icon="💰",
    layout="wide"
)

DB_PATH = "household.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------------------------------------------
# 2. SQLite DB 초기화 및 안전 마이그레이션
# -------------------------------------------------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 0) 시스템 설정 (비밀번호)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    cur.execute("SELECT value FROM settings WHERE key='app_password'")
    if cur.fetchone() is None:
        cur.execute("INSERT INTO settings (key, value) VALUES ('app_password', '1234')")
    
    # 1) 대분류-소분류 관리 테이블
    cur.execute("""
    CREATE TABLE IF NOT EXISTS category_hierarchy (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT, -- '수입' or '지출'
        category TEXT, -- 대분류
        sub_category TEXT, -- 소분류
        UNIQUE(type, category, sub_category)
    )""")
    
    # 2) 고정 수입/지출 항목
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fixed_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        name TEXT,
        amount INTEGER,
        payment_method TEXT,
        category TEXT DEFAULT '고정비',
        sub_category TEXT DEFAULT '기타'
    )""")
    
    # 3) 거래 내역 테이블
    cur.execute("""
    CREATE TABLE IF NOT EXISTS variable_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER,
        type TEXT,
        date TEXT,
        time TEXT DEFAULT '',
        name TEXT,
        amount INTEGER,
        category TEXT,
        sub_category TEXT DEFAULT '기타',
        memo TEXT DEFAULT '',
        source TEXT DEFAULT '수기'
    )""")
    
    # 4) 지능형 자동 분류 규칙 (대분류 + 소분류 연계)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT DEFAULT '지출',
        category TEXT,
        sub_category TEXT,
        keyword TEXT UNIQUE
    )""")
    conn.commit()

    # --- 기존 DB 테이블 컬럼 자동 마이그레이션 ---
    cur.execute("PRAGMA table_info(variable_records)")
    v_cols = [row[1] for row in cur.fetchall()]
    if "time" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN time TEXT DEFAULT ''")
    if "sub_category" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN sub_category TEXT DEFAULT '기타'")
    if "memo" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN memo TEXT DEFAULT ''")
    if "source" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN source TEXT DEFAULT '수기'")
    
    cur.execute("PRAGMA table_info(auto_rules)")
    r_cols = [row[1] for row in cur.fetchall()]
    if "sub_category" not in r_cols: cur.execute("ALTER TABLE auto_rules ADD COLUMN sub_category TEXT DEFAULT '기타'")
    conn.commit()

    # 기본 대/소분류 카테고리 주입
    cur.execute("SELECT COUNT(*) FROM category_hierarchy")
    if cur.fetchone()[0] == 0:
        base_hierarchy = [
            # 수입 체계
            ('수입', '급여', '본인급여'), ('수입', '급여', '배우자급여'), ('수입', '급여', '상여금/성과급'),
            ('수입', '금융수입', '이자수익'), ('수입', '금융수입', '배당금'),
            ('수입', '기타수입', '환급금/공제'), ('수입', '기타수입', '중고판매'), ('수입', '기타수입', '용돈/지원금'), ('수입', '기타수입', '기타'),
            # 지출 체계
            ('지출', '식비', '식자재/마트'), ('지출', '식비', '간식/가공식품'),
            ('지출', '외식', '음식점/외식'), ('지출', '외식', '카페/디저트'), ('지출', '외식', '배달음식'),
            ('지출', '교통', '주유비'), ('지출', '교통', '대중교통'), ('지출', '교통', '통행료/하이패스'), ('지출', '교통', '택시비'),
            ('지출', '차량', '차량정비/부품'), ('지출', '차량', '세차/주차료'),
            ('지출', '금융/주거', '주택담보대출'), ('지출', '금융/주거', '관리비/공과금'), ('지출', '금융/주거', '보험료'), ('지출', '금융/주거', '카드대금'), ('지출', '금융/주거', '대출이자'),
            ('지출', '생활', '생필품'), ('지출', '생활', '통신비/인터넷'), ('지출', '생활', '정기구독료'),
            ('지출', '쇼핑', '의류/잡화'), ('지출', '쇼핑', '온라인쇼핑'), ('지출', '쇼핑', '가전/가구'),
            ('지출', '의료', '병원진료'), ('지출', '의료', '약국'), ('지출', '의료', '동물병원'),
            ('지출', '교육', '학원비'), ('지출', '교육', '도서/문구'),
            ('지출', '문화/여가', '영화/공연'), ('지출', '문화/여가', '여행/숙박'), ('지출', '문화/여가', '운동/레저'),
            ('지출', '경조/기부', '기부금/후원'), ('지출', '경조/기부', '경조사비'), ('지출', '기타', '기타지출')
        ]
        cur.executemany("INSERT OR IGNORE INTO category_hierarchy (type, category, sub_category) VALUES (?, ?, ?)", base_hierarchy)

    # 기본 고정 지출/수입
    cur.execute("SELECT COUNT(*) FROM fixed_items")
    if cur.fetchone()[0] == 0:
        base_fixed = [
            ('수입', '본인 급여', 4800000, '-', '급여', '본인급여'),
            ('수입', '배우자 급여', 1200000, '-', '급여', '배우자급여'),
            ('지출', '주택담보대출', 1100000, '자동이체', '금융/주거', '주택담보대출'),
            ('지출', '관리비/공과금', 280000, '자동이체', '금융/주거', '관리비/공과금'),
            ('지출', '보험료(통합)', 320000, '카드납부', '금융/주거', '보험료'),
            ('지출', '통신비/인터넷', 150000, '자동이체', '생활', '통신비/인터넷'),
            ('지출', '정기구독료', 45000, '카드결제', '생활', '정기구독료')
        ]
        cur.executemany("INSERT INTO fixed_items (type, name, amount, payment_method, category, sub_category) VALUES (?, ?, ?, ?, ?, ?)", base_fixed)

    # 기본 자동 분류 규칙 주입 (소분류 매핑 포함)
    cur.execute("SELECT COUNT(*) FROM auto_rules")
    if cur.fetchone()[0] == 0:
        base_rules = [
            ('수입', '급여', '본인급여', '천안논산고속도로'), ('수입', '급여', '본인급여', '급여'), ('수입', '급여', '본인급여', '월급'), ('수입', '급여', '상여금/성과급', '상여'), ('수입', '급여', '상여금/성과급', '성과급'),
            ('수입', '금융수입', '이자수익', '이자'), ('수입', '금융수입', '배당금', '배당'),
            ('수입', '기타수입', '환급금/공제', '환급'), ('수입', '기타수입', '중고판매', '중고'),
            ('지출', '경조/기부', '기부금/후원', '홀트'), ('지출', '경조/기부', '기부금/후원', '국경없는의사회'), ('지출', '경조/기부', '기부금/후원', '유니세프'), ('지출', '경조/기부', '기부금/후원', '후원'),
            ('지출', '금융/주거', '카드대금', '국민카드'), ('지출', '금융/주거', '카드대금', '신한카드'), ('지출', '금융/주거', '카드대금', '삼성카드'), ('지출', '금융/주거', '카드대금', '현대카드'),
            ('지출', '금융/주거', '보험료', '보험'), ('지출', '금융/주거', '보험료', '생명'), ('지출', '금융/주거', '보험료', '화재'), ('지출', '금융/주거', '대출이자', '대출이자'),
            ('지출', '식비', '식자재/마트', '마트'), ('지출', '식비', '식자재/마트', '하나로'), ('지출', '식비', '식자재/마트', '농협'), ('지출', '식비', '식자재/마트', '이마트'), ('지출', '식비', '식자재/마트', '홈플러스'), ('지출', '식비', '식자재/마트', '파머스'),
            ('지출', '외식', '카페/디저트', '카페'), ('지출', '외식', '카페/디저트', '이디야'), ('지출', '외식', '카페/디저트', '스타벅스'), ('지출', '외식', '카페/디저트', '커피'), ('지출', '외식', '카페/디저트', '회란'), ('지출', '외식', '카페/디저트', '디저트'),
            ('지출', '외식', '음식점/외식', '식당'), ('지출', '외식', '음식점/외식', '음식점'), ('지출', '외식', '음식점/외식', '휴게소'), ('지출', '외식', '음식점/외식', '치킨'),
            ('지출', '교통', '주유비', '주유소'), ('지출', '교통', '주유비', '오일'), ('지출', '교통', '통행료/하이패스', '하이패스'), ('지출', '교통', '통행료/하이패스', '통행료'), ('지출', '교통', '대중교통', '코레일'), ('지출', '교통', '대중교통', 'srt'), ('지출', '교통', '택시비', '택시'),
            ('지출', '차량', '차량정비/부품', '정비'), ('지출', '차량', '차량정비/부품', '카센터'), ('지출', '차량', '세차/주차료', '세차'), ('지출', '차량', '세차/주차료', '주차'),
            ('지출', '의료', '병원진료', '병원'), ('지출', '의료', '약국', '약국'), ('지출', '의료', '병원진료', '의원'), ('지출', '의료', '병원진료', '치과'), ('지출', '의료', '동물병원', '동물병원'),
            ('지출', '교육', '학원비', '학원'), ('지출', '교육', '도서/문구', '서점'), ('지출', '교육', '도서/문구', '도서'),
            ('지출', '쇼핑', '생필품', '다이소'), ('지출', '쇼핑', '온라인쇼핑', '쿠팡'), ('지출', '쇼핑', '온라인쇼핑', '네이버페이'),
            ('지출', '생활', '관리비/공과금', '관리비'), ('지출', '생활', '관리비/공과금', '도시가스'), ('지출', '생활', '관리비/공과금', '전기요금'), ('지출', '생활', '통신비/인터넷', '통신'),
            ('지출', '문화/여가', '영화/공연', '영화'), ('지출', '문화/여가', '영화/공연', 'cgv'), ('지출', '문화/여가', '여행/숙박', '호텔'), ('지출', '문화/여가', '운동/레저', '골프'),
            ('지출', '경조/기부', '경조사비', '축의'), ('지출', '경조/기부', '경조사비', '부의')
        ]
        cur.executemany("INSERT OR IGNORE INTO auto_rules (rule_type, category, sub_category, keyword) VALUES (?, ?, ?, ?)", base_rules)

    conn.commit()
    conn.close()

init_db()

# -------------------------------------------------------------
# 3. 비밀번호 관리 및 로그인 게이트웨이
# -------------------------------------------------------------
def get_stored_password():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key='app_password'")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "1234"

def update_stored_password(new_pw):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET value=? WHERE key='app_password'", (new_pw,))
    conn.commit()
    conn.close()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def login_screen():
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col_center, _ = st.columns([1, 1.2, 1])
    with col_center:
        st.markdown("### 🔐 스마트 가계부 로그인")
        st.info("안전한 금융 데이터 관리를 위해 접속 비밀번호를 입력해 주세요. (초기 비밀번호: 1234)")
        input_pw = st.text_input("접속 비밀번호", type="password", key="login_pw_input")
        if st.button("로그인", use_container_width=True):
            if input_pw == get_stored_password():
                st.session_state.authenticated = True
                st.success("인증 완료되었습니다.")
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")

if not st.session_state.authenticated:
    login_screen()
    st.stop()

# -------------------------------------------------------------
# 4. 데이터베이스 헬퍼 함수
# -------------------------------------------------------------
def get_categories_hierarchy(r_type=None):
    conn = get_db_connection()
    if r_type:
        df = pd.read_sql("SELECT type, category, sub_category FROM category_hierarchy WHERE type=? ORDER BY category, sub_category", conn, params=(r_type,))
    else:
        df = pd.read_sql("SELECT type, category, sub_category FROM category_hierarchy ORDER BY type, category, sub_category", conn)
    conn.close()
    return df

def get_fixed_items():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM fixed_items", conn)
    conn.close()
    return df

def get_variable_records():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(variable_records)")
    cols = [r[1] for r in cur.fetchall()]
    order_clause = "ORDER BY date DESC, time DESC, id DESC" if "time" in cols else "ORDER BY date DESC, id DESC"
    df = pd.read_sql(f"SELECT * FROM variable_records {order_clause}", conn)
    if "time" not in df.columns: df["time"] = ""
    if "sub_category" not in df.columns: df["sub_category"] = "기타"
    if "memo" not in df.columns: df["memo"] = ""
    if "source" not in df.columns: df["source"] = "수기"
    conn.close()
    return df

def get_auto_rules():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM auto_rules ORDER BY rule_type, category, sub_category, keyword", conn)
    conn.close()
    return df

def auto_classify_kb_record(sender_receiver, memo, r_type, summary_field):
    text = f"{str(sender_receiver)} {str(memo)} {str(summary_field)}".lower()
    rules_df = get_auto_rules()
    
    filtered_rules = rules_df[rules_df['rule_type'] == r_type]
    for _, rule in filtered_rules.iterrows():
        kw = str(rule['keyword']).lower().strip()
        if kw and kw in text:
            return rule['category'], rule['sub_category']
            
    default_cat = '기타수입' if r_type == '수입' else '기타'
    return default_cat, '기타'

def calculate_monthly_summary():
    df_fix = get_fixed_items()
    df_var = get_variable_records()
    
    tot_fixed_inc = df_fix[df_fix['type'] == '수입']['amount'].sum() if not df_fix.empty else 0
    tot_fixed_exp = df_fix[df_fix['type'] == '지출']['amount'].sum() if not df_fix.empty else 0
    
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

# 2계층 피벗 생성 함수 (대분류-소분류)
def generate_detailed_pivot(r_type='지출'):
    df_var = get_variable_records()
    filtered_df = df_var[df_var['type'] == r_type] if not df_var.empty else pd.DataFrame()
    
    if filtered_df.empty:
        return pd.DataFrame(columns=['대분류', '소분류'] + [f"{i}월" for i in range(1, 13)] + ['연간 합계'])
    
    pivot = filtered_df.pivot_table(
        index=['category', 'sub_category'], 
        columns='month', 
        values='amount', 
        aggfunc='sum', 
        fill_value=0
    )
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = 0
    pivot = pivot[[m for m in range(1, 13)]]
    pivot.columns = [f"{m}월" for m in range(1, 13)]
    pivot['연간 합계'] = pivot.sum(axis=1)
    pivot = pivot.sort_values(by='연간 합계', ascending=False).reset_index()
    pivot = pivot.rename(columns={'category': '대분류', 'sub_category': '소분류'})
    return pivot

# -------------------------------------------------------------
# 5. 사이드바 메뉴 및 백업
# -------------------------------------------------------------
st.sidebar.title("📌 가계부 시스템")
menu = st.sidebar.radio(
    "메뉴 선택",
    [
        "연간 통합 대시보드", 
        "월별 수입/지출 내역 관리", 
        "📊 대/소분류 심층 통계 분석", 
        "🏦 KB 거래내역 엑셀 연동", 
        "⚙️ 지능형 자동분류 규칙 관리", 
        "고정 수입/지출 관리", 
        "🏷️ 대/소분류 체계 설정",
        "🔒 비밀번호 변경"
    ]
)

if st.sidebar.button("🚪 로그아웃"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💾 데이터 엑셀 내보내기")
df_summary_export = calculate_monthly_summary()
df_var_all = get_variable_records()
df_fix_all = get_fixed_items()
df_exp_pivot = generate_detailed_pivot('지출')
df_inc_pivot = generate_detailed_pivot('수입')
df_rules_export = get_auto_rules()
df_hier_export = get_categories_hierarchy()

output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df_summary_export.to_excel(writer, sheet_name='연간수지요약', index=False)
    df_exp_pivot.to_excel(writer, sheet_name='지출_대소분류_월별통계', index=False)
    df_inc_pivot.to_excel(writer, sheet_name='수입_대소분류_월별통계', index=False)
    if not df_var_all.empty:
        df_var_all.to_excel(writer, sheet_name='거래내역전체', index=False)
    df_fix_all.to_excel(writer, sheet_name='고정항목설정', index=False)
    df_rules_export.to_excel(writer, sheet_name='자동분류_키워드규칙', index=False)
    df_hier_export.to_excel(writer, sheet_name='대소분류체계목록', index=False)

st.sidebar.download_button(
    label="현재 가계부 엑셀 다운로드",
    data=output.getvalue(),
    file_name="스마트가계부_연간_통합분석대장.xlsx",
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
            fig_pie2 = px.pie(cat_sum, names="category", values="amount", title="대분류별 지출 비중", hole=0.45)
            st.plotly_chart(fig_pie2, use_container_width=True)
        else:
            st.info("등록된 지출 내역이 없습니다.")
            
    st.subheader("📑 월별 상세 수지 분석표")
    st.dataframe(df_summary.style.format({
        "총 수입": "{:,}원", "총 지출": "{:,}원", "고정 지출": "{:,}원",
        "변동 지출": "{:,}원", "당월 순저축": "{:,}원", "누적 순저축": "{:,}원", "저축률(%)": "{:.2f}%"
    }), use_container_width=True)

# -------------------------------------------------------------
# 메뉴 2: 월별 수입/지출 내역 관리 (대분류-소분류 연동)
# -------------------------------------------------------------
elif menu == "월별 수입/지출 내역 관리":
    selected_month = st.sidebar.selectbox("조회/관리할 월 선택", [f"{i}월" for i in range(1, 13)])
    month_int = int(selected_month.replace("월", ""))
    
    st.title(f"🗓️ {selected_month} 가계부 내역 관리")
    
    df_fix = get_fixed_items()
    tot_fixed_inc = df_fix[df_fix['type'] == '수입']['amount'].sum() if not df_fix.empty else 0
    tot_fixed_exp = df_fix[df_fix['type'] == '지출']['amount'].sum() if not df_fix.empty else 0
    
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
    
    # 1) 수정 모드
    if 'editing_record_id' not in st.session_state:
        st.session_state.editing_record_id = None

    if st.session_state.editing_record_id is not None:
        edit_row = all_recs[all_recs["id"] == st.session_state.editing_record_id]
        if not edit_row.empty:
            edit_item = edit_row.iloc[0]
            st.warning(f"✏️ [내역 수정] 항목 ID #{edit_item['id']} ({edit_item['name']}) 수정 중입니다.")
            
            with st.form("edit_record_form"):
                col_type, col_date, col_name, col_amt = st.columns([1, 1.2, 2.5, 1.8])
                new_type = col_type.selectbox("구분", ["지출", "수입"], index=0 if edit_item["type"] == "지출" else 1)
                new_date = col_date.text_input("일자 (YYYY.MM.DD 또는 MM-DD)", edit_item["date"])
                new_name = col_name.text_input("항목명", edit_item["name"])
                new_amt = col_amt.number_input("금액 (원)", min_value=0, value=int(edit_item["amount"]), step=1000)
                
                col_c1, col_c2 = st.columns(2)
                type_hier = get_categories_hierarchy(new_type)
                avail_cats = sorted(type_hier['category'].unique().tolist())
                cur_cat_idx = avail_cats.index(edit_item['category']) if edit_item['category'] in avail_cats else 0
                new_cat = col_c1.selectbox("대분류", avail_cats, index=cur_cat_idx)
                
                avail_subs = sorted(type_hier[type_hier['category'] == new_cat]['sub_category'].tolist())
                if not avail_subs: avail_subs = ['기타']
                cur_sub_idx = avail_subs.index(edit_item['sub_category']) if edit_item['sub_category'] in avail_subs else 0
                new_sub = col_c2.selectbox("소분류", avail_subs, index=cur_sub_idx)
                
                b_save, b_cancel = st.columns(2)
                if b_save.form_submit_button("수정 내용 저장", use_container_width=True):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("""
                    UPDATE variable_records 
                    SET type=?, date=?, name=?, amount=?, category=?, sub_category=? 
                    WHERE id=?
                    """, (new_type, new_date, new_name, new_amt, new_cat, new_sub, int(edit_item['id'])))
                    conn.commit()
                    conn.close()
                    st.session_state.editing_record_id = None
                    st.success("내역 수정 완료")
                    st.rerun()
                if b_cancel.form_submit_button("수정 취소", use_container_width=True):
                    st.session_state.editing_record_id = None
                    st.rerun()

    # 2) 신규 내역 등록 폼 (동적 대/소분류 드롭다운)
    st.subheader(f"➕ {selected_month} 새로운 내역 직접 추가")
    c_type, c_cat, c_sub = st.columns(3)
    rec_type = c_type.selectbox("수지 구분", ["지출", "수입"], key="add_rec_type")
    
    hier_df = get_categories_hierarchy(rec_type)
    cat_list = sorted(hier_df['category'].unique().tolist())
    rec_cat = c_cat.selectbox(f"{rec_type} 대분류", cat_list, key="add_rec_cat")
    
    sub_list = sorted(hier_df[hier_df['category'] == rec_cat]['sub_category'].tolist())
    if not sub_list: sub_list = ['기타']
    rec_sub = c_sub.selectbox(f"{rec_cat} 소분류", sub_list, key="add_rec_sub")
    
    with st.form("add_record_form", clear_on_submit=True):
        col_date, col_name, col_amt, col_btn = st.columns([1.2, 2.5, 2, 1.2])
        rec_date = col_date.text_input("일자 (MM-DD)", f"{month_int:02d}-01")
        rec_name = col_name.text_input("항목명/거래처", placeholder="예: 이마트 장보기, 스타벅스")
        rec_amt = col_amt.number_input("금액 (원)", min_value=0, step=1000)
        btn_add = col_btn.form_submit_button("내역 등록", use_container_width=True)
        
        if btn_add:
            if rec_name and rec_amt > 0:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                INSERT INTO variable_records (month, type, date, time, name, amount, category, sub_category, memo, source) 
                VALUES (?, ?, ?, '', ?, ?, ?, ?, '', '수기')
                """, (month_int, rec_type, rec_date, rec_name, rec_amt, rec_cat, rec_sub))
                conn.commit()
                conn.close()
                st.success(f"'{rec_name}' ({rec_amt:,}원) 등록 완료 [{rec_cat} > {rec_sub}]")
                st.rerun()
            else:
                st.error("항목명과 유효한 금액을 입력해 주세요.")

    # 3) 등록 내역 목록 테이블
    st.subheader(f"📝 {selected_month} 등록 내역 목록 (총 {len(m_records)}건)")
    if not m_records.empty:
        h1, h2, h3, h4, h5, h6, h7, h8, h9 = st.columns([1.2, 0.8, 2.2, 1.6, 1.3, 1.3, 0.8, 0.6, 0.6])
        h1.markdown("**일자**"); h2.markdown("**구분**"); h3.markdown("**거래처/항목**"); h4.markdown("**금액**")
        h5.markdown("**대분류**"); h6.markdown("**소분류**"); h7.markdown("**출처**"); h8.markdown("**수정**"); h9.markdown("**삭제**")
        
        for idx, row in m_records.iterrows():
            c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([1.2, 0.8, 2.2, 1.6, 1.3, 1.3, 0.8, 0.6, 0.6])
            c1.text(f"{row['date']}")
            c2.markdown(f"<span style='color:{'#2962FF' if row['type']=='수입' else '#FF5252'}; font-weight:bold;'>{row['type']}</span>", unsafe_allow_html=True)
            c3.text(f"{row['name']}")
            c4.text(f"{row['amount']:,} 원")
            c5.text(f"{row['category']}")
            c6.text(f"{row['sub_category']}")
            c7.caption(f"{row['source']}")
            if c8.button("✏️", key=f"edit_btn_{row['id']}"):
                st.session_state.editing_record_id = row['id']
                st.rerun()
            if c9.button("🗑", key=f"del_rec_{row['id']}"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM variable_records WHERE id=?", (int(row['id']),))
                conn.commit()
                conn.close()
                st.rerun()
    else:
        st.info("해당 월에 등록된 거래 내역이 없습니다.")

# -------------------------------------------------------------
# 메뉴 3: 📊 대/소분류 심층 통계 분석 (지출/수입 세분화 탭)
# -------------------------------------------------------------
elif menu == "📊 대/소분류 심층 통계 분석":
    st.title("📊 대분류 · 소분류 심층 통계 분석")
    st.info("💡 대분류와 소분류로 세분화된 지출 및 수입 분석 시트와 계층형 시각화 차트입니다.")
    
    df_var = get_variable_records()
    
    tab_exp, tab_inc = st.tabs(["💸 지출 - 대/소분류 통계", "💰 수입 - 대/소분류 통계"])
    
    # ------------------ [탭 1: 지출 통계] ------------------
    with tab_exp:
        exp_df = df_var[df_var['type'] == '지출'] if not df_var.empty else pd.DataFrame()
        if exp_df.empty:
            st.warning("등록된 지출 내역이 없습니다.")
        else:
            tot_exp_val = exp_df['amount'].sum()
            top_cat = exp_df.groupby("category")["amount"].sum().idxmax()
            top_sub = exp_df.groupby(["category", "sub_category"])["amount"].sum().idxmax()
            top_sub_amt = exp_df.groupby(["category", "sub_category"])["amount"].sum().max()
            
            k1, k2, k3 = st.columns(3)
            k1.metric("총 변동 지출액", f"{tot_exp_val:,} 원")
            k2.metric("최대 지출 대분류", f"{top_cat}")
            k3.metric("최대 지출 소분류", f"{top_sub[0]} > {top_sub[1]}", delta=f"{top_sub_amt:,}원 ({(top_sub_amt/tot_exp_val*100):.1f}%)")
            
            st.divider()
            
            # 1. 선버스트(Sunburst) 계층형 차트 & 트리맵
            st.subheader("1️⃣ 지출 계층 구조 시각화 (대분류 ➡️ 소분류)")
            c_sb1, c_sb2 = st.columns(2)
            with c_sb1:
                fig_sun = px.sunburst(
                    exp_df, 
                    path=['category', 'sub_category'], 
                    values='amount',
                    title="대분류-소분류 지출 비중 (선버스트 차트)",
                    color='amount',
                    color_continuous_scale='Reds'
                )
                st.plotly_chart(fig_sun, use_container_width=True)
            with c_sb2:
                fig_tree = px.treemap(
                    exp_df, 
                    path=['category', 'sub_category'], 
                    values='amount',
                    title="소분류별 지출 면적 트리맵 (Treemap)",
                    color='amount',
                    color_continuous_scale='YlOrRd'
                )
                st.plotly_chart(fig_tree, use_container_width=True)
                
            # 2. 소분류별 누적 지출 랭킹 (Top 10)
            st.subheader("2️⃣ 소분류별 누적 지출 순위 (Top 10)")
            sub_ranked = exp_df.groupby(["category", "sub_category"])["amount"].sum().reset_index()
            sub_ranked["분류_표시"] = sub_ranked["category"] + " > " + sub_ranked["sub_category"]
            sub_ranked = sub_ranked.sort_values(by="amount", ascending=True).tail(10)
            
            fig_sub_bar = px.bar(
                sub_ranked,
                x="amount",
                y="분류_표시",
                orientation='h',
                text="amount",
                color="amount",
                color_continuous_scale="Purples",
                title="상위 10개 소분류 지출 항목"
            )
            fig_sub_bar.update_traces(texttemplate='%{text:,}원', textposition='outside')
            fig_sub_bar.update_layout(xaxis_title="지출 합계 (원)", yaxis_title="대분류 > 소분류", coloraxis_showscale=False)
            st.plotly_chart(fig_sub_bar, use_container_width=True)

            # 3. 2계층 지출 피벗 테이블 시트
            st.subheader("3️⃣ [지출] 대분류 · 소분류별 월별 상세 집계표")
            exp_pivot = generate_detailed_pivot('지출')
            fmt_exp = {col: "{:,}원" for col in exp_pivot.columns if col not in ['대분류', '소분류']}
            st.dataframe(exp_pivot.style.format(fmt_exp), use_container_width=True)

    # ------------------ [탭 2: 수입 통계] ------------------
    with tab_inc:
        inc_df = df_var[df_var['type'] == '수입'] if not df_var.empty else pd.DataFrame()
        if inc_df.empty:
            st.warning("등록된 수입 내역이 없습니다.")
        else:
            tot_inc_val = inc_df['amount'].sum()
            top_inc_cat = inc_df.groupby("category")["amount"].sum().idxmax()
            top_inc_sub = inc_df.groupby(["category", "sub_category"])["amount"].sum().idxmax()
            top_inc_sub_amt = inc_df.groupby(["category", "sub_category"])["amount"].sum().max()
            
            ik1, ik2, ik3 = st.columns(3)
            ik1.metric("총 변동 수입액", f"{tot_inc_val:,} 원")
            ik2.metric("최대 수입 대분류", f"{top_inc_cat}")
            ik3.metric("최대 수입 소분류", f"{top_inc_sub[0]} > {top_inc_sub[1]}", delta=f"{top_inc_sub_amt:,}원 ({(top_inc_sub_amt/tot_inc_val*100):.1f}%)")
            
            st.divider()
            
            # 수입 계층 차트
            st.subheader("1️⃣ 수입 계층 구조 시각화 (대분류 ➡️ 소분류)")
            ci_1, ci_2 = st.columns(2)
            with ci_1:
                fig_inc_sun = px.sunburst(
                    inc_df, 
                    path=['category', 'sub_category'], 
                    values='amount',
                    title="대분류-소분류 수입 구성 (선버스트 차트)",
                    color='amount',
                    color_continuous_scale='Blues'
                )
                st.plotly_chart(fig_inc_sun, use_container_width=True)
            with ci_2:
                inc_sub_sum = inc_df.groupby(["category", "sub_category"])["amount"].sum().reset_index()
                inc_sub_sum["수입항목"] = inc_sub_sum["category"] + " > " + inc_sub_sum["sub_category"]
                fig_inc_pie = px.pie(
                    inc_sub_sum,
                    names="수입항목",
                    values="amount",
                    title="소분류별 수입 비중 (도넛 차트)",
                    hole=0.45
                )
                st.plotly_chart(fig_inc_pie, use_container_width=True)

            # 2계층 수입 피벗 테이블 시트
            st.subheader("2️⃣ [수입] 대분류 · 소분류별 월별 상세 집계표")
            inc_pivot = generate_detailed_pivot('수입')
            fmt_inc = {col: "{:,}원" for col in inc_pivot.columns if col not in ['대분류', '소분류']}
            st.dataframe(inc_pivot.style.format(fmt_inc), use_container_width=True)

# -------------------------------------------------------------
# 메뉴 4: 🏦 KB 국민은행 거래내역 엑셀 연동
# -------------------------------------------------------------
elif menu == "🏦 KB 거래내역 엑셀 연동":
    st.title("🏦 KB국민은행 거래내역 엑셀 자동 연동")
    st.info("국민은행 인터넷뱅킹에서 다운로드한 '거래내역조회 엑셀 파일'(`.xls` 또는 `.xlsx`)을 업로드하면 지능형 분류 엔진에 따라 대분류 및 소분류까지 자동으로 지정됩니다.")

    uploaded_file = st.file_uploader("KB국민은행 거래내역 엑셀 파일 업로드", type=["xls", "xlsx"])
    
    if uploaded_file is not None:
        try:
            df_kb_raw = pd.read_excel(uploaded_file, skiprows=3)
            if 'Unnamed: 0' in df_kb_raw.columns:
                df_kb_raw.columns = df_kb_raw.iloc[0]
                df_kb_raw = df_kb_raw.iloc[1:].reset_index(drop=True)
                
            df_kb = df_kb_raw[df_kb_raw['거래일시'].notna() & (df_kb_raw['거래일시'] != '합계')].copy()
            st.success(f"파일 파싱 성공: 총 {len(df_kb)}건의 거래 내역을 인식했습니다.")
            
            parsed_rows = []
            for _, r in df_kb.iterrows():
                dt_str = str(r.get('거래일시', '')).strip()
                summary_val = str(r.get('적요', '')).strip()
                partner_val = str(r.get('보낸분/받는분', '')).strip()
                memo_val = str(r.get('송금메모', '')).strip()
                
                w_val = str(r.get('출금액', 0)).replace(',', '').split('.')[0]
                d_val = str(r.get('입금액', 0)).replace(',', '').split('.')[0]
                withdraw_amt = int(w_val) if w_val.isdigit() else 0
                deposit_amt = int(d_val) if d_val.isdigit() else 0
                
                date_part = dt_str.split(' ')[0] if ' ' in dt_str else dt_str
                time_part = dt_str.split(' ')[1] if ' ' in dt_str else ''
                
                try:
                    month_num = int(date_part.split('.')[1])
                except Exception:
                    month_num = 1
                
                if withdraw_amt > 0:
                    rec_type = '지출'
                    amt = withdraw_amt
                elif deposit_amt > 0:
                    rec_type = '수입'
                    amt = deposit_amt
                else:
                    continue
                    
                display_name = partner_val if partner_val and partner_val != 'nan' else summary_val
                # 대분류 및 소분류 자동 매핑
                assigned_cat, assigned_sub = auto_classify_kb_record(partner_val, memo_val, rec_type, summary_val)
                
                parsed_rows.append({
                    "month": month_num,
                    "type": rec_type,
                    "date": date_part,
                    "time": time_part,
                    "name": display_name,
                    "amount": amt,
                    "category": assigned_cat,
                    "sub_category": assigned_sub,
                    "memo": memo_val if memo_val != 'nan' else '',
                    "source": "KB국민"
                })
            
            preview_df = pd.DataFrame(parsed_rows)
            st.subheader("👀 대/소분류 자동 분류 및 분개 미리보기")
            st.dataframe(preview_df[["date", "type", "name", "amount", "category", "sub_category", "memo"]].head(15).style.format({"amount": "{:,}원"}), use_container_width=True)
            
            c_btn1, _ = st.columns([1, 2])
            with c_btn1:
                if st.button("🚀 이 거래내역을 가계부에 일괄 동기화", use_container_width=True):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    
                    existing_df = pd.read_sql("SELECT date, time, name, amount FROM variable_records WHERE source='KB국민'", conn)
                    existing_keys = set(zip(existing_df['date'], existing_df['time'], existing_df['name'], existing_df['amount']))
                    
                    inserted_cnt = 0
                    skipped_cnt = 0
                    
                    for row in parsed_rows:
                        key = (row['date'], row['time'], row['name'], row['amount'])
                        if key in existing_keys:
                            skipped_cnt += 1
                            continue
                        cur.execute("""
                        INSERT INTO variable_records (month, type, date, time, name, amount, category, sub_category, memo, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (row['month'], row['type'], row['date'], row['time'], row['name'], row['amount'], row['category'], row['sub_category'], row['memo'], row['source']))
                        inserted_cnt += 1
                        existing_keys.add(key)
                        
                    conn.commit()
                    conn.close()
                    st.success(f"동기화 완료: 신규 등록 {inserted_cnt}건 (중복 건너뜀 {skipped_cnt}건)")
                    st.balloons()
        except Exception as e:
            st.error(f"파일 처리 중 오류가 발생했습니다: {e}")

# -------------------------------------------------------------
# 메뉴 5: ⚙️ 지능형 자동분류 규칙 관리 (대/소분류 키워드)
# -------------------------------------------------------------
elif menu == "⚙️ 지능형 자동분류 규칙 관리":
    st.title("⚙️ KB 지능형 자동 분류 규칙(키워드) 관리")
    st.info("💡 거래처/적요 키워드를 등록하면, 국민은행 엑셀을 업로드할 때 지정한 [대분류 > 소분류]로 정확하게 자동 분개됩니다.")
    
    rules_df = get_auto_rules()
    col_r_add, col_r_list = st.columns([1, 1.5])
    
    with col_r_add:
        st.subheader("➕ 새 자동분류 키워드 등록")
        r_type = st.selectbox("수지 구분", ["지출", "수입"], key="rule_add_type")
        hier_df = get_categories_hierarchy(r_type)
        cats = sorted(hier_df['category'].unique().tolist())
        r_cat = st.selectbox("매핑할 대분류", cats, key="rule_add_cat")
        subs = sorted(hier_df[hier_df['category'] == r_cat]['sub_category'].tolist())
        if not subs: subs = ['기타']
        r_sub = st.selectbox("매핑할 소분류", subs, key="rule_add_sub")
        
        with st.form("add_rule_form", clear_on_submit=True):
            r_kw = st.text_input("매칭 키워드 (예: 스타벅스, 올리브영, GS25, 파머스)")
            if st.form_submit_button("키워드 규칙 추가", use_container_width=True):
                if r_kw.strip():
                    try:
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("""
                        INSERT INTO auto_rules (rule_type, category, sub_category, keyword) 
                        VALUES (?, ?, ?, ?)
                        """, (r_type, r_cat, r_sub, r_kw.strip().lower()))
                        conn.commit()
                        conn.close()
                        st.success(f"키워드 '{r_kw.strip()}' ➡️ [{r_cat} > {r_sub}] 등록 완료")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.warning("이미 등록되어 있는 키워드입니다.")
                else:
                    st.error("키워드를 입력해 주세요.")
                    
    with col_r_list:
        st.subheader(f"📋 등록된 자동 분류 규칙 (총 {len(rules_df)}개)")
        f_type = st.radio("보기 필터", ["전체", "지출", "수입"], horizontal=True)
        disp_rules = rules_df if f_type == "전체" else rules_df[rules_df['rule_type'] == f_type]
        
        if not disp_rules.empty:
            h1, h2, h3, h4, h5 = st.columns([1, 1.5, 1.5, 2.5, 0.8])
            h1.markdown("**구분**"); h2.markdown("**대분류**"); h3.markdown("**소분류**"); h4.markdown("**매칭 키워드**"); h5.markdown("**삭제**")
            
            for _, r in disp_rules.iterrows():
                c1, c2, c3, c4, c5 = st.columns([1, 1.5, 1.5, 2.5, 0.8])
                c1.text(r['rule_type'])
                c2.text(r['category'])
                c3.text(r['sub_category'])
                c4.markdown(f"`{r['keyword']}`")
                if c5.button("🗑", key=f"del_rule_{r['id']}"):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM auto_rules WHERE id=?", (int(r['id']),))
                    conn.commit()
                    conn.close()
                    st.rerun()
        else:
            st.info("등록된 규칙이 없습니다.")

# -------------------------------------------------------------
# 메뉴 6: 고정 수입/지출 관리
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
                    cur.execute("INSERT INTO fixed_items (type, name, amount, payment_method, category, sub_category) VALUES ('수입', ?, ?, '-', '급여', '본인급여')", (f_inc_name, f_inc_amt))
                    conn.commit()
                    conn.close()
                    st.rerun()
        
        inc_items = df_fix[df_fix['type'] == '수입'] if not df_fix.empty else pd.DataFrame()
        st.markdown(f"**월 고정 수입 합계: `{inc_items['amount'].sum() if not inc_items.empty else 0:,} 원`**")
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
                    cur.execute("INSERT INTO fixed_items (type, name, amount, payment_method, category, sub_category) VALUES ('지출', ?, ?, ?, '금융/주거', '기타')", (f_exp_name, f_exp_amt, f_exp_pay))
                    conn.commit()
                    conn.close()
                    st.rerun()
        
        exp_items = df_fix[df_fix['type'] == '지출'] if not df_fix.empty else pd.DataFrame()
        st.markdown(f"**월 고정 지출 합계: `{exp_items['amount'].sum() if not exp_items.empty else 0:,} 원`**")
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
# 메뉴 7: 🏷️ 대/소분류 체계 설정
# -------------------------------------------------------------
elif menu == "🏷️ 대/소분류 체계 설정":
    st.title("🏷️ 대분류 및 소분류 체계 관리")
    st.info("💡 수입 및 지출에 사용할 대분류와 소분류 항목을 자유롭게 추가하거나 삭제할 수 있습니다.")
    
    col_add_hier, col_view_hier = st.columns([1, 1.5])
    
    with col_add_hier:
        st.subheader("➕ 새 소분류/대분류 추가")
        with st.form("add_hier_form", clear_on_submit=True):
            h_type = st.selectbox("수지 구분", ["지출", "수입"])
            existing_hier = get_categories_hierarchy(h_type)
            existing_cats = sorted(existing_hier['category'].unique().tolist())
            
            sel_cat_mode = st.radio("대분류 선택 방식", ["기존 대분류 선택", "새 대분류 직접 입력"], horizontal=True)
            if sel_cat_mode == "기존 대분류 선택":
                h_cat = st.selectbox("대분류 선택", existing_cats)
            else:
                h_cat = st.text_input("새 대분류명 입력")
                
            h_sub = st.text_input("추가할 소분류명 입력 (예: 야식/배달, 캠핑용품 등)")
            
            if st.form_submit_button("분류 체계에 추가", use_container_width=True):
                if h_cat.strip() and h_sub.strip():
                    try:
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("""
                        INSERT INTO category_hierarchy (type, category, sub_category) 
                        VALUES (?, ?, ?)
                        """, (h_type, h_cat.strip(), h_sub.strip()))
                        conn.commit()
                        conn.close()
                        st.success(f"[{h_type}] {h_cat.strip()} ➡️ {h_sub.strip()} 등록 성공!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.warning("이미 존재하는 대분류-소분류 조합입니다.")
                else:
                    st.error("대분류와 소분류명을 모두 입력해 주세요.")
                    
    with col_view_hier:
        st.subheader("📋 현재 등록된 대분류/소분류 목록")
        v_type = st.radio("조회할 구분", ["지출", "수입"], horizontal=True, key="view_hier_type")
        v_df = get_categories_hierarchy(v_type)
        
        for cat_name, group in v_df.groupby("category"):
            with st.expander(f"📁 {cat_name} (소분류 {len(group)}개)"):
                for _, r in group.iterrows():
                    c_txt, c_del = st.columns([3, 1])
                    c_txt.text(f"  └ {r['sub_category']}")
                    if c_del.button("삭제", key=f"del_hier_{v_type}_{cat_name}_{r['sub_category']}"):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("DELETE FROM category_hierarchy WHERE type=? AND category=? AND sub_category=?", 
                                    (v_type, cat_name, r['sub_category']))
                        conn.commit()
                        conn.close()
                        st.rerun()

# -------------------------------------------------------------
# 메뉴 8: 🔒 비밀번호 변경
# -------------------------------------------------------------
elif menu == "🔒 비밀번호 변경":
    st.title("🔒 접속 비밀번호 변경")
    st.info("가계부 접속 비밀번호를 안전하게 변경할 수 있습니다. 변경된 비밀번호는 데이터베이스에 영구 저장됩니다.")
    
    col_pw1, _ = st.columns([1.2, 1])
    with col_pw1:
        with st.form("change_password_form", clear_on_submit=True):
            current_pw_input = st.text_input("현재 비밀번호", type="password")
            new_pw_input = st.text_input("새로운 비밀번호", type="password")
            confirm_pw_input = st.text_input("새로운 비밀번호 확인", type="password")
            
            btn_pw_submit = st.form_submit_button("비밀번호 변경하기", use_container_width=True)
            
            if btn_pw_submit:
                real_pw = get_stored_password()
                if current_pw_input != real_pw:
                    st.error("현재 비밀번호가 일치하지 않습니다.")
                elif not new_pw_input:
                    st.error("새로운 비밀번호를 입력해 주세요.")
                elif new_pw_input != confirm_pw_input:
                    st.error("새로운 비밀번호와 비밀번호 확인이 일치하지 않습니다.")
                else:
                    update_stored_password(new_pw_input)
                    st.success("비밀번호가 성공적으로 변경되었습니다! 다음 접속 시 새 비밀번호로 로그인해 주세요.")
                    st.balloons()
