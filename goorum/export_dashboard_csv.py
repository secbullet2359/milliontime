"""
대시보드용 CSV 내보내기

train_xgboost.py가 만든
    - val_predictions_{tag}.csv (또는 test_predictions_{tag}.csv) : 날짜/종가/예측
    - shap_values_val_{tag}.npy : 같은 행 순서의 SHAP 값
    - xgb_model_{tag}.json (feature_names 추출용) 또는 shap_feature_importance_{tag}.csv
를 합쳐서, 종목 하나당 CSV 한 장으로 만든다.

⚠ predictions CSV와 shap npy는 반드시 "같은 실행에서 나온" 한 쌍이어야 함
   (val 데이터프레임의 행 순서가 완전히 동일해야 정렬이 맞음 - train_xgboost.py의
    fit_and_evaluate()에서 둘 다 같은 val 데이터프레임으로부터 만들어지므로 원래 짝이 맞음)

출력 CSV 컬럼:
    날짜, 종목코드, 종가, actual_next_close, predicted_return, shap__<feature1>, shap__<feature2>, ...
    (shap__ 접두어를 대시보드 HTML이 "이건 기여도 컬럼이다"라고 자동으로 인식하는 데 씀)
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------
# 경로 설정 - 실제 파일로 수정
# ------------------------------------------------------------------
PREDICTIONS_CSV = Path("/home/claude/news_collection/raw_data/xgb_output/val_predictions_full.csv")
SHAP_NPY = Path("/home/claude/news_collection/raw_data/xgb_output/shap_values_val_full.npy")
MODEL_JSON = Path("/home/claude/news_collection/raw_data/xgb_output/xgb_model_full.json")  # feature_names 용
STOCK_NAMES_CSV = Path("/home/claude/news_collection/raw_data/stock_names.csv")  # 종목코드,종목명 매핑

OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/dashboard_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STOCK_CODES = None  # None이면 전체 종목 각각 CSV 생성. 특정 종목만 원하면 ["005930", "000660"] 처럼 지정


def get_feature_names() -> list[str]:
    with open(MODEL_JSON, encoding="utf-8") as f:
        m = json.load(f)
    return m["learner"]["feature_names"]


def main():
    pred = pd.read_csv(PREDICTIONS_CSV, dtype={"종목코드": str}, parse_dates=["날짜"])
    shap_values = np.load(SHAP_NPY)
    feature_names = get_feature_names()

    assert len(pred) == len(shap_values), (
        f"행 수가 안 맞습니다: predictions {len(pred)}행 vs shap {len(shap_values)}행. "
        f"같은 실행에서 나온 파일 쌍인지 확인하세요."
    )
    assert shap_values.shape[1] == len(feature_names), (
        f"feature 수가 안 맞습니다: shap {shap_values.shape[1]}개 vs feature_names {len(feature_names)}개."
    )

    shap_df = pd.DataFrame(shap_values, columns=[f"shap__{f}" for f in feature_names])
    combined = pd.concat([pred.reset_index(drop=True), shap_df], axis=1)

    # 종목명 붙이기 (train_xgboost.py 출력에는 종목명이 빠져있어서 별도 매핑에서 조인)
    if STOCK_NAMES_CSV.exists():
        names = pd.read_csv(STOCK_NAMES_CSV, dtype={"종목코드": str})
        combined = combined.merge(names, on="종목코드", how="left")
        if combined["종목명"].isna().any():
            missing = combined.loc[combined["종목명"].isna(), "종목코드"].unique()
            print(f"⚠ 종목명을 못 찾은 종목코드: {list(missing)}")
    else:
        print(f"⚠ {STOCK_NAMES_CSV}가 없어 종목명 없이 진행합니다.")
        combined["종목명"] = ""

    target_codes = STOCK_CODES or sorted(combined["종목코드"].unique())
    for code in target_codes:
        sub = combined[combined["종목코드"] == code].sort_values("날짜")
        out_path = OUTPUT_DIR / f"dashboard_{code}.csv"
        sub.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"{len(target_codes)}개 종목 CSV 생성 완료 -> {OUTPUT_DIR}")
    print(f"예시: {OUTPUT_DIR / f'dashboard_{target_codes[0]}.csv'} ({len(combined[combined['종목코드']==target_codes[0]])}행)")


if __name__ == "__main__":
    main()
