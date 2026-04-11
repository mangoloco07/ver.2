import pandas as pd
import geopandas as gpd
import numpy as np
from scipy.spatial import KDTree

def build_final_walking_data():
        base_df = pd.read_csv('보도기본사항.csv', encoding='cp949', low_memory=False)
        block_df = pd.read_csv('점자블록.csv', encoding='cp949', low_memory=False)
        spot_heights = gpd.read_file('표고점.shp')

    # 보도면관리번호를 기준으로 보도기본사항 - 점자블록 merge
    block_sub = block_df[['보도면관리번호', 'BRLL_BLK_SN']].drop_duplicates('보도면관리번호')
    integrated_df = pd.merge(base_df, block_sub, on='보도면관리번호', how='left')

    # 표고점기준 경사도 계산
    spot_coords = np.array(list(zip(spot_heights.geometry.x, spot_heights.geometry.y)))
    height_values = spot_heights['HEIGHT'].values
    tree = KDTree(spot_coords)

    # 시작점(XMIN, YMIN)과 끝점(XMAX, YMAX) 주변의 표고점 기준 
    _, s_indices = tree.query(integrated_df[['G2_XMIN', 'G2_YMIN']].values)
    integrated_df['START_H'] = height_values[s_indices]

    _, e_indices = tree.query(integrated_df[['G2_XMAX', 'G2_YMAX']].values)
    integrated_df['END_H'] = height_values[e_indices]

    # 경사도 = (높이차 / 보도길이) * 100
    integrated_df['SLOPE'] = (
        np.abs(integrated_df['END_H'] - integrated_df['START_H']) / 
        integrated_df['BDL_LEN'].replace(0, 0.1)
    ) * 100

    output_filename = 'walking.csv'
    integrated_df.to_csv(output_filename, index=False, encoding='utf-8-sig')
    
if __name__ == "__main__":
    build_final_walking_data()
