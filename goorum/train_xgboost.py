"""
XGBoost 학습 파이프라인
    입력: merge_news_score_into_dataset.py의 결과물 (merged_dataset_with_news.csv)
    타겟: 익일 수익률 (다음날 종가/오늘 종가 - 1)
    평가: 예측 종가가 실제 종가의 ±5% 이내로 들어간 날의 비율 (목표 70%)
          + "전날 종가 유지" 베이스라인과 비교
    해석: SHAP로 어떤 변수가 예측에 가장 크게 기여했는지 확인

⚠ 이 샌드박스는 xgboost/shap가 설치되어 있지 않고 네트워크도 막혀서 설치가
   안 됨. 데이터 분리/타겟 정의/평가 로직은 sklearn 대체 모델로 검증했고,
   아래 코드는 실제 xgboost/shap API로 작성됨.
   실행 전: pip install xgboost shap
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

INPUT_PATH = Path("/home/claude/news_collection/raw_data/merged_dataset_with_news.csv")
OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/xgb_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TOLERANCE = 0.05          # ±5% 허용오차
TRAIN_RATIO, VAL_RATIO = 0.70, 0.15   # 나머지 15%는 test

# 학습에 쓰지 않을 컬럼 (식별자, 미래정보/타겟 관련, 중복정보)
DROP_COLS = ["날짜", "종목명", "next_return", "actual_next_close"]


def load_input(path: Path) -> pd.DataFrame:
    """
    확장자가 .xls/.xlsx라도 실제로는 CSV(텍스트)로 저장된 경우가 있어
    (예: pandas to_csv 결과를 확장자만 바꿔 올린 경우) 시그니처를 보고 판단.
    """
    with open(path, "rb") as f:
        head = f.read(8)

    is_binary_excel = head[:2] == b"PK" or head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if path.suffix.lower() in (".xls", ".xlsx") and not is_binary_excel:
        print(f"⚠ {path.name}: 확장자는 {path.suffix}지만 실제로는 CSV 텍스트 포맷입니다. CSV로 읽습니다.")
        return pd.read_csv(path, dtype={"종목코드": str}, parse_dates=["날짜"], encoding="utf-8-sig")
    elif path.suffix.lower() in (".xls", ".xlsx"):
        return pd.read_excel(path, dtype={"종목코드": str}, parse_dates=["날짜"])
    else:
        return pd.read_csv(path, dtype={"종목코드": str}, parse_dates=["날짜"], encoding="utf-8-sig")


def ensure_halt_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    '거래정지'/'재상장첫날' 컬럼이 없으면(중간 병합 과정에서 빠진 경우 등),
    원본 신호(거래량=0)로부터 다시 계산해서 만든다.
    (build_dataset.py에서 썼던 것과 동일한 탐지 방식: 거래량==0 -> 거래정지,
     그 다음날 -> 재상장첫날)
    """
    if "거래정지" in df.columns and "재상장첫날" in df.columns:
        return df

    print("⚠ '거래정지'/'재상장첫날' 컬럼이 없어 거래량 기준으로 다시 계산합니다.")
    df = df.sort_values(["종목코드", "날짜"]).copy()
    df["거래정지"] = (df["거래량"] == 0).astype(int)
    df["재상장첫날"] = (
        df.groupby("종목코드")["거래정지"].shift(1).fillna(0).astype(bool) & (~df["거래정지"].astype(bool))
    ).astype(int)

    n_halt = df["거래정지"].sum()
    print(f"  재계산 결과: 거래정지 {n_halt}행, 재상장첫날 {df['재상장첫날'].sum()}행")
    return df


def build_target(df: pd.DataFrame) -> pd.DataFrame:
    """
    다음날 수익률(next_return)과 실제 다음날 종가(actual_next_close)를 만든다.
    거래정지/재상장첫날에 걸리는 경우는 NaN으로 남겨서 이후 dropna로 학습 제외.
    """
    df = ensure_halt_flags(df)
    df = df.sort_values(["종목코드", "날짜"]).copy()

    df["next_return"] = df.groupby("종목코드")["종가"].shift(-1) / df["종가"] - 1
    df["actual_next_close"] = df.groupby("종목코드")["종가"].shift(-1)

    # 오늘(t) 또는 다음날(t+1)이 거래정지/재상장첫날이면 이 수익률은 무효
    next_day_halt = df.groupby("종목코드")["거래정지"].shift(-1).fillna(0).astype(bool)
    next_day_resume = df.groupby("종목코드")["재상장첫날"].shift(-1).fillna(0).astype(bool)
    today_halt = df["거래정지"].astype(bool)

    invalid = today_halt | next_day_halt | next_day_resume
    df.loc[invalid, ["next_return", "actual_next_close"]] = np.nan

    n_before = len(df)
    df = df.dropna(subset=["next_return", "actual_next_close"])
    print(f"타겟 정의 후 유효 샘플: {len(df)}/{n_before} "
          f"({(n_before-len(df))/n_before*100:.1f}% 제외 - 거래정지/데이터끝 등)")
    return df


def time_based_split(df: pd.DataFrame):
    """날짜 기준으로 앞 70%/15%/15%를 train/val/test로 분리 (모든 종목이 같은 경계로 나뉨)."""
    unique_dates = np.sort(df["날짜"].unique())
    n = len(unique_dates)
    train_end = unique_dates[int(n * TRAIN_RATIO)]
    val_end = unique_dates[int(n * (TRAIN_RATIO + VAL_RATIO))]

    train = df[df["날짜"] <= train_end]
    val = df[(df["날짜"] > train_end) & (df["날짜"] <= val_end)]
    test = df[df["날짜"] > val_end]

    print(f"\nTrain: {len(train)}행 ({train['날짜'].min().date()} ~ {train['날짜'].max().date()})")
    print(f"Val:   {len(val)}행 ({val['날짜'].min().date()} ~ {val['날짜'].max().date()})")
    print(f"Test:  {len(test)}행 ({test['날짜'].min().date()} ~ {test['날짜'].max().date()})")
    return train, val, test


def evaluate(df: pd.DataFrame, y_pred_return: np.ndarray, label: str) -> dict:
    """±5% 적중률 + 베이스라인(전날 종가 유지) 비교."""
    predicted_close = df["종가"].values * (1 + y_pred_return)
    actual_close = df["actual_next_close"].values

    error_rate = np.abs(predicted_close - actual_close) / actual_close
    accuracy = (error_rate <= TOLERANCE).mean() * 100
    mape = error_rate.mean() * 100

    baseline_close = df["종가"].values  # "내일도 오늘과 같다"
    baseline_error = np.abs(baseline_close - actual_close) / actual_close
    baseline_accuracy = (baseline_error <= TOLERANCE).mean() * 100

    print(f"\n[{label}] 모델 적중률(±{TOLERANCE*100:.0f}%): {accuracy:.1f}% "
          f"(MAPE: {mape:.2f}%) / 베이스라인: {baseline_accuracy:.1f}%")

    return {"label": label, "accuracy": accuracy, "mape": mape, "baseline_accuracy": baseline_accuracy}


def main():
    print(f"입력 로딩: {INPUT_PATH}")
    df = load_input(INPUT_PATH)
    df["종목코드"] = df["종목코드"].astype("category")

    df = build_target(df)
    train, val, test = time_based_split(df)

    feature_cols = [c for c in df.columns if c not in DROP_COLS + ["next_return", "actual_next_close"]]
    print(f"\n학습에 사용할 feature 수: {len(feature_cols)}")

    X_train, y_train = train[feature_cols], train["next_return"]
    X_val, y_val = val[feature_cols], val["next_return"]
    X_test, y_test = test[feature_cols], test["next_return"]

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        enable_categorical=True,   # 종목코드를 category dtype 그대로 사용
        random_state=42,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    model.save_model(OUTPUT_DIR / "xgb_model.json")
    print(f"\n모델 저장 완료: {OUTPUT_DIR / 'xgb_model.json'}")

    val_pred = model.predict(X_val)
    test_pred = model.predict(X_test)

    results = [
        evaluate(val, val_pred, "Validation"),
        evaluate(test, test_pred, "Test (최종, 한 번만 확인)"),
    ]
    pd.DataFrame(results).to_csv(OUTPUT_DIR / "evaluation_results.csv", index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------
    # SHAP 분석 (validation set 기준 - test는 최종 확인 전까지 아껴둠)
    # ------------------------------------------------------------------
    import shap
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_val)

    mean_abs_shap = pd.Series(
        np.abs(shap_values).mean(axis=0), index=feature_cols
    ).sort_values(ascending=False)

    print("\n=== SHAP 기준 변수 중요도 Top 15 ===")
    print(mean_abs_shap.head(15))
    mean_abs_shap.to_csv(OUTPUT_DIR / "shap_feature_importance.csv", encoding="utf-8-sig")

    np.save(OUTPUT_DIR / "shap_values_val.npy", shap_values)
    print(f"\nSHAP 값 저장 완료: {OUTPUT_DIR / 'shap_values_val.npy'} "
          f"(shape: {shap_values.shape}, X_val과 같은 행 순서)")


if __name__ == "__main__":
    main()
