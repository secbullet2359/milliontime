"""
merged_dataset_with_news_macro_dart.csv에 "시장 대비 초과수익(알파)" feature를 추가한다.

알파 = 그 종목의 등락률 - 그날 50개 종목 평균 등락률
    -> "시장 전체가 다 같이 움직인 것"과 "이 종목만의 이유로 움직인 것"을 분리.
       사용자가 얘기한 "돈이 다른 종목으로 흘러가는" 효과를 근사하는 지표.
"""

from pathlib import Path

import pandas as pd

INPUT_PATH = Path("raw_data/merged_dataset_with_news_macro_dart.csv")
OUTPUT_PATH = Path("raw_data/merged_dataset_with_alpha.csv")


def main():
    df = pd.read_csv(INPUT_PATH, dtype={"종목코드": str}, parse_dates=["날짜"])

    market_avg = df.groupby("날짜")["등락률"].transform("mean")
    df["시장대비알파"] = df["등락률"] - market_avg
    df["시장평균등락률"] = market_avg

    print(f"알파 feature 추가 완료. 평균(0에 가까워야 정상): {df['시장대비알파'].mean():.6f}")
    print(f"표준편차: {df['시장대비알파'].std():.4f} (원래 등락률 표준편차: {df['등락률'].std():.4f}와 비교)")

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
