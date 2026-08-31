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

INPUT_PATH = Path("/home/claude/news_collection/raw_data/merged_dataset_with_news_macro_dart.csv")
OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/xgb_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TOLERANCE = 0.05          # ±5% 허용오차
TRAIN_RATIO, VAL_RATIO = 0.70, 0.15   # 나머지 15%는 test
TOP_K_FEATURES = 15       # 2단계에서 SHAP 상위 몇 개만 남겨서 재학습할지

# ⚠ 뉴스 임베딩이 2026-04-02까지만 존재함 (daily_news_embeddings.parquet 확인 결과).
#   그 이후 구간은 news_influence_score_per_stock이 통째로 결측이라, 평가가
#   왜곡되지 않도록 이 날짜까지의 데이터만 사용한다.
#   뉴스 수집이 이후로 더 진행되면 이 값을 늘려서 다시 실행하면 됨.
DATA_CUTOFF_DATE = "2026-04-02"

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

    # 뉴스 점수 결측을 "0에 가까운 값"과 구분하기 위한 명시적 플래그.
    # (이전 진단 결과: Train/Val엔 결측이 0%였는데 Test 후반부에만 갑자기 50%가
    #  비어서, 모델이 결측을 처리하는 학습된 경험이 거의 없었던 게 test 성능
    #  하락의 핵심 원인 중 하나였음 - 이 플래그로 "결측 자체"를 신호로 만들어줌)
    df["news_score_missing"] = df["news_influence_score_per_stock"].isna().astype(int)

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


def evaluate_by_news_coverage(df: pd.DataFrame, y_pred_return: np.ndarray, label: str):
    """
    뉴스 점수가 있는 구간 / 없는 구간을 나눠서 각각 평가.
    (test 후반부처럼 뉴스가 통째로 빠진 구간의 성능을 따로 봐야, 진짜 모델의
     일반화 성능과 '데이터가 아직 없어서 생긴 하락'을 구분할 수 있음)
    """
    has_news = ~df["news_score_missing"].astype(bool)
    results = []
    for sub_label, mask in [("뉴스 O", has_news), ("뉴스 X(결측)", ~has_news)]:
        if mask.sum() == 0:
            continue
        sub_df = df[mask]
        sub_pred = y_pred_return[mask.values]
        results.append(evaluate(sub_df, sub_pred, f"{label} - {sub_label}"))
    return results


def evaluate_by_news_strength(df: pd.DataFrame, y_pred_return: np.ndarray, label: str):
    """
    news_influence_score_per_stock의 절댓값이 큰 날(뉴스 신호가 강한 날) vs
    작은 날(신호가 거의 없는 날)로 나눠서 모델이 특히 어디서 유효한지 확인.
    (SHAP에서 이 변수가 압도적 1위로 나왔다면, 신호가 강한 구간에서
     모델-베이스라인 격차가 더 뚜렷하게 드러나야 앞뒤가 맞음)
    """
    score_abs = df["news_influence_score_per_stock"].abs()
    tertile_high = score_abs >= score_abs.quantile(2/3)
    tertile_low = score_abs <= score_abs.quantile(1/3)

    results = []
    for sub_label, mask in [("뉴스신호 강함(상위1/3)", tertile_high), ("뉴스신호 약함(하위1/3)", tertile_low)]:
        sub_df = df[mask]
        sub_pred = y_pred_return[mask.values]
        results.append(evaluate(sub_df, sub_pred, f"{label} - {sub_label}"))
        detailed_diagnostics(sub_df, sub_pred, f"{label} - {sub_label}")
    return results


def detailed_diagnostics(df: pd.DataFrame, y_pred_return: np.ndarray, label: str):
    """
    ±5% 적중률은 대부분의 날이 원래 그 안에서 움직여서 모델/베이스라인 차이가
    잘 안 드러나는 무딘 지표임. 방향 적중률/상관관계/교차표로 더 세밀하게 확인.
    """
    actual_return = df["next_return"].values
    direction_acc = (np.sign(y_pred_return) == np.sign(actual_return)).mean() * 100
    corr = np.corrcoef(y_pred_return, actual_return)[0, 1]

    predicted_close = df["종가"].values * (1 + y_pred_return)
    actual_close = df["actual_next_close"].values
    model_hit = np.abs(predicted_close - actual_close) / actual_close <= TOLERANCE
    baseline_hit = np.abs(df["종가"].values - actual_close) / actual_close <= TOLERANCE

    model_only = (model_hit & ~baseline_hit).sum()
    baseline_only = (baseline_hit & ~model_hit).sum()

    print(f"\n[{label}] 세부진단 - 방향적중률: {direction_acc:.2f}% (랜덤=50%), "
          f"예측-실제 상관관계: {corr:.4f}")
    print(f"  모델만 맞춤: {model_only}건 / 베이스라인만 맞춤: {baseline_only}건 "
          f"/ 순수 우위: {model_only - baseline_only}건 (전체 {len(df)}건 중)")


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


# 경제학적 근거가 뚜렷한 feature들 - 방향(+/-)은 강제하지 않고, colsample 샘플링 시
# 후보로 더 자주 뽑히도록만 가중치를 줌 (강제로 분기를 만들게 하는 게 아니라
# "이 feature들을 더 자주 검토해봐라" 정도의 안전한 우선순위)
PRIORITY_FEATURES = {
    "시장대비알파": 3.0,
    "m2": 3.0, "m2_diff": 3.0, "m2_pct_change": 3.0,
    "실질금리": 3.0,
    "물가상승률_YoY": 2.0,
    # 기존에 SHAP로 이미 중요성 확인됐던 macro feature들도 같이 우선순위 부여
    "usd_krw": 2.0, "usd_krw_pct_change": 2.0,
    "us_10y_treasury": 2.0, "us_10y_treasury_pct_change": 2.0,
    "news_influence_score_per_stock": 2.0,
}
DEFAULT_FEATURE_WEIGHT = 1.0


def build_feature_weights(feature_cols: list[str]) -> list[float]:
    return [PRIORITY_FEATURES.get(f, DEFAULT_FEATURE_WEIGHT) for f in feature_cols]


def fit_and_evaluate(train, val, test, feature_cols, tag: str):
    """
    한 번의 학습+평가 사이클. tag별로 결과 파일이 겹치지 않게 접두어를 붙임.
    (전체 feature로 한 번, SHAP 상위 K개로 한 번 - 이렇게 2번 호출해서 비교)
    """
    print(f"\n{'='*60}\n[{tag}] feature 수: {len(feature_cols)}\n{'='*60}")

    X_train, y_train = train[feature_cols], train["next_return"]
    X_val, y_val = val[feature_cols], val["next_return"]
    X_test, y_test = test[feature_cols], test["next_return"]

    feature_weights = build_feature_weights(feature_cols)
    boosted = [f for f, w in zip(feature_cols, feature_weights) if w > DEFAULT_FEATURE_WEIGHT]
    if boosted:
        print(f"우선순위 부여된 feature: {boosted}")

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        enable_categorical=True,
        early_stopping_rounds=20,
        random_state=42,
        feature_weights=feature_weights,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"실제 사용된 나무 개수: {model.best_iteration + 1} / {model.n_estimators} "
          f"(조기종료 여부: {'예' if model.best_iteration + 1 < model.n_estimators else '아니오 - 다 씀'})")

    model.save_model(OUTPUT_DIR / f"xgb_model_{tag}.json")

    val_pred = model.predict(X_val)
    test_pred = model.predict(X_test)

    val[["날짜", "종목코드", "종가", "actual_next_close", "next_return", "news_score_missing"]].assign(
        predicted_return=val_pred
    ).to_csv(OUTPUT_DIR / f"val_predictions_{tag}.csv", index=False, encoding="utf-8-sig")
    test[["날짜", "종목코드", "종가", "actual_next_close", "next_return", "news_score_missing"]].assign(
        predicted_return=test_pred
    ).to_csv(OUTPUT_DIR / f"test_predictions_{tag}.csv", index=False, encoding="utf-8-sig")

    results = [
        evaluate(val, val_pred, f"[{tag}] Validation"),
        evaluate(test, test_pred, f"[{tag}] Test (전체)"),
    ]
    detailed_diagnostics(val, val_pred, f"[{tag}] Validation")
    detailed_diagnostics(test, test_pred, f"[{tag}] Test")
    results += evaluate_by_news_strength(test, test_pred, f"[{tag}] Test")

    import shap
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_val)
    mean_abs_shap = pd.Series(
        np.abs(shap_values).mean(axis=0), index=feature_cols
    ).sort_values(ascending=False)
    mean_abs_shap.to_csv(OUTPUT_DIR / f"shap_feature_importance_{tag}.csv", encoding="utf-8-sig")
    np.save(OUTPUT_DIR / f"shap_values_val_{tag}.npy", shap_values)

    print(f"\n[{tag}] SHAP 기준 변수 중요도 Top 10:")
    print(mean_abs_shap.head(10))

    return {"results": results, "mean_abs_shap": mean_abs_shap}


def main():
    print(f"입력 로딩: {INPUT_PATH}")
    df = load_input(INPUT_PATH)
    df["종목코드"] = df["종목코드"].astype("category")

    cutoff = pd.Timestamp(DATA_CUTOFF_DATE)
    n_before = len(df)
    df = df[df["날짜"] <= cutoff].copy()
    print(f"데이터 컷오프 적용 ({DATA_CUTOFF_DATE}까지): {n_before}행 -> {len(df)}행 "
          f"({n_before - len(df)}행 제외)")

    df = build_target(df)
    train, val, test = time_based_split(df)

    all_feature_cols = [c for c in df.columns if c not in DROP_COLS + ["next_return", "actual_next_close"]]

    # ------------------------------------------------------------------
    # 1단계: 전체 feature로 학습 -> SHAP 중요도 확인
    # ------------------------------------------------------------------
    full_run = fit_and_evaluate(train, val, test, all_feature_cols, tag="full")

    # ------------------------------------------------------------------
    # 2단계: SHAP 상위 TOP_K_FEATURES개만 남겨서 재학습 (반드시 '종목코드'는 유지 -
    #         카테고리 정체성 정보라 별도 취급, 상위 K에 없어도 강제로 포함)
    # ------------------------------------------------------------------
    top_features = full_run["mean_abs_shap"].head(TOP_K_FEATURES).index.tolist()
    if "종목코드" not in top_features:
        top_features.append("종목코드")
    print(f"\n2단계에 사용할 feature ({len(top_features)}개): {top_features}")

    pruned_run = fit_and_evaluate(train, val, test, top_features, tag="pruned")

    # ------------------------------------------------------------------
    # 두 결과 비교
    # ------------------------------------------------------------------
    all_results = full_run["results"] + pruned_run["results"]
    result_df = pd.DataFrame(all_results)
    result_df.to_csv(OUTPUT_DIR / "evaluation_results_comparison.csv", index=False, encoding="utf-8-sig")

    print(f"\n{'='*60}\n=== 전체 feature(full) vs 상위 {TOP_K_FEATURES}개(pruned) 비교 ===\n{'='*60}")
    print(result_df[["label", "accuracy", "baseline_accuracy", "mape"]].to_string(index=False))


if __name__ == "__main__":
    main()
