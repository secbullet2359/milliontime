"""
환율/금리/M2/실질금리 같은 거시지표는 하루짜리 diff/pct_change만 있고,
주가처럼 "최근 며칠간 추세가 어땠는지"를 담는 feature(이동평균 등)가 없었음.

이 스크립트는 그 갭을 메운다:
    1) 연속상승/하락일수 - 며칠째 한 방향으로 가고 있는지
    2) N일 이동평균 대비 현재값 - 최근 평균보다 위/아래로 얼마나 벗어났는지
    3) N일 누적변화율 - "오늘 하루"가 아니라 "최근 N일 통틀어" 얼마나 움직였는지
"""

from pathlib import Path

import numpy as np
import pandas as pd

INPUT_PATH = Path("raw_data/merged_dataset_with_alpha.csv")  # add_alpha_feature.py 결과물 위에 이어서
OUTPUT_PATH = Path("raw_data/merged_dataset_with_trend.csv")

TREND_COLS = ["usd_krw", "base_rate", "us_10y_treasury", "fed_funds_rate", "m2", "실질금리"]
WINDOWS = [5, 10, 20]  # 일주일/2주/1개월 정도의 추세를 각각 확인


def add_trend_features(series: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=series.index)

    diff = series.diff()
    sign = np.sign(diff).fillna(0)

    # 연속상승/하락일수: 방향이 바뀌면 0으로 리셋, 같은 방향이면 누적
    streak = np.zeros(len(series))
    current = 0
    prev_sign = 0
    for i, s in enumerate(sign.values):
        if s == 0:
            current = 0
        elif s == prev_sign:
            current += 1
        else:
            current = 1
        streak[i] = current * s  # 양수=연속상승일수, 음수=연속하락일수
        prev_sign = s if s != 0 else prev_sign
    out["연속추세일수"] = streak

    for w in WINDOWS:
        ma = series.rolling(w).mean()
        out[f"MA{w}대비"] = (series - ma) / ma
        out[f"{w}일누적변화율"] = series.pct_change(w)

    return out


def main():
    df = pd.read_csv(INPUT_PATH, dtype={"종목코드": str}, parse_dates=["날짜"])

    # 거시지표는 날짜당 값이 하나(종목 무관)라서, 날짜별로 중복 없이 추세를 계산한 뒤 다시 merge
    macro_daily = df.drop_duplicates(subset=["날짜"]).sort_values("날짜").set_index("날짜")

    trend_frames = []
    for col in TREND_COLS:
        if col not in macro_daily.columns:
            print(f"⚠ {col} 컬럼이 없어 건너뜁니다.")
            continue
        trend = add_trend_features(macro_daily[col])
        trend.columns = [f"{col}_{c}" for c in trend.columns]
        trend_frames.append(trend)

    trend_all = pd.concat(trend_frames, axis=1).reset_index()
    df = df.merge(trend_all, on="날짜", how="left")

    print(f"추세 feature {sum(len(t.columns) for t in trend_frames)}개 추가 완료")
    sample_col = f"{TREND_COLS[0]}_연속추세일수"
    print(f"\n예시 ({sample_col}) 값 분포:")
    print(df[sample_col].describe())

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
