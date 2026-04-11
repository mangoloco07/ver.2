import pandas as pd
import requests
import pyproj
from datetime import datetime

transformer = pyproj.Transformer.from_crs("epsg:4326", "epsg:5174", always_xy=True)

def smart_read_csv(filename):
    # 데이터 리딩 오류 방지 
    encodings = ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']
    for enc in encodings:
        try:
            df = pd.read_csv(filename, encoding=enc, low_memory=False)
            return df
        except UnicodeDecodeError:
            continue
    return None

bit_df = smart_read_csv('BIT.csv')
low_bus_df = smart_read_csv('low.csv')
walking_df = smart_read_csv('walking.csv')

# 장애인 경로 계산 로직 
def analyze_path(path_data, user_type):
    penalty = 0
    reasons = []
    
    for sub in path_data['subPath']:
        # 도보 구간에서 시간 패널티 부과 
        if sub['trafficType'] == 3:
            # 나의 현재 좌표와 보도의 좌표 비교해서 내가 어떤 길을 걷고 있는지 확인 
            check_points = [
                (sub.get('startX'), sub.get('startY')),
                (sub.get('endX'), sub.get('endY'))
            ]
            
            for sx, sy in check_points:
                if sx and sy:
                    mx, my = transformer.transform(sx, sy)
                    nearby = walking_df[
                        (walking_df['G2_XMIN'] <= mx) & (walking_df['G2_XMAX'] >= mx) &
                        (walking_df['G2_YMIN'] <= my) & (walking_df['G2_YMAX'] >= my)
                    ]
                    
                    if not nearby.empty:
                        # 휠체어 장애인의 경우: 보도폭 1.5m 이하면 15분 패널티 
                        if user_type == '1': 
                            width = nearby['BDL_WID'].min()
                            if width < 1.5:
                                penalty += 15
                                reasons.append(f"보도폭 협소({width}m)")

                        # 휠체어 장애인의 경우,경사도에 따라 패널티 부여
                        if user_type == '1':
                            slope = row.get('SLOPE', 0)
                            if slope >= 8:    # 급경사면 20분 
                                penalty += 20
                                reasons.append(f"급경사({slope:.1f}%)")
                            elif slope >= 5:  # 급경사가 아닌 경사구간이면 10분 
                                penalty += 10
                                reasons.append(f"경사구간({slope:.1f}%)")
                        
                        # 시각장애의 경우: 점자블록 부재시 15분 패널티 
                        if user_type == '2': 
                            if nearby['BRLL_BLK_SN'].isna().any():
                                penalty += 15 
                                reasons.append("점자블록 없음")

        # 버스 구간에서 패널티 부과 
        elif sub['trafficType'] == 2:
            bus_no = sub['lane'][0]['busNo']
            ars_id = str(sub['startArsID']).replace('-', '').zfill(5)
                    
            # 휠체어 장애인의 경우: 저상버스 도입율에 따라 최대 50분 패널티
            if user_type == '1':
                low_info = low_bus_df[low_bus_df['노선번호'] == str(bus_no)]
                if not low_info.empty:
                    rate = low_info['보유율'].values[0]
                    wait = int((100 - rate) / 2)
                    penalty += wait
                    if wait > 0: 
                        reasons.append(f"저상버스 부족({bus_no}) 대기 {wait}분")
            
            # 시각장애인의 경우: 정류장의 BIT 설치 안돼있으면 15분 패널티 
            elif user_type == '2':
                bit_status = bit_df[bit_df['ARS_ID'] == int(ars_id)]['BIT_설치여부'].values
                # BIT가 없으면 도착 정보를 소리로 들을 수 없으므로 지연 발생
                if len(bit_status) > 0 and '미설치' in bit_status[0]:
                    penalty += 15
                    reasons.append(f"BIT 미설치({ars_id})로 인한 정보 접근 지연")

    return penalty, ", ".join(list(set(reasons)))

def run_comparison():
    ODSAY_KEY = "yqhEh8MZC8yL3483q1ypL2ecQ83DZIVdMtFisljhjV8"
    user_type = input("장애 유형 (1. 휠체어, 2. 시각장애): ").strip()
    
    # 9시 신설동 -> 삼청동  (테스트용)
    sx, sy = "127.0255534", "37.57494727"
    ex, ey = "126.9810158", "37.59076538"
    departure_time = "202604100900"
    
    url = f"https://api.odsay.com/v1/api/searchPubTransPathT?SX={sx}&SY={sy}&EX={ex}&EY={ey}&apiKey={ODSAY_KEY}&SearchPathType=0&departure_time={departure_time}"
    
    try:
        res = requests.get(url).json()
        if 'result' not in res:
            print("경로 찾을 수 없음:", res.get('error', [{}])[0].get('message', '알 수 없는 이유'))
            return

        final_report = []
        
        # 상위 3개 대안 경로 
        for i, path in enumerate(res['result']['path'][:3]):
            n_time = path['info']['totalTime']
            p_time, reason = analyze_path(path, user_type)
            
            # 상세 경로 정보 
            path_details = []
            for sub in path['subPath']:
                if sub['trafficType'] == 1:
                    path_details.append(f"지하철 {sub['lane'][0]['name']} ({sub['startName']}역)")
                elif sub['trafficType'] == 2:
                    path_details.append(f"버스 {sub['lane'][0]['busNo']}번 ({sub['startName']})")
                elif sub['trafficType'] == 3:
                    if sub['distance'] > 0:
                        path_details.append(f"도보 {sub['distance']}m")
            
            detail_str = " -> ".join(path_details)
            
            final_report.append({
                '경로': f"대안 {i+1}",
                '일반인(분)': n_time,
                '장애인(분)': n_time + p_time,
                '추가지연': p_time,
                '지연사유': reason if reason else "없음",
                '상세경로': detail_str
            })
        
        print("\n" + "="*100)
        print(f"분석 결과 ({'휠체어' if user_type=='1' else '시각장애'})")
        print("-" * 100)
        
        for item in final_report:
            print(f"[{item['경로']}] 일반: {item['일반인(분)']}분 | 장애인: {item['장애인(분)']}분 (지연 +{item['추가지연']}분)")
            print(f" - 경로: {item['상세경로']}")
            print(f" - 사유: {item['지연사유']}")
            print("-" * 100)
        
    except Exception as e:
        print(f"오류: {e}")

if __name__ == "__main__":
    run_comparison()
