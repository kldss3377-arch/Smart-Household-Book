import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import io
import re

# -------------------------------------------------------------
# 1. 페이지 설정 & 글래스모피즘 / 아이소메트릭 테마 스타일
# -------------------------------------------------------------
st.set_page_config(
    page_title="스마트 가계부 & 3단계 다차원 자산분석 시스템",
    page_icon="💎",
    layout="wide"
)

st.markdown("""
<style>
    .main {
        background: linear-gradient(135deg, #0b1120 0%, #1e293b 100%);
        color: #f8fafc;
    }
    .iso-card {
        background: rgba(30, 41, 59, 0.75);
        backdrop-filter: blur(14px);
        -webkit-backdrop-filter: blur(14px);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 18px;
        padding: 22px 24px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
        margin-bottom: 16px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .iso-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 16px 32px rgba(0, 0, 0, 0.6);
    }
    .iso-label {
        font-size: 0.95rem;
        font-weight: 600;
        color: #94a3b8;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .iso-value {
        font-size: 1.85rem;
        font-weight: 800;
        letter-spacing: -0.5px;
    }
    .val-blue { color: #38bdf8; text-shadow: 0 0 15px rgba(56, 189, 248, 0.35); }
    .val-red { color: #f87171; text-shadow: 0 0 15px rgba(248, 113, 113, 0.35); }
    .val-green { color: #4ade80; text-shadow: 0 0 15px rgba(74, 222, 128, 0.35); }
    .val-amber { color: #fbbf24; text-shadow: 0 0 15px rgba(251, 191, 36, 0.35); }
    
    /* 붉은색 강조 경고 박스 */
    .danger-box {
        background: rgba(239, 68, 68, 0.15);
        border: 2px solid #ef4444;
        border-radius: 14px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

DB_PATH = "household.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------------------------------------------
# 2. SQLite DB 초기화, 자동 마이그레이션 및 연도 데이터 자동 복구
# -------------------------------------------------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    cur.execute("SELECT value FROM settings WHERE key='app_password'")
    if cur.fetchone() is None:
        cur.execute("INSERT INTO settings (key, value) VALUES ('app_password', '1234')")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS category_hierarchy_3tier (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        cat_large TEXT,
        cat_mid TEXT,
        cat_small TEXT,
        UNIQUE(type, cat_large, cat_mid, cat_small)
    )""")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS variable_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER,
        month INTEGER,
        type TEXT,
        date TEXT,
        time TEXT DEFAULT '',
        name TEXT,
        amount INTEGER,
        cat_large TEXT DEFAULT '기타',
        cat_mid TEXT DEFAULT '기타',
        cat_small TEXT DEFAULT '기타',
        memo TEXT DEFAULT '',
        source TEXT DEFAULT '수기'
    )""")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auto_rules_3tier (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT DEFAULT '지출',
        cat_large TEXT,
        cat_mid TEXT,
        cat_small TEXT,
        keyword TEXT UNIQUE
    )""")
    conn.commit()

    cur.execute("PRAGMA table_info(variable_records)")
    v_cols = [row[1] for row in cur.fetchall()]
    if "year" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN year INTEGER")
    if "cat_large" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN cat_large TEXT DEFAULT '기타'")
    if "cat_mid" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN cat_mid TEXT DEFAULT '기타'")
    if "cat_small" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN cat_small TEXT DEFAULT '기타'")
    if "time" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN time TEXT DEFAULT ''")
    if "memo" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN memo TEXT DEFAULT ''")
    if "source" not in v_cols: cur.execute("ALTER TABLE variable_records ADD COLUMN source TEXT DEFAULT '수기'")
    conn.commit()

    # DB 내 기존 레코드의 잘못된 년도/월 일괄 복구
    cur.execute("""
    UPDATE variable_records 
    SET year = CAST(SUBSTR(REPLACE(date, '-', '.'), 1, 4) AS INTEGER),
        month = CAST(SUBSTR(REPLACE(date, '-', '.'), 6, 2) AS INTEGER)
    WHERE date LIKE '202%' AND LENGTH(date) >= 7
    """)
    conn.commit()

    # 기본 3단계 카테고리 시드 데이터 주입
    cur.execute("SELECT COUNT(*) FROM category_hierarchy_3tier")
    if cur.fetchone()[0] == 0:
        base_3tier = [
            ('수입', '근로소득', '정기급여', '본인급여'), ('수입', '근로소득', '정기급여', '배우자급여'),
            ('수입', '근로소득', '성과/상여', '명절상여'), ('수입', '근로소득', '성과/상여', '회사성과급'),
            ('수입', '금융/투자', '이자수익', '예적금이자'), ('수입', '금융/투자', '배당수익', '국내외배당'),
            ('수입', '기타소득', '부수입', '중고거래'), ('수입', '기타소득', '부수입', '원고료/자문료'),
            ('수입', '기타소득', '환급/지원', '연말정산환급'), ('수입', '기타소득', '환급/지원', '정부지원금'),
            ('지출', '생활필수', '식비/장보기', '마트/농협'), ('지출', '생활필수', '식비/장보기', '정육/청과'), ('지출', '생활필수', '식비/장보기', '간식/생필품'),
            ('지출', '생활필수', '주거/통신', '관리비/공과금'), ('지출', '생활필수', '주거/통신', '통신비/인터넷'), ('지출', '생활필수', '주거/통신', '도시가스/난방'),
            ('지출', '생활필수', '보건/의료', '병원진료'), ('지출', '생활필수', '보건/의료', '약국처방'), ('지출', '생활필수', '보건/의료', '동물병원'),
            ('지출', '외식/여가', '외식/식도락', '음식점/식당'), ('지출', '외식/여가', '외식/식도락', '카페/디저트'), ('지출', '외식/여가', '외식/식도락', '배달음식'),
            ('지출', '외식/여가', '문화/여행', '영화/공연'), ('지출', '외식/여가', '문화/여행', '여행/숙박'), ('지출', '외식/여가', '문화/여행', '운동/피트니스'),
            ('지출', '차량/교통', '차량유지', '주유비'), ('지출', '차량/교통', '차량유지', '정비/소모품'), ('지출', '차량/교통', '차량유지', '세차/주차료'),
            ('지출', '차량/교통', '교통이용', '통행료/하이패스'), ('지출', '차량/교통', '교통이용', '대중교통/기차'), ('지출', '차량/교통', '교통이용', '택시비'),
            ('지출', '금융/안전망', '대출/상환', '주택담보대출'), ('지출', '금융/안전망', '대출/상환', '신용대출이자'),
            ('지출', '금융/안전망', '보험료', '실손/통합보험'), ('지출', '금융/안전망', '보험료', '자동차보험'),
            ('지출', '금융/안전망', '카드대금', '신용카드일시불'),
            ('지출', '쇼핑/잡화', '의류/미용', '의류/신발'), ('지출', '쇼핑/잡화', '온라인쇼핑', '쿠팡/네이버페이'),
            ('지출', '사회/기부', '경조사', '축의/부의금'), ('지출', '사회/기부', '기부/후원', '정기후원금'),
            ('지출', '기타', '예비비', '기타지출')
        ]
        cur.executemany("INSERT OR IGNORE INTO category_hierarchy_3tier (type, cat_large, cat_mid, cat_small) VALUES (?, ?, ?, ?)", base_3tier)

    cur.execute("SELECT COUNT(*) FROM auto_rules_3tier")
    if cur.fetchone()[0] == 0:
        base_rules = [
            ('수입', '근로소득', '정기급여', '본인급여', '천안논산고속도로'),
            ('수입', '근로소득', '정기급여', '본인급여', '급여'),
            ('수입', '근로소득', '정기급여', '본인급여', '월급'),
            ('수입', '근로소득', '성과/상여', '회사성과급', '성과급'),
            ('수입', '근로소득', '성과/상여', '명절상여', '상여'),
            ('수입', '금융/투자', '이자수익', '예적금이자', '이자'),
            ('수입', '금융/투자', '배당수익', '국내외배당', '배당'),
            ('수입', '기타소득', '환급/지원', '연말정산환급', '환급'),
            ('수입', '기타소득', '부수입', '중고거래', '중고'),
            ('지출', '사회/기부', '기부/후원', '정기후원금', '홀트'),
            ('지출', '사회/기부', '기부/후원', '정기후원금', '국경없는의사회'),
            ('지출', '사회/기부', '기부/후원', '정기후원금', '유니세프'),
            ('지출', '금융/안전망', '카드대금', '신용카드일시불', '국민카드'),
            ('지출', '금융/안전망', '카드대금', '신용카드일시불', '신한카드'),
            ('지출', '금융/안전망', '카드대금', '신용카드일시불', '삼성카드'),
            ('지출', '금융/안전망', '카드대금', '신용카드일시불', '현대카드'),
            ('지출', '금융/안전망', '보험료', '실손/통합보험', '보험'),
            ('지출', '금융/안전망', '보험료', '실손/통합보험', '생명'),
            ('지출', '금융/안전망', '보험료', '실손/통합보험', '화재'),
            ('지출', '금융/안전망', '대출/상환', '신용대출이자', '대출이자'),
            ('지출', '생활필수', '식비/장보기', '마트/농협', '마트'),
            ('지출', '생활필수', '식비/장보기', '마트/농협', '하나로'),
            ('지출', '생활필수', '식비/장보기', '마트/농협', '농협'),
            ('지출', '생활필수', '식비/장보기', '마트/농협', '이마트'),
            ('지출', '생활필수', '식비/장보기', '마트/농협', '파머스'),
            ('지출', '외식/여가', '외식/식도락', '카페/디저트', '카페'),
            ('지출', '외식/여가', '외식/식도락', '카페/디저트', '이디야'),
            ('지출', '외식/여가', '외식/식도락', '카페/디저트', '스타벅스'),
            ('지출', '외식/여가', '외식/식도락', '카페/디저트', '회란'),
            ('지출', '외식/여가', '외식/식도락', '음식점/식당', '식당'),
            ('지출', '외식/여가', '외식/식도락', '음식점/식당', '휴게소'),
            ('지출', '차량/교통', '차량유지', '주유비', '주유소'),
            ('지출', '차량/교통', '차량유지', '주유비', '오일'),
            ('지출', '차량/교통', '교통이용', '통행료/하이패스', '하이패스'),
            ('지출', '차량/교통', '교통이용', '통행료/하이패스', '통행료'),
            ('지출', '차량/교통', '교통이용', '대중교통/기차', '코레일'),
            ('지출', '차량/교통', '교통이용', '대중교통/기차', 'srt'),
            ('지출', '차량/교통', '교통이용', '택시비', '택시'),
            ('지출', '차량/교통', '차량유지', '정비/소모품', '정비'),
            ('지출', '차량/교통', '차량유지', '세차/주차료', '세차'),
            ('지출', '생활필수', '보건/의료', '병원진료', '병원'),
            ('지출', '생활필수', '보건/의료', '약국처방', '약국'),
            ('지출', '생활필수', '보건/의료', '동물병원', '동물병원'),
            ('지출', '쇼핑/잡화', '온라인쇼핑', '쿠팡/네이버페이', '쿠팡'),
            ('지출', '쇼핑/잡화', '온라인쇼핑', '쿠팡/네이버페이', '네이버페이'),
            ('지출', '쇼핑/잡화', '의류/미용', '간식/생필품', '다이소')
        ]
        cur.executemany("INSERT OR IGNORE INTO auto_rules_3tier (rule_type, cat_large, cat_mid, cat_small, keyword) VALUES (?, ?, ?, ?, ?)", base_rules)

    conn.commit()
    conn.close()

init_db()

# -------------------------------------------------------------
# 3. 비밀번호 관리 및 인증 게이트웨이
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
        st.markdown("""
        <div class="iso-card" style="text-align: center;">
            <h2 style="color: #38bdf8; margin-bottom: 8px;">💎 스마트 가계부 로그인</h2>
            <p style="color: #94a3b8; font-size: 0.95rem;">안전한 금융 데이터 관리를 위해 접속 비밀번호를 입력해 주세요.</p>
        </div>
        """, unsafe_allow_html=True)
        input_pw = st.text_input("접속 비밀번호 (초기값: 1234)", type="password", key="login_pw_input")
        if st.button("시스템 접속", use_container_width=True):
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
# 4. 데이터 조회 및 계산 함수
# -------------------------------------------------------------
def get_3tier_hierarchy(r_type=None):
    conn = get_db_connection()
    if r_type:
        df = pd.read_sql("SELECT type, cat_large, cat_mid, cat_small FROM category_hierarchy_3tier WHERE type=? ORDER BY cat_large, cat_mid, cat_small", conn, params=(r_type,))
    else:
        df = pd.read_sql("SELECT type, cat_large, cat_mid, cat_small FROM category_hierarchy_3tier ORDER BY type, cat_large, cat_mid, cat_small", conn)
    conn.close()
    return df

def get_variable_records(selected_year=None):
    conn = get_db_connection()
    if selected_year and selected_year != "전체":
        clean_y = int(str(selected_year).replace("년", ""))
        df = pd.read_sql("SELECT * FROM variable_records WHERE year=? ORDER BY date DESC, time DESC, id DESC", conn, params=(clean_y,))
    else:
        df = pd.read_sql("SELECT * FROM variable_records ORDER BY year DESC, date DESC, time DESC, id DESC", conn)
    conn.close()
    return df

def get_auto_rules_3tier():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM auto_rules_3tier ORDER BY rule_type, cat_large, cat_mid, cat_small, keyword", conn)
    conn.close()
    return df

def auto_classify_3tier(sender_receiver, memo, r_type, summary_field):
    text = f"{str(sender_receiver)} {str(memo)} {str(summary_field)}".lower()
    rules_df = get_auto_rules_3tier()
    
    filtered = rules_df[rules_df['rule_type'] == r_type]
    for _, rule in filtered.iterrows():
        kw = str(rule['keyword']).lower().strip()
        if kw and kw in text:
            return rule['cat_large'], rule['cat_mid'], rule['cat_small']
            
    if r_type == '수입':
        return '기타소득', '기타수입', '기타'
    return '기타', '예비비', '기타지출'

def calculate_summary(year_filter):
    df_var = get_variable_records(year_filter)
    
    if year_filter == "전체":
        summary = []
        years_list = list(range(2020, 2027))
        accumulated_savings = 0
        for y in years_list:
            y_df = df_var[df_var['year'] == y] if not df_var.empty else pd.DataFrame()
            tot_inc = y_df[y_df['type'] == '수입']['amount'].sum() if not y_df.empty else 0
            tot_exp = y_df[y_df['type'] == '지출']['amount'].sum() if not y_df.empty else 0
            net_savings = tot_inc - tot_exp
            accumulated_savings += net_savings
            savings_rate = (net_savings / tot_inc * 100) if tot_inc > 0 else 0
            summary.append({
                "연도": f"{y}년",
                "총 수입": tot_inc,
                "총 지출": tot_exp,
                "당기 순저축": net_savings,
                "누적 순저축": accumulated_savings,
                "저축률(%)": round(savings_rate, 2)
            })
        return pd.DataFrame(summary), "연도"
    else:
        summary = []
        accumulated_savings = 0
        for m in range(1, 13):
            m_df = df_var[df_var['month'] == m] if not df_var.empty else pd.DataFrame()
            tot_inc = m_df[m_df['type'] == '수입']['amount'].sum() if not m_df.empty else 0
            tot_exp = m_df[m_df['type'] == '지출']['amount'].sum() if not m_df.empty else 0
            net_savings = tot_inc - tot_exp
            accumulated_savings += net_savings
            savings_rate = (net_savings / tot_inc * 100) if tot_inc > 0 else 0
            summary.append({
                "월": f"{m}월",
                "총 수입": tot_inc,
                "총 지출": tot_exp,
                "당월 순저축": net_savings,
                "누적 순저축": accumulated_savings,
                "저축률(%)": round(savings_rate, 2)
            })
        return pd.DataFrame(summary), "월"

def generate_3tier_pivot(year_filter, r_type='지출'):
    df_var = get_variable_records(year_filter)
    filtered = df_var[df_var['type'] == r_type] if not df_var.empty else pd.DataFrame()
    
    if filtered.empty:
        if year_filter == "전체":
            return pd.DataFrame(columns=['대분류', '중분류', '소분류'] + [f"{y}년" for y in range(2020, 2027)] + ['총합계'])
        else:
            return pd.DataFrame(columns=['대분류', '중분류', '소분류'] + [f"{i}월" for i in range(1, 13)] + ['연간 합계'])
    
    col_dim = 'year' if year_filter == "전체" else 'month'
    pivot = filtered.pivot_table(
        index=['cat_large', 'cat_mid', 'cat_small'], 
        columns=col_dim, 
        values='amount', 
        aggfunc='sum', 
        fill_value=0
    )
    
    if year_filter == "전체":
        for y in range(2020, 2027):
            if y not in pivot.columns: pivot[y] = 0
        pivot = pivot[[y for y in range(2020, 2027)]]
        pivot.columns = [f"{y}년" for y in range(2020, 2027)]
        pivot['총합계'] = pivot.sum(axis=1)
    else:
        for m in range(1, 13):
            if m not in pivot.columns: pivot[m] = 0
        pivot = pivot[[m for m in range(1, 13)]]
        pivot.columns = [f"{m}월" for m in range(1, 13)]
        pivot['연간 합계'] = pivot.sum(axis=1)
        
    pivot = pivot.sort_values(by=pivot.columns[-1], ascending=False).reset_index()
    pivot = pivot.rename(columns={'cat_large': '대분류', 'cat_mid': '중분류', 'cat_small': '소분류'})
    return pivot

# -------------------------------------------------------------
# 5. 사이드바 컨트롤 & 분석 년도 선택기
# -------------------------------------------------------------
st.sidebar.markdown("### 💎 SMART LEDGER")

year_options = ["전체", "2026년", "2025년", "2024년", "2023년", "2022년", "2021년", "2020년"]
selected_year_str = st.sidebar.selectbox("📅 분석년도 선택", year_options, index=1)

menu = st.sidebar.radio(
    "메뉴 선택",
    [
        "연간 통합 대시보드", 
        "월별 수입/지출 내역 관리", 
        "📊 3단계 분류 심층 통계 분석", 
        "🏦 KB 거래내역 엑셀 연동", 
        "⚙️ 지능형 자동분류 규칙 관리", 
        "🏷️ 대/중/소분류 체계 관리",
        "🔒 비밀번호 변경"
    ]
)

if st.sidebar.button("🚪 시스템 로그아웃"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💾 데이터 엑셀 내보내기")
df_summary_export, _ = calculate_summary(selected_year_str)
df_var_all = get_variable_records(selected_year_str)
df_exp_pivot = generate_3tier_pivot(selected_year_str, '지출')
df_inc_pivot = generate_3tier_pivot(selected_year_str, '수입')
df_rules_export = get_auto_rules_3tier()

output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df_summary_export.to_excel(writer, sheet_name='수지요약', index=False)
    df_exp_pivot.to_excel(writer, sheet_name='지출_3단계_통계', index=False)
    df_inc_pivot.to_excel(writer, sheet_name='수입_3단계_통계', index=False)
    if not df_var_all.empty:
        df_var_all.to_excel(writer, sheet_name='거래내역전체', index=False)
    df_rules_export.to_excel(writer, sheet_name='자동분류규칙', index=False)
    get_3tier_hierarchy().to_excel(writer, sheet_name='3단계분류체계목록', index=False)

st.sidebar.download_button(
    label=f"[{selected_year_str}] 가계부 엑셀 다운로드",
    data=output.getvalue(),
    file_name=f"스마트가계부_{selected_year_str}_통합분석.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)

# -------------------------------------------------------------
# 메뉴 1: 연간 통합 대시보드
# -------------------------------------------------------------
if menu == "연간 통합 대시보드":
    st.title(f"📊 {selected_year_str} 수입 / 지출 통합 대시보드")
    df_summary, x_axis_col = calculate_summary(selected_year_str)
    
    tot_year_inc = df_summary["총 수입"].sum()
    tot_year_exp = df_summary["총 지출"].sum()
    tot_year_sav = df_summary["당월 순저축"].sum() if "당월 순저축" in df_summary.columns else df_summary["당기 순저축"].sum()
    avg_sav_rate = (tot_year_sav / tot_year_inc * 100) if tot_year_inc > 0 else 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="iso-card">
            <div class="iso-label">💰 총 수입</div>
            <div class="iso-value val-blue">{tot_year_inc:,} <span style="font-size: 1rem;">원</span></div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="iso-card">
            <div class="iso-label">💸 총 지출</div>
            <div class="iso-value val-red">{tot_year_exp:,} <span style="font-size: 1rem;">원</span></div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="iso-card">
            <div class="iso-label">📈 순 저축</div>
            <div class="iso-value val-green">{tot_year_sav:,} <span style="font-size: 1rem;">원</span></div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="iso-card">
            <div class="iso-label">🎯 평균 저축률</div>
            <div class="iso-value val-amber">{avg_sav_rate:.1f} <span style="font-size: 1rem;">%</span></div>
        </div>
        """, unsafe_allow_html=True)
        
    st.divider()
    
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(x=df_summary[x_axis_col], y=df_summary["총 수입"], name="총 수입", marker_color="#38bdf8"))
    fig_bar.add_trace(go.Bar(x=df_summary[x_axis_col], y=df_summary["총 지출"], name="총 지출", marker_color="#f87171"))
    net_col_name = "당월 순저축" if "당월 순저축" in df_summary.columns else "당기 순저축"
    fig_bar.add_trace(go.Scatter(x=df_summary[x_axis_col], y=df_summary[net_col_name], name="순저축", mode="lines+markers", marker_color="#4ade80", line=dict(width=3)))
    fig_bar.update_layout(
        title=f"{selected_year_str} {x_axis_col}별 수입, 지출 및 순저축 추이",
        barmode="group",
        hovermode="x unified",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20)
    )
    st.plotly_chart(fig_bar, use_container_width=True)
    
    c1, c2 = st.columns(2)
    with c1:
        df_var_exp = df_var_all[df_var_all['type'] == '지출'] if not df_var_all.empty else pd.DataFrame()
        if not df_var_exp.empty:
            cat_sum = df_var_exp.groupby("cat_large")["amount"].sum().reset_index()
            fig_pie1 = px.pie(cat_sum, names="cat_large", values="amount", title="지출 대분류별 구성 비중", hole=0.45, template="plotly_dark", color_discrete_sequence=px.colors.sequential.RdBu)
            st.plotly_chart(fig_pie1, use_container_width=True)
        else:
            st.info("등록된 지출 내역이 없습니다.")
            
    with c2:
        df_var_inc = df_var_all[df_var_all['type'] == '수입'] if not df_var_all.empty else pd.DataFrame()
        if not df_var_inc.empty:
            inc_sum = df_var_inc.groupby("cat_large")["amount"].sum().reset_index()
            fig_pie2 = px.pie(inc_sum, names="cat_large", values="amount", title="수입 대분류별 구성 비중", hole=0.45, template="plotly_dark", color_discrete_sequence=px.colors.sequential.Teal)
            st.plotly_chart(fig_pie2, use_container_width=True)
        else:
            st.info("등록된 수입 내역이 없습니다.")
            
    st.subheader("📑 상세 수지 분석표")
    fmt_dict = {
        "총 수입": "{:,}원", "총 지출": "{:,}원",
        "누적 순저축": "{:,}원", "저축률(%)": "{:.2f}%"
    }
    if "당월 순저축" in df_summary.columns: fmt_dict["당월 순저축"] = "{:,}원"
    if "당기 순저축" in df_summary.columns: fmt_dict["당기 순저축"] = "{:,}원"
    st.dataframe(df_summary.style.format(fmt_dict), use_container_width=True)

# -------------------------------------------------------------
# 메뉴 2: 월별 수입/지출 내역 관리
# -------------------------------------------------------------
elif menu == "월별 수입/지출 내역 관리":
    col_sel_y, col_sel_m = st.columns(2)
    with col_sel_y:
        cur_year_choice = st.selectbox(
            "관리할 년도 선택", 
            ["2026년", "2025년", "2024년", "2023년", "2022년", "2021년", "2020년"], 
            index=0 if selected_year_str == "전체" else ["2026년", "2025년", "2024년", "2023년", "2022년", "2021년", "2020년"].index(selected_year_str)
        )
    target_year = int(cur_year_choice.replace("년", ""))
    
    with col_sel_m:
        selected_month = st.selectbox("조회/관리할 월 선택", [f"{i}월" for i in range(1, 13)])
    month_int = int(selected_month.replace("월", ""))
    
    st.title(f"🗓 {target_year}년 {selected_month} 가계부 내역 관리")
    
    all_recs = get_variable_records(target_year)
    m_records = all_recs[all_recs["month"] == month_int] if not all_recs.empty else pd.DataFrame()
    
    m_var_inc = m_records[m_records["type"] == "수입"]["amount"].sum() if not m_records.empty else 0
    m_var_exp = m_records[m_records["type"] == "지출"]["amount"].sum() if not m_records.empty else 0
    m_net = m_var_inc - m_var_exp
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총 수입", f"{m_var_inc:,} 원")
    k2.metric("총 지출", f"{m_var_exp:,} 원", delta_color="inverse")
    k3.metric("당월 순저축", f"{m_net:,} 원")
    k4.metric("당월 저축률", f"{(m_net/m_var_inc*100):.1f} %" if m_var_inc > 0 else "0 %")
    
    st.divider()
    
    if 'editing_record_id' not in st.session_state:
        st.session_state.editing_record_id = None

    if st.session_state.editing_record_id is not None:
        edit_row = all_recs[all_recs["id"] == st.session_state.editing_record_id]
        if not edit_row.empty:
            edit_item = edit_row.iloc[0]
            st.warning(f"✏️ [내역 수정] 항목 ID #{edit_item['id']} ({edit_item['name']}) 수정 중입니다.")
            
            with st.form("edit_record_form"):
                col_y, col_type, col_date, col_name, col_amt = st.columns([1, 1, 1.2, 2.5, 1.8])
                new_year = col_y.number_input("년도", min_value=2020, max_value=2035, value=int(edit_item['year']))
                new_type = col_type.selectbox("구분", ["지출", "수입"], index=0 if edit_item["type"] == "지출" else 1)
                new_date = col_date.text_input("일자 (YYYY-MM-DD 또는 MM-DD)", edit_item["date"])
                new_name = col_name.text_input("항목명", edit_item["name"])
                new_amt = col_amt.number_input("금액 (원)", min_value=0, value=int(edit_item["amount"]), step=1000)
                
                type_hier = get_3tier_hierarchy(new_type)
                avail_large = sorted(type_hier['cat_large'].unique().tolist())
                cur_l_idx = avail_large.index(edit_item['cat_large']) if edit_item['cat_large'] in avail_large else 0
                
                col_l, col_m, col_s = st.columns(3)
                new_large = col_l.selectbox("대분류", avail_large, index=cur_l_idx)
                
                avail_mid = sorted(type_hier[type_hier['cat_large'] == new_large]['cat_mid'].unique().tolist())
                if not avail_mid: avail_mid = ['기타']
                cur_m_idx = avail_mid.index(edit_item['cat_mid']) if edit_item['cat_mid'] in avail_mid else 0
                new_mid = col_m.selectbox("중분류", avail_mid, index=cur_m_idx)
                
                avail_small = sorted(type_hier[(type_hier['cat_large'] == new_large) & (type_hier['cat_mid'] == new_mid)]['cat_small'].unique().tolist())
                if not avail_small: avail_small = ['기타']
                cur_s_idx = avail_small.index(edit_item['cat_small']) if edit_item['cat_small'] in avail_small else 0
                new_small = col_s.selectbox("소분류", avail_small, index=cur_s_idx)
                
                b_save, b_cancel = st.columns(2)
                if b_save.form_submit_button("수정 내용 저장", use_container_width=True):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("""
                    UPDATE variable_records 
                    SET year=?, type=?, date=?, name=?, amount=?, cat_large=?, cat_mid=?, cat_small=? 
                    WHERE id=?
                    """, (new_year, new_type, new_date, new_name, new_amt, new_large, new_mid, new_small, int(edit_item['id'])))
                    conn.commit()
                    conn.close()
                    st.session_state.editing_record_id = None
                    st.success("수정 완료되었습니다.")
                    st.rerun()
                if b_cancel.form_submit_button("수정 취소", use_container_width=True):
                    st.session_state.editing_record_id = None
                    st.rerun()

    st.subheader(f"➕ {target_year}년 {selected_month} 새로운 내역 직접 추가")
    c_y, c_type, c_large, c_mid, c_small = st.columns(5)
    rec_year = c_y.number_input("해당 년도", min_value=2020, max_value=2035, value=target_year, key="add_rec_year")
    rec_type = c_type.selectbox("수지 구분", ["지출", "수입"], key="add_rec_type")
    
    hier_df = get_3tier_hierarchy(rec_type)
    large_list = sorted(hier_df['cat_large'].unique().tolist())
    rec_large = c_large.selectbox("대분류 선택", large_list, key="add_rec_large")
    
    mid_list = sorted(hier_df[hier_df['cat_large'] == rec_large]['cat_mid'].unique().tolist())
    if not mid_list: mid_list = ['기타']
    rec_mid = c_mid.selectbox("중분류 선택", mid_list, key="add_rec_mid")
    
    small_list = sorted(hier_df[(hier_df['cat_large'] == rec_large) & (hier_df['cat_mid'] == rec_mid)]['cat_small'].unique().tolist())
    if not small_list: small_list = ['기타']
    rec_small = c_small.selectbox("소분류 선택", small_list, key="add_rec_small")
    
    with st.form("add_record_form", clear_on_submit=True):
        col_date, col_name, col_amt, col_btn = st.columns([1.2, 2.5, 2, 1.2])
        rec_date = col_date.text_input("일자 (YYYY-MM-DD)", f"{rec_year}-{month_int:02d}-01")
        rec_name = col_name.text_input("항목명/거래처", placeholder="예: 농협 하나로마트, 스타벅스")
        rec_amt = col_amt.number_input("금액 (원)", min_value=0, step=1000)
        btn_add = col_btn.form_submit_button("내역 등록", use_container_width=True)
        
        if btn_add:
            if rec_name and rec_amt > 0:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                INSERT INTO variable_records (year, month, type, date, time, name, amount, cat_large, cat_mid, cat_small, memo, source) 
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, '', '수기')
                """, (rec_year, month_int, rec_type, rec_date, rec_name, rec_amt, rec_large, rec_mid, rec_small))
                conn.commit()
                conn.close()
                st.success(f"등록 완료 [{rec_large} > {rec_mid} > {rec_small}]")
                st.rerun()
            else:
                st.error("항목명과 유효한 금액을 입력해 주세요.")

    st.subheader(f"📝 {selected_month} 등록 내역 목록 (총 {len(m_records)}건)")
    if not m_records.empty:
        h1, h2, h3, h4, h5, h6, h7, h8, h9, h10 = st.columns([1.0, 0.8, 2.0, 1.5, 1.2, 1.2, 1.2, 0.8, 0.6, 0.6])
        h1.markdown("**일자**"); h2.markdown("**구분**"); h3.markdown("**거래처/항목**"); h4.markdown("**금액**")
        h5.markdown("**대분류**"); h6.markdown("**중분류**"); h7.markdown("**소분류**"); h8.markdown("**출처**"); h9.markdown("**수정**"); h10.markdown("**삭제**")
        
        for idx, row in m_records.iterrows():
            c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns([1.0, 0.8, 2.0, 1.5, 1.2, 1.2, 1.2, 0.8, 0.6, 0.6])
            c1.text(f"{row['date']}")
            c2.markdown(f"<span style='color:{'#38bdf8' if row['type']=='수입' else '#f87171'}; font-weight:bold;'>{row['type']}</span>", unsafe_allow_html=True)
            c3.text(f"{row['name']}")
            c4.text(f"{row['amount']:,} 원")
            c5.text(f"{row['cat_large']}")
            c6.text(f"{row['cat_mid']}")
            c7.text(f"{row['cat_small']}")
            c8.caption(f"{row['source']}")
            if c9.button("✏️", key=f"edit_btn_{row['id']}"):
                st.session_state.editing_record_id = row['id']
                st.rerun()
            if c10.button("🗑", key=f"del_rec_{row['id']}"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("DELETE FROM variable_records WHERE id=?", (int(row['id']),))
                conn.commit()
                conn.close()
                st.rerun()
    else:
        st.info("해당 월에 등록된 거래 내역이 없습니다.")

# -------------------------------------------------------------
# 메뉴 3: 📊 3단계 분류 심층 통계 분석
# -------------------------------------------------------------
elif menu == "📊 3단계 분류 심층 통계 분석":
    st.title(f"📊 {selected_year_str} 3단계 분류 심층 통계 분석")
    st.info("💡 대분류 ➡️ 중분류 ➡️ 소분류 항목을 선택하여 드릴다운하거나, 다양한 차트 형태로 비교 분석할 수 있습니다.")
    
    df_var = get_variable_records(selected_year_str)
    
    view_mode = st.radio("분석 관점 선택", ["💸 지출 3단계 심층 분석", "💰 수입 3단계 심층 분석", "⚖️ 수입/지출 통합 비교 분석"], horizontal=True)
    
    if view_mode == "💸 지출 3단계 심층 분석":
        exp_df = df_var[df_var['type'] == '지출'] if not df_var.empty else pd.DataFrame()
        if exp_df.empty:
            st.warning("등록된 지출 내역이 없습니다.")
        else:
            tot_exp_val = exp_df['amount'].sum()
            top_l = exp_df.groupby("cat_large")["amount"].sum().idxmax()
            top_m = exp_df.groupby("cat_mid")["amount"].sum().idxmax()
            top_s = exp_df.groupby(["cat_large", "cat_mid", "cat_small"])["amount"].sum().idxmax()
            top_s_amt = exp_df.groupby(["cat_large", "cat_mid", "cat_small"])["amount"].sum().max()
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("총 지출액", f"{tot_exp_val:,} 원")
            c2.metric("최다 지출 대분류", f"{top_l}")
            c3.metric("최다 지출 중분류", f"{top_m}")
            c4.metric("최다 지출 소분류", f"{top_s[2]}", delta=f"{top_s_amt:,}원 ({(top_s_amt/tot_exp_val*100):.1f}%)")
            
            st.divider()
            
            st.subheader("🎨 지출 인터랙티브 시각화 대시보드")
            chart_choice = st.selectbox(
                "차트 형태 선택", 
                ["3단계 선버스트 차트 (Sunburst)", "3단계 트리맵 (Treemap)", "중분류별 지출 도넛 차트", "소분류 Top 15 랭킹 바", "대분류 히트맵"]
            )
            
            if chart_choice == "3단계 선버스트 차트 (Sunburst)":
                fig = px.sunburst(
                    exp_df, 
                    path=['cat_large', 'cat_mid', 'cat_small'], 
                    values='amount', 
                    title="대분류 ➡️ 중분류 ➡️ 소분류 지출 계층 구조", 
                    color='amount', 
                    template="plotly_dark",
                    color_continuous_scale='Reds'
                )
                st.plotly_chart(fig, use_container_width=True)
            elif chart_choice == "3단계 트리맵 (Treemap)":
                fig = px.treemap(
                    exp_df, 
                    path=['cat_large', 'cat_mid', 'cat_small'], 
                    values='amount', 
                    title="대-중-소 지출 면적 비중 트리맵", 
                    color='amount', 
                    template="plotly_dark",
                    color_continuous_scale='YlOrRd'
                )
                st.plotly_chart(fig, use_container_width=True)
            elif chart_choice == "중분류별 지출 도넛 차트":
                mid_sum = exp_df.groupby("cat_mid")["amount"].sum().reset_index()
                fig = px.pie(mid_sum, names="cat_mid", values="amount", title="중분류별 지출 비중", hole=0.45, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            elif chart_choice == "소분류 Top 15 랭킹 바":
                small_sum = exp_df.groupby(["cat_large", "cat_mid", "cat_small"])["amount"].sum().reset_index()
                small_sum["계층표시"] = small_sum["cat_large"] + " > " + small_sum["cat_mid"] + " > " + small_sum["cat_small"]
                small_sum = small_sum.sort_values(by="amount", ascending=True).tail(15)
                fig = px.bar(small_sum, x="amount", y="계층표시", orientation='h', text="amount", color="amount", template="plotly_dark", color_continuous_scale="Purples", title="소분류 누적 지출 Top 15")
                fig.update_traces(texttemplate='%{text:,}원', textposition='outside')
                st.plotly_chart(fig, use_container_width=True)
            elif chart_choice == "대분류 히트맵":
                col_group = 'year' if selected_year_str == "전체" else 'month'
                pivot_heat = exp_df.pivot_table(index='cat_large', columns=col_group, values='amount', aggfunc='sum', fill_value=0)
                fig = px.imshow(pivot_heat, labels=dict(x="기간", y="대분류", color="지출액"), aspect="auto", template="plotly_dark", color_continuous_scale="Reds", title="대분류별 지출 집중도 히트맵")
                st.plotly_chart(fig, use_container_width=True)
                
            st.subheader(f"📑 [지출] 대분류 - 중분류 - 소분류 상세 집계표 ({selected_year_str})")
            exp_pivot = generate_3tier_pivot(selected_year_str, '지출')
            fmt = {col: "{:,}원" for col in exp_pivot.columns if col not in ['대분류', '중분류', '소분류']}
            st.dataframe(exp_pivot.style.format(fmt), use_container_width=True)

    elif view_mode == "💰 수입 3단계 심층 분석":
        inc_df = df_var[df_var['type'] == '수입'] if not df_var.empty else pd.DataFrame()
        if inc_df.empty:
            st.warning("등록된 수입 내역이 없습니다.")
        else:
            tot_inc_val = inc_df['amount'].sum()
            top_il = inc_df.groupby("cat_large")["amount"].sum().idxmax()
            top_im = inc_df.groupby("cat_mid")["amount"].sum().idxmax()
            top_is = inc_df.groupby(["cat_large", "cat_mid", "cat_small"])["amount"].sum().idxmax()
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("총 수입액", f"{tot_inc_val:,} 원")
            c2.metric("최대 수입 대분류", f"{top_il}")
            c3.metric("최대 수입 중분류", f"{top_im}")
            c4.metric("최대 수입 소분류", f"{top_is[2]}")
            
            st.divider()
            
            col_i1, col_i2 = st.columns(2)
            with col_i1:
                fig_inc_sun = px.sunburst(inc_df, path=['cat_large', 'cat_mid', 'cat_small'], values='amount', title="수입 계층 선버스트 차트", color='amount', template="plotly_dark", color_continuous_scale='Blues')
                st.plotly_chart(fig_inc_sun, use_container_width=True)
            with col_i2:
                inc_tree = px.treemap(inc_df, path=['cat_large', 'cat_mid', 'cat_small'], values='amount', title="수입 트리맵 구조", color='amount', template="plotly_dark", color_continuous_scale='Teal')
                st.plotly_chart(inc_tree, use_container_width=True)
                
            st.subheader(f"📑 [수입] 대분류 - 중분류 - 소분류 상세 집계표 ({selected_year_str})")
            inc_pivot = generate_3tier_pivot(selected_year_str, '수입')
            fmt_i = {col: "{:,}원" for col in inc_pivot.columns if col not in ['대분류', '중분류', '소분류']}
            st.dataframe(inc_pivot.style.format(fmt_i), use_container_width=True)

    else:
        st.subheader("⚖️ 수입 vs 지출 통합 대분류 비교 분석")
        if not df_var.empty:
            type_cat_sum = df_var.groupby(["type", "cat_large"])["amount"].sum().reset_index()
            fig_compare = px.bar(
                type_cat_sum, 
                x="cat_large", 
                y="amount", 
                color="type", 
                barmode="group",
                title="수입 및 지출 대분류별 금액 비교",
                template="plotly_dark",
                color_discrete_map={"수입": "#38bdf8", "지출": "#f87171"}
            )
            fig_compare.update_traces(texttemplate='%{y:,}원', textposition='outside')
            st.plotly_chart(fig_compare, use_container_width=True)
            
            st.subheader("📅 연도별(Year-over-Year) 수입/지출 총액 추이")
            yoy_df = df_var.groupby(["year", "type"])["amount"].sum().reset_index()
            fig_yoy = px.bar(
                yoy_df, 
                x="year", 
                y="amount", 
                color="type", 
                barmode="group",
                title="연도별 수입 및 지출 규모 변동 추이 (2020~2026)",
                template="plotly_dark",
                color_discrete_map={"수입": "#38bdf8", "지출": "#f87171"}
            )
            fig_yoy.update_traces(texttemplate='%{y:,}원', textposition='outside')
            st.plotly_chart(fig_yoy, use_container_width=True)

# -------------------------------------------------------------
# 메뉴 4: 🏦 KB 국민은행 거래내역 엑셀 연동 (항상 보이는 초기화 재동기화 버튼 탑재)
# -------------------------------------------------------------
elif menu == "🏦 KB 거래내역 엑셀 연동":
    st.title("🏦 KB국민은행 거래내역 엑셀 자동 연동 (3단계)")
    st.info("💡 국민은행 거래내역 엑셀 파일(`.xls` 또는 `.xlsx`)을 업로드하면 2020년부터 2026년까지의 연도와 월이 정확하게 자동 추출되며, 3단계 규칙에 따라 100% 자동 분개됩니다.")

    # [핵심] 상시 노출되는 데이터베이스 원클릭 초기화 패널
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM variable_records WHERE source='KB국민'")
    cur_kb_count = cur.fetchone()[0]
    cur.execute("SELECT DISTINCT year FROM variable_records WHERE source='KB국민' ORDER BY year DESC")
    cur_kb_years = [str(r[0]) for r in cur.fetchall()]
    conn.close()
    
    st.markdown(f"""
    <div class="danger-box">
        <h4 style="color: #ef4444; margin-top:0;">🚨 KB국민은행 데이터 관리 & 초기화 센터</h4>
        <p style="color: #fca5a5; font-size: 0.95rem;">
            현재 등록된 KB 거래내역: <b>{cur_kb_count:,}건</b> (등록된 연도: {', '.join(cur_kb_years) if cur_kb_years else '없음'})<br>
            이전에 연도가 잘못 저장되었거나 2026년으로 쏠려있는 경우, 아래 버튼을 눌러 깔끔하게 비운 뒤 재등록하세요.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🔥 [즉시 초기화] 기존 등록된 KB국민은행 거래내역 전부 삭제", type="primary", use_container_width=True):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM variable_records WHERE source='KB국민'")
        conn.commit()
        conn.close()
        st.success("✅ 기존 KB국민은행 거래내역이 전부 깨끗하게 삭제되었습니다. 이제 아래에서 파일을 업로드해 주세요.")
        st.rerun()

    st.divider()
    st.subheader("📂 엑셀 파일 업로드 및 2020~2026년 신규 동기화")
    uploaded_file = st.file_uploader("KB국민은행 거래내역 엑셀 파일 선택", type=["xls", "xlsx"])
    
    if uploaded_file is not None:
        try:
            df_kb_raw = pd.read_excel(uploaded_file, skiprows=3)
            if 'Unnamed: 0' in df_kb_raw.columns:
                df_kb_raw.columns = df_kb_raw.iloc[0]
                df_kb_raw = df_kb_raw.iloc[1:].reset_index(drop=True)
                
            df_kb = df_kb_raw[df_kb_raw['거래일시'].notna() & (df_kb_raw['거래일시'] != '합계')].copy()
            st.success(f"파일 분석 성공: 총 {len(df_kb)}건의 거래 내역을 인식했습니다.")
            
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
                
                # [핵심] YYYY.MM.DD 앞자리 기준 연도/월 100% 정밀 추출
                if len(dt_str) >= 7 and dt_str[:4].isdigit():
                    rec_year = int(dt_str[:4])
                    month_num = int(dt_str[5:7]) if dt_str[5:7].isdigit() else 1
                    date_part = dt_str[:10].replace('.', '-')
                    time_part = dt_str[11:].strip() if len(dt_str) > 11 else ''
                else:
                    rec_year = 2026
                    month_num = 1
                    date_part = dt_str.split(' ')[0]
                    time_part = ''
                
                if withdraw_amt > 0:
                    rec_type = '지출'
                    amt = withdraw_amt
                elif deposit_amt > 0:
                    rec_type = '수입'
                    amt = deposit_amt
                else:
                    continue
                    
                display_name = partner_val if partner_val and partner_val != 'nan' else summary_val
                c_large, c_mid, c_small = auto_classify_3tier(partner_val, memo_val, rec_type, summary_val)
                
                parsed_rows.append({
                    "year": rec_year,
                    "month": month_num,
                    "type": rec_type,
                    "date": date_part,
                    "time": time_part,
                    "name": display_name,
                    "amount": amt,
                    "cat_large": c_large,
                    "cat_mid": c_mid,
                    "cat_small": c_small,
                    "memo": memo_val if memo_val != 'nan' else '',
                    "source": "KB국민"
                })
            
            preview_df = pd.DataFrame(parsed_rows)
            st.subheader("👀 3단계 자동 분류 및 연도별 분개 미리보기")
            st.dataframe(preview_df[["year", "date", "type", "name", "amount", "cat_large", "cat_mid", "cat_small"]].head(15).style.format({"amount": "{:,}원"}), use_container_width=True)
            
            year_counts = preview_df['year'].value_counts().sort_index()
            st.markdown("### 📊 연도별 추출 건수 검증 결과")
            y_cols = st.columns(len(year_counts))
            for i, (yr, cnt) in enumerate(year_counts.items()):
                y_cols[i].metric(f"{yr}년", f"{cnt:,} 건")
            
            st.divider()
            
            # [요청하신 붉은색/주황색 원클릭 초기화 재동기화 버튼]
            st.markdown("### 🚀 가계부 데이터베이스 반영 실행")
            
            col_b1, col_b2 = st.columns([1.5, 1])
            with col_b1:
                # 붉은색 메인 버튼
                btn_reset_sync = st.button("🚨 [초기화 후 재동기화] 기존 KB 데이터 전체 삭제 후 2020~2026년 신규 동기화", type="primary", use_container_width=True)
                if btn_reset_sync:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    
                    cur.execute("DELETE FROM variable_records WHERE source='KB국민'")
                    conn.commit()
                    
                    insert_tuples = [
                        (r['year'], r['month'], r['type'], r['date'], r['time'], r['name'], r['amount'], r['cat_large'], r['cat_mid'], r['cat_small'], r['memo'], r['source'])
                        for r in parsed_rows
                    ]
                    cur.executemany("""
                    INSERT INTO variable_records (year, month, type, date, time, name, amount, cat_large, cat_mid, cat_small, memo, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, insert_tuples)
                    
                    conn.commit()
                    conn.close()
                    st.success(f"🎉 초기화 및 동기화 완료! 총 {len(insert_tuples):,}건의 거래가 2020년~2026년 연도별로 온전하게 등록되었습니다.")
                    st.balloons()
                    st.rerun()
                    
            with col_b2:
                btn_cum_sync = st.button("➕ [누적 추가] 기존 데이터 유지하고 추가", use_container_width=True)
                if btn_cum_sync:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    
                    existing_df = pd.read_sql("SELECT year, date, time, name, amount FROM variable_records WHERE source='KB국민'", conn)
                    existing_keys = set(zip(existing_df['year'], existing_df['date'], existing_df['time'], existing_df['name'], existing_df['amount']))
                    
                    inserted_cnt = 0
                    skipped_cnt = 0
                    
                    for row in parsed_rows:
                        key = (row['year'], row['date'], row['time'], row['name'], row['amount'])
                        if key in existing_keys:
                            skipped_cnt += 1
                            continue
                        cur.execute("""
                        INSERT INTO variable_records (year, month, type, date, time, name, amount, cat_large, cat_mid, cat_small, memo, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (row['year'], row['month'], row['type'], row['date'], row['time'], row['name'], row['amount'], row['cat_large'], row['cat_mid'], row['cat_small'], row['memo'], row['source']))
                        inserted_cnt += 1
                        existing_keys.add(key)
                        
                    conn.commit()
                    conn.close()
                    st.success(f"동기화 완료: 신규 등록 {inserted_cnt}건 (중복 건너뜀 {skipped_cnt}건)")
                    st.balloons()
                    st.rerun()
        except Exception as e:
            st.error(f"파일 처리 중 오류가 발생했습니다: {e}")

# -------------------------------------------------------------
# 메뉴 5: ⚙️ 지능형 자동분류 규칙 관리 (3단계 매핑)
# -------------------------------------------------------------
elif menu == "⚙️ 지능형 자동분류 규칙 관리":
    st.title("⚙️ KB 지능형 자동 분류 규칙(키워드) 관리")
    st.info("💡 키워드를 등록하면 국민은행 엑셀을 업로드할 때 지정한 [대분류 > 중분류 > 소분류]로 100% 자동 매핑됩니다.")
    
    rules_df = get_auto_rules_3tier()
    col_r_add, col_r_list = st.columns([1, 1.5])
    
    with col_r_add:
        st.subheader("➕ 새 자동분류 키워드 등록")
        r_type = st.selectbox("수지 구분", ["지출", "수입"], key="rule_3_type")
        hier_df = get_3tier_hierarchy(r_type)
        
        c_l_list = sorted(hier_df['cat_large'].unique().tolist())
        r_large = st.selectbox("매핑할 대분류", c_l_list, key="rule_3_l")
        
        c_m_list = sorted(hier_df[hier_df['cat_large'] == r_large]['cat_mid'].unique().tolist())
        if not c_m_list: c_m_list = ['기타']
        r_mid = st.selectbox("매핑할 중분류", c_m_list, key="rule_3_m")
        
        c_s_list = sorted(hier_df[(hier_df['cat_large'] == r_large) & (hier_df['cat_mid'] == r_mid)]['cat_small'].unique().tolist())
        if not c_s_list: c_s_list = ['기타']
        r_small = st.selectbox("매핑할 소분류", c_s_list, key="rule_3_s")
        
        with st.form("add_rule_3tier_form", clear_on_submit=True):
            r_kw = st.text_input("매칭 키워드 (예: 스타벅스, 올리브영, 파머스)")
            if st.form_submit_button("키워드 규칙 추가", use_container_width=True):
                if r_kw.strip():
                    try:
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("""
                        INSERT INTO auto_rules_3tier (rule_type, cat_large, cat_mid, cat_small, keyword) 
                        VALUES (?, ?, ?, ?, ?)
                        """, (r_type, r_large, r_mid, r_small, r_kw.strip().lower()))
                        conn.commit()
                        conn.close()
                        st.success(f"키워드 '{r_kw.strip()}' ➡️ [{r_large} > {r_mid} > {r_small}] 등록 완료")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.warning("이미 등록되어 있는 키워드입니다.")
                else:
                    st.error("키워드를 입력해 주세요.")
                    
    with col_r_list:
        st.subheader(f"📋 등록된 자동 분류 규칙 (총 {len(rules_df)}개)")
        f_type = st.radio("보기 필터", ["전체", "지출", "수입"], horizontal=True, key="filter_rule_view")
        disp_rules = rules_df if f_type == "전체" else rules_df[rules_df['rule_type'] == f_type]
        
        if not disp_rules.empty:
            h1, h2, h3, h4, h5, h6 = st.columns([0.8, 1.2, 1.2, 1.2, 2.0, 0.6])
            h1.markdown("**구분**"); h2.markdown("**대분류**"); h3.markdown("**중분류**"); h4.markdown("**소분류**"); h5.markdown("**매칭 키워드**"); h6.markdown("**삭제**")
            
            for _, r in disp_rules.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([0.8, 1.2, 1.2, 1.2, 2.0, 0.6])
                c1.text(r['rule_type'])
                c2.text(r['cat_large'])
                c3.text(r['cat_mid'])
                c4.text(r['cat_small'])
                c5.markdown(f"`{r['keyword']}`")
                if c6.button("🗑", key=f"del_rule3_{r['id']}"):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM auto_rules_3tier WHERE id=?", (int(r['id']),))
                    conn.commit()
                    conn.close()
                    st.rerun()
        else:
            st.info("등록된 규칙이 없습니다.")

# -------------------------------------------------------------
# 메뉴 6: 🏷️ 대/중/소분류 체계 관리
# -------------------------------------------------------------
elif menu == "🏷️ 대/중/소분류 체계 관리":
    st.title("🏷 대분류 · 중분류 · 소분류 3단계 체계 관리")
    st.info("💡 가계부에서 사용할 3단계 분류 체계를 자유롭게 추가하거나 삭제할 수 있습니다.")
    
    col_add_3, col_view_3 = st.columns([1, 1.5])
    
    with col_add_3:
        st.subheader("➕ 새 3단계 분류 등록")
        h_type = st.selectbox("수지 구분", ["지출", "수입"], key="hier3_type")
        hier_df = get_3tier_hierarchy(h_type)
        
        mode_l = st.radio("대분류 선택 방식", ["기존 대분류 선택", "새 대분류 직접 입력"], horizontal=True)
        if mode_l == "기존 대분류 선택":
            l_candidates = sorted(hier_df['cat_large'].unique().tolist())
            inp_l = st.selectbox("대분류 선택", l_candidates)
        else:
            inp_l = st.text_input("새 대분류명 입력")
            
        mode_m = st.radio("중분류 선택 방식", ["기존 중분류 선택", "새 중분류 직접 입력"], horizontal=True)
        if mode_m == "기존 중분류 선택" and mode_l == "기존 대분류 선택":
            m_candidates = sorted(hier_df[hier_df['cat_large'] == inp_l]['cat_mid'].unique().tolist())
            if not m_candidates: m_candidates = ['기타']
            inp_m = st.selectbox("중분류 선택", m_candidates)
        else:
            inp_m = st.text_input("새 중분류명 입력")
            
        inp_s = st.text_input("추가할 소분류명 입력")
        
        if st.button("3단계 분류 등록하기", use_container_width=True):
            if inp_l.strip() and inp_m.strip() and inp_s.strip():
                try:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("""
                    INSERT INTO category_hierarchy_3tier (type, cat_large, cat_mid, cat_small) 
                    VALUES (?, ?, ?, ?)
                    """, (h_type, inp_l.strip(), inp_m.strip(), inp_s.strip()))
                    conn.commit()
                    conn.close()
                    st.success(f"[{h_type}] {inp_l.strip()} > {inp_m.strip()} > {inp_s.strip()} 등록 성공!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.warning("이미 존재하는 분류 조합입니다.")
            else:
                st.error("대분류, 중분류, 소분류 이름을 모두 입력해 주세요.")
                
    with col_view_3:
        st.subheader("📋 현재 등록된 3단계 분류 체계")
        v_type = st.radio("조회할 수지 구분", ["지출", "수입"], horizontal=True, key="view3_type")
        v_df = get_3tier_hierarchy(v_type)
        
        for large_name, l_group in v_df.groupby("cat_large"):
            with st.expander(f"📁 [대분류] {large_name}"):
                for mid_name, m_group in l_group.groupby("cat_mid"):
                    st.markdown(f"**📂 {mid_name}**")
                    for _, r in m_group.iterrows():
                        c_t, c_d = st.columns([3, 1])
                        c_t.text(f"  └ 🏷️ {r['cat_small']}")
                        if c_d.button("삭제", key=f"del_h3_{v_type}_{large_name}_{mid_name}_{r['cat_small']}"):
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("""
                            DELETE FROM category_hierarchy_3tier 
                            WHERE type=? AND cat_large=? AND cat_mid=? AND cat_small=?
                            """, (v_type, large_name, mid_name, r['cat_small']))
                            conn.commit()
                            conn.close()
                            st.rerun()

# -------------------------------------------------------------
# 메뉴 7: 🔒 비밀번호 변경
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
