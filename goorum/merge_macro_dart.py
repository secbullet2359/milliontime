"""
macro_indicators.csv(환율/금리) + dart_disclosures.csv(공시)를
merged_dataset_with_news.csv에 통합한다.

macro_indicators:
    - 날짜 기준 공통값 -> 50개 종목에 broadcast
    - ⚠ 확인 결과 forward-fill이 안 되어 있었음 (base_rate 96.7% 결측 등).
      기준금리/환율은 "다음 변경 전까지 그 값 유지"가 맞는 값이라, 여기서
      직접 ffill을 다시 적용하고, diff/pct_change도 그 위에서 재계산한다.

dart_disclosures:
    - (날짜, 종목코드) 기준 -> 종목별로 다른 값
    - 공시유형(B/C/I)별로 건수를 나눠서 집계 (한 컬럼으로 합치면 미래에셋증권처럼
      일상적 발행공시(C)가 많은 종목이 압도적으로 커져서 신호가 왜곡됨)
    - 공시가 전혀 없는 (날짜,종목코드)는 결측이 아니라 "0건"이 맞는 값이므로
      fillna(0) 처리 (news_influence_score의 NaN=미수집과는 성격이 다름)
"""

from pathlib import Path

import numpy as np
import pandas as pd

BASE_PATH = Path("/home/claude/news_collection/raw_data/merged_dataset_with_news.csv")
MACRO_PATH = Path("/mnt/user-data/uploads/macro_indicators.xls")   # 실제로는 CSV(BOM)
DART_PATH = Path("/mnt/user-data/uploads/dart_disclosures.xls")     # 실제로는 CSV(BOM)
OUTPUT_PATH = Path("/home/claude/news_collection/raw_data/merged_dataset_with_news_macro_dart.csv")

MACRO_LEVEL_COLS = ["usd_krw", "base_rate", "fed_funds_rate", "us_10y_treasury"]


def load_csv_like(path: Path, **kwargs) -> pd.DataFrame:
    """확장자가 .xls라도 실제로는 BOM 붙은 CSV인 경우 대응."""
    return pd.read_csv(path, encoding="utf-8-sig", **kwargs)


def prepare_macro(path: Path) -> pd.DataFrame:
    macro = load_csv_like(path, parse_dates=["날짜"])
    macro = macro[["날짜"] + MACRO_LEVEL_COLS].sort_values("날짜").set_index("날짜")

    # 원본 diff/pct_change는 ffill 되기 전 값 기준이라 신뢰할 수 없어 버리고,
    # 여기서 ffill 후 다시 계산한다.
    before_missing = macro.isna().mean()
    macro = macro.ffill()
    after_missing = macro.isna().mean()

    print("=== macro ffill 전/후 결측비율 ===")
    print(pd.DataFrame({"전": before_missing, "후": after_missing}))

    for col in MACRO_LEVEL_COLS:
        macro[f"{col}_diff"] = macro[col].diff()
        macro[f"{col}_pct_change"] = macro[col].pct_change()

    return macro.reset_index()


def prepare_dart(path: Path) -> pd.DataFrame:
    dart = load_csv_like(path, dtype={"종목코드": str}, parse_dates=["날짜"])

    # (날짜, 종목코드, 공시유형)별 건수 집계 -> 유형별 컬럼으로 펼치기
    counts = (
        dart.groupby(["날짜", "종목코드", "pblntf_ty_filter"])
        .size()
        .unstack("pblntf_ty_filter", fill_value=0)
    )
    counts.columns = [f"공시_{c}건수" for c in counts.columns]  # B/C/I -> 공시_B건수 등
    counts["공시_전체건수"] = counts.sum(axis=1)
    counts["공시발생여부"] = (counts["공시_전체건수"] > 0).astype(int)

    print(f"\n공시 데이터: {dart[['날짜','종목코드']].drop_duplicates().shape[0]}개 "
          f"(날짜,종목코드) 조합, 유형별 컬럼: {list(counts.columns)}")

    return counts.reset_index()


def main():
    print(f"기본 데이터 로딩: {BASE_PATH}")
    base = pd.read_csv(BASE_PATH, dtype={"종목코드": str}, parse_dates=["날짜"])
    print(f"  shape: {base.shape}")

    # ------------------------------------------------------------------
    # 1) 거시지표 병합 (날짜 기준 broadcast)
    # ------------------------------------------------------------------
    macro = prepare_macro(MACRO_PATH)
    before = len(base)
    base = base.merge(macro, on="날짜", how="left")
    assert len(base) == before, "macro 병합 후 행 수가 바뀌면 안 됨 (날짜 기준 다대일 병합)"

    macro_cols = [c for c in macro.columns if c != "날짜"]
    macro_missing = base[macro_cols].isna().mean().mean() * 100
    print(f"거시지표 병합 완료. 평균 결측비율: {macro_missing:.2f}%")

    # ------------------------------------------------------------------
    # 2) 공시 병합 ((날짜,종목코드) 기준)
    # ------------------------------------------------------------------
    dart = prepare_dart(DART_PATH)
    before = len(base)
    base = base.merge(dart, on=["날짜", "종목코드"], how="left")
    assert len(base) == before, "dart 병합 후 행 수가 바뀌면 안 됨"

    dart_cols = [c for c in dart.columns if c not in ("날짜", "종목코드")]
    # 공시가 없는 (날짜,종목코드)는 '결측'이 아니라 '0건'이 맞는 값 -> fillna(0)
    base[dart_cols] = base[dart_cols].fillna(0)
    for c in dart_cols:
        if base[c].dtype == float and (base[c] % 1 == 0).all():
            base[c] = base[c].astype(int)

    print(f"공시 병합 완료. 공시발생여부=1인 행 비율: {base['공시발생여부'].mean()*100:.2f}%")

    missing_stock_check = base.groupby("종목코드")["공시_전체건수"].sum()
    zero_stocks = missing_stock_check[missing_stock_check == 0].index.tolist()
    if zero_stocks:
        print(f"⚠ 공시 데이터가 전혀 없는 종목(전 기간 0건): {zero_stocks} "
              f"(corp_code 매핑 실패 종목으로 추정 - 정상적으로 fillna(0) 처리됨)")

    print(f"\n최종 shape: {base.shape} (원본 {before}행에서 컬럼만 늘어남)")
    base.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
