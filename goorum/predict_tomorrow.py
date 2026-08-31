"""
predict_tomorrow.py - 최종 단계

merged_dataset(정형데이터, 오늘까지) + today_news_score.csv(오늘의 뉴스점수)
+ macro_indicators.csv(환율/금리) + dart_disclosures.csv(공시)
를 "오늘" 하루치로 전부 합쳐서, 최종 XGBoost 모델로 "내일 수익률"을 예측한다.

⚠ macro/dart 데이터가 오늘(정형데이터 마지막 날짜)까지 못 미치는 경우 대응:
   - macro: 마지막으로 확인된 값을 오늘까지 forward-fill (환율/금리는
     "다음 발표/변경 전까지 유지"가 맞는 값이라 이 방식이 타당함)
   - dart: 못 채운 기간은 공시 0건으로 처리 (실제로 없었는지, 아직 수집이
     안 된 것인지 구분이 안 되니 참고용으로만 볼 것 - 아래 로그에 갭 기간을
     명시적으로 출력함)
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

MERGED_DATASET_PATH = Path("kospi_top50_data/predict/merged_dataset.csv")
NEWS_SCORE_PATH = Path("raw_data/predict/today_news_score.csv")
MACRO_PATH = Path("raw_data/macro_indicators.csv")
DART_PATH = Path("raw_data/dart_disclosures.csv")
MODEL_PATH = Path("raw_data/xgb_output/xgb_model_full.json")
OUTPUT_PATH = Path("raw_data/predict/tomorrow_prediction.csv")

MACRO_LEVEL_COLS = ["usd_krw", "base_rate", "fed_funds_rate", "us_10y_treasury"]


def load_csv(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", **kwargs)


def prepare_macro(path: Path, target_end: pd.Timestamp) -> pd.DataFrame:
    macro = load_csv(path, parse_dates=["날짜"])
    macro = macro[["날짜"] + MACRO_LEVEL_COLS].sort_values("날짜").set_index("날짜")

    last_available = macro.index.max()
    if last_available < target_end:
        print(f"⚠ macro 데이터가 {last_available.date()}까지만 있어, "
              f"{target_end.date()}까지 마지막 값으로 forward-fill합니다 "
              f"(그 사이 {(target_end - last_available).days}일은 실제 변동을 반영 못함).")

    full_range = pd.date_range(macro.index.min(), max(macro.index.max(), target_end), freq="D")
    macro = macro.reindex(full_range).ffill()

    for col in MACRO_LEVEL_COLS:
        macro[f"{col}_diff"] = macro[col].diff()
        macro[f"{col}_pct_change"] = macro[col].pct_change()

    return macro.reset_index().rename(columns={"index": "날짜"})


def prepare_dart(path: Path, target_date: pd.Timestamp) -> pd.DataFrame:
    dart = load_csv(path, dtype={"종목코드": str}, parse_dates=["날짜"])

    last_available = dart["날짜"].max()
    if last_available < target_date:
        print(f"⚠ dart 공시 데이터가 {last_available.date()}까지만 있어, "
              f"{target_date.date()}은 '공시 0건'으로 처리됩니다 "
              f"(실제로 없었는지 미수집인지 구분 안 되니 참고만 하세요).")

    counts = (
        dart.groupby(["날짜", "종목코드", "pblntf_ty_filter"])
        .size()
        .unstack("pblntf_ty_filter", fill_value=0)
    )
    counts.columns = [f"공시_{c}건수" for c in counts.columns]
    counts["공시_전체건수"] = counts.sum(axis=1)
    counts["공시발생여부"] = (counts["공시_전체건수"] > 0).astype(int)
    return counts.reset_index()


def ensure_halt_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["종목코드", "날짜"]).copy()
    df["거래정지"] = (df["거래량"] == 0).astype(int)
    df["재상장첫날"] = (
        df.groupby("종목코드")["거래정지"].shift(1).fillna(0).astype(bool) & (~df["거래정지"].astype(bool))
    ).astype(int)
    return df


def main():
    print(f"정형데이터 로딩: {MERGED_DATASET_PATH}")
    df = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str}, parse_dates=["날짜"])
    today = df["날짜"].max()
    print(f"'오늘' 기준일: {today.date()}")

    df = ensure_halt_flags(df)

    # ------------------------------------------------------------------
    # macro 병합 (날짜 기준 broadcast)
    # ------------------------------------------------------------------
    macro = prepare_macro(MACRO_PATH, target_end=today)
    df = df.merge(macro, on="날짜", how="left")

    # ------------------------------------------------------------------
    # dart 병합 ((날짜,종목코드) 기준, 없으면 0건)
    # ------------------------------------------------------------------
    dart = prepare_dart(DART_PATH, target_date=today)
    dart_cols = [c for c in dart.columns if c not in ("날짜", "종목코드")]
    df = df.merge(dart, on=["날짜", "종목코드"], how="left")
    df[dart_cols] = df[dart_cols].fillna(0)

    # ------------------------------------------------------------------
    # 오늘의 뉴스점수 병합 ((날짜,종목코드) 기준, 오늘 하루치만 존재)
    # ------------------------------------------------------------------
    news = load_csv(NEWS_SCORE_PATH, parse_dates=["날짜"])
    df = df.merge(news, on=["날짜", "종목코드"], how="left")
    df["news_score_missing"] = df["news_influence_score_per_stock"].isna().astype(int)

    # ------------------------------------------------------------------
    # 오늘 하루치만 추출 (예측 대상)
    # ------------------------------------------------------------------
    today_df = df[df["날짜"] == today].copy()
    today_df["종목코드"] = today_df["종목코드"].astype("category")
    print(f"\n오늘({today.date()}) 종목 수: {len(today_df)} (50개여야 정상)")
    print(f"오늘 news_score_missing 비율: {today_df['news_score_missing'].mean()*100:.1f}% "
          f"(0%가 아니면 today_news_score.csv 병합이 잘 안 된 것)")

    # ------------------------------------------------------------------
    # 모델 로딩 + feature 정합성 확인 + 예측
    # ------------------------------------------------------------------
    model = xgb.XGBRegressor(enable_categorical=True)
    model.load_model(MODEL_PATH)
    feature_cols = model.get_booster().feature_names

    missing = set(feature_cols) - set(today_df.columns)
    if missing:
        raise ValueError(f"모델이 기대하는 feature가 없습니다: {missing}. "
                          f"merge 단계에서 빠진 컬럼이 있는지 확인하세요.")

    X_today = today_df[feature_cols]
    pred_return = model.predict(X_today)

    today_df["예측수익률"] = pred_return
    today_df["예측종가"] = today_df["종가"] * (1 + pred_return)

    result = today_df[["종목코드", "종목명", "종가", "예측수익률", "예측종가"]] \
        .sort_values("예측수익률", ascending=False) \
        .rename(columns={"종가": "오늘종가"})

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n=== {today.date()} 기준, 다음 거래일 예측 (상위 5 / 하위 5) ===")
    print(result.head(5).to_string(index=False))
    print("...")
    print(result.tail(5).to_string(index=False))
    print(f"\n저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
