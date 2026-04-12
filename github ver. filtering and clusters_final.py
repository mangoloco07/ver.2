import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString
from sklearn.cluster import DBSCAN
import re

# 1. 데이터 로드 및 대기시간 계산
try:
    df = pd.read_csv('taxi.csv', encoding='utf-8')
except UnicodeDecodeError:
    df = pd.read_csv('taxi.csv', encoding='cp949')

# 대기시간(분) 계산
df['접수일시_dt'] = pd.to_datetime(df['접수일시'], errors='coerce')
df['배차일시_dt'] = pd.to_datetime(df['배차일시'], errors='coerce')
df['wait_time'] = (df['배차일시_dt'] - df['접수일시_dt']).dt.total_seconds() / 60

# 장애유형 filter
def classify_group(x):
    if pd.isna(x): return None
    if '지체' in x or '뇌병변' in x: return '휠체어'
    if '시각' in x: return '시각'
    return None

df['Group'] = df['장애유형'].apply(classify_group)
df = df[df['Group'].notna()].copy() 

# 시간대 설정(05~23)
df['datetime'] = pd.to_datetime(df.iloc[:, 0], errors='coerce')
df['hour'] = df['datetime'].dt.hour
df = df[(df['hour'] >= 5) & (df['hour'] < 23)].copy()

# 매핑 
dong_shp = gpd.read_file('행정구역.shp', encoding='cp949')
dong_shp['centroid'] = dong_shp.geometry.centroid
coord_dict = {row['EMD_NM']: (row['centroid'].x, row['centroid'].y) for _, row in dong_shp.iterrows()}

def normalize_dong(name):
    if pd.isna(name): return name
    return re.sub(r'제?\d동$|\d\.\d동$|\d가$', '', str(name)).strip()

df['출발동_clean'] = df['출발동'].apply(normalize_dong)
df['목적동_clean'] = df['목적동'].apply(normalize_dong)

def make_line(row):
    s, e = row['출발동_clean'], row['목적동_clean']
    if s in coord_dict and e in coord_dict:
        # coord_dict에서 좌표 정보를 가져옴
        return LineString([coord_dict[s], coord_dict[e]])
    return None

df['geometry'] = df.apply(make_line, axis=1)
gdf = gpd.GeoDataFrame(df.dropna(subset=['geometry']), geometry='geometry', crs="EPSG:5186")

# r=900m 기준 cluster (DBSCAN 활용)
hours = sorted(gdf['hour'].unique())
hour_frames = []

for hr in hours:
    hr_gdf = gdf[gdf['hour'] == hr].copy()
    hr_clusters = []
    
    for group in ['휠체어', '시각']:
        group_gdf = hr_gdf[hr_gdf['Group'] == group].copy()
        if len(group_gdf) < 1: continue
        
        coords = np.array([[g.coords[0][0], g.coords[0][1], g.coords[-1][0], g.coords[-1][1]] for g in group_gdf.geometry])
        db = DBSCAN(eps=900, min_samples=1).fit(coords)
        group_gdf['cluster_id'] = db.labels_
        
        # 클러스터별
        for cid in group_gdf['cluster_id'].unique():
            subset = group_gdf[group_gdf['cluster_id'] == cid]
            
            # 평균 대기시간
            avg_wait = subset['wait_time'].mean()
            
            # 대표 이동 경로 선정
            rep_move = subset.groupby(['출발동_clean', '목적동_clean']).size().idxmax()
            total_vol = len(subset)
            
            # 좌표 추출 
            start_lon, start_lat = coord_dict[rep_move[0]]
            end_lon, end_lat = coord_dict[rep_move[1]]
            
            hr_clusters.append({
                'hour': hr, 
                'Group': group, 
                'Total_Volume': total_vol,
                'Avg_Wait_Time': round(avg_wait, 2),
                'Rep_Start_Name': rep_move[0], 
                'Rep_End_Name': rep_move[1],
                'SX': start_lon, 'SY': start_lat,
                'EX': end_lon, 'EY': end_lat
            })
    
    if hr_clusters:
        hour_frames.append(pd.DataFrame(hr_clusters))

if hour_frames:
    new_clusters_df = pd.concat(hour_frames, ignore_index=True)
    # 새 파일 이름으로 저장
    new_clusters_df.to_csv('filter and clusters_final.csv', index=False, encoding='utf-8-sig')
