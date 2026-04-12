import streamlit as st
import pandas as pd
import requests
import pyproj
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="장애인 vs 일반인 대중교통 이용 소요시간", layout="wide")

# 2. API key (Streamlit Secrets)
ODSAY_KEY = st.secrets["ODSAY_KEY"]

transformer = pyproj.Transformer.from_crs("epsg:4326", "epsg:5174", always_xy=True)

@st.cache_data
def load_data():
    def smart_read_csv(filename):
        encodings = ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']
        for enc in encodings:
            return pd.read_csv(filename, encoding=enc, low_memory=False)    
        return pd.DataFrame()

    def read_parquet_data(filename):
        return pd.read_parquet(filename, engine='pyarrow')

    # walking.csv 용량이 너무 커서 walking.parquet으로 컨버트 
    bit_df = smart_read_csv('BIT.csv')
    low_bus_df = smart_read_csv('low.csv')
    walking_df = read_parquet_data('walking.parquet') 
    
    return bit_df, low_bus_df, walking_df

bit_df, low_bus_df, walking_df = load_data()
def analyze_path(path_data, user_type):
    penalty = 0
    reasons = []
    
    for sub in path_data['subPath']:
        # 도보 구간 분석
        if sub['trafficType'] == 3:
            check_points = [(sub.get('startX'), sub.get('startY')), (sub.get('endX'), sub.get('endY'))]
            for sx, sy in check_points:
                if sx and sy:
                    mx, my = transformer.transform(sx, sy)
                    nearby = walking_df[
                        (walking_df['G2_XMIN'] <= mx) & (walking_df['G2_XMAX'] >= mx) &
                        (walking_df['G2_YMIN'] <= my) & (walking_df['G2_YMAX'] >= my)
                    ]
                    if not nearby.empty:
                        if user_type == '1': 
                            width = nearby['BDL_WID'].min()
                            if width < 1.5:
                                penalty += 15
                                reasons.append(f"보도폭 협소({width}m)")
                            
                           
                            if 'SLOPE' in nearby.columns:
                                slope = nearby['SLOPE'].max()
                                if slope >= 8: penalty += 20; reasons.append(f"급경사({slope:.1f}%)")
                                elif slope >= 5: penalty += 10; reasons.append(f"경사구간({slope:.1f}%)")
                        
                        elif user_type == '2': 
                            if nearby['BRLL_BLK_SN'].isna().any():
                                penalty += 15 
                                reasons.append("점자블록 없음")

        elif sub['trafficType'] == 2:
            bus_no = sub['lane'][0]['busNo']
            ars_id = str(sub['startArsID']).replace('-', '').zfill(5)
            
            if user_type == '1':
                low_info = low_bus_df[low_bus_df['노선번호'] == str(bus_no)]
                if not low_info.empty:
                    rate = low_info['보유율'].values[0]
                    wait = int((100 - rate) / 2)
                    penalty += wait
                    if wait > 0: reasons.append(f"저상버스 부족({bus_no})")
            
            elif user_type == '2':
                if not bit_df.empty:
                    bit_status = bit_df[bit_df['ARS_ID'] == int(ars_id)]['BIT_설치여부'].values
                    if len(bit_status) > 0 and '미설치' in bit_status[0]:
                        penalty += 15
                        reasons.append(f"BIT 미설치({ars_id})")

    return penalty, ", ".join(list(set(reasons)))

# 5. UI 구성
st.title("♿ 장애인의 대중교통 이용 소요시간 ")
st.markdown("---")

with st.sidebar:
    st.header("🔍 검색 조건 설정")
    st.header("🔍 검색 조건 설정")
    u_type = st.radio("장애 유형", ("휠체어", "시각장애"), index=0)
    user_type_code = '1' if u_type == "휠체어" else '2'
    
    st.subheader("좌표 입력")
    sx = st.text_input("출발지 X (경도)", "126.9431")
    sy = st.text_input("출발지 Y (위도)", "37.5497")
    ex = st.text_input("목적지 X (경도)", "126.9413")
    ey = st.text_input("목적지 Y (위도)", "37.5655")
    
    st.subheader("출발 일시")
    d_date = st.date_input("날짜", datetime.now())
    d_time = st.time_input("시간", datetime.now())
    
    search_clicked = st.button("경로 탐색 시작", use_container_width=True)

# 6. 결과 출력
if search_clicked:
    formatted_time = d_date.strftime('%Y%m%d') + d_time.strftime('%H%M')
    url = f"https://api.odsay.com/v1/api/searchPubTransPathT?SX={sx}&SY={sy}&EX={ex}&EY={ey}&apiKey={ODSAY_KEY}&SearchPathType=0&departure_time={formatted_time}"
    
    with st.spinner("ODsay 데이터를 분석 중입니다..."):
        try:
            res = requests.get(url).json()
            if 'result' not in res:
                st.warning("오류")
            else:
                st.subheader(f"{u_type} 기준 분석 결과")
                
                for i, path in enumerate(res['result']['path'][:3]):
                    n_time = path['info']['totalTime']
                    p_time, reason = analyze_path(path, user_type_code)
                    total_time = n_time + p_time
                    
                    with st.container():
                        col1, col2 = st.columns([1, 3])
                        with col1:
                            st.metric(f"대안 {i+1}", f"{total_time}분", f"+{p_time}분", delta_color="inverse")
                        with col2:
                            summary = []
                            for sub in path['subPath']:
                                if sub['trafficType'] == 1: summary.append(f"🚇{sub['lane'][0]['name']}")
                                elif sub['trafficType'] == 2: summary.append(f"🚌{sub['lane'][0]['busNo']}")
                                elif sub['trafficType'] == 3 and sub['distance'] > 0: summary.append(f"🚶")
                            
                            st.write(f"**경로:** {' → '.join(summary)}")
                            st.write(f"**지연 사유:** {reason if reason else '없음'}")
                        st.divider()
        except Exception as e:
            st.error(f"오류: {e}")
