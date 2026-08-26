"""
train_attention_lstm.py 결과물(news_influence_score_per_stock.csv)을
merged_dataset.csv에 (날짜, 종목코드) 기준으로 합친다. (방향 C)

방향 A(시장 전체 공통 값)와 달리, 이제는 종목마다 다른 값이라
날짜만으로 broadcast하면 안 되고 종목코드까지 정확히 맞춰서 병합해야 함.
"""

from pathlib import Path

import pandas as pd

MERGED_DATASET_PATH = Path("/mnt/user-data/outputs/merged_dataset.csv")
NEWS_SCORE_PATH = Path("/home/claude/news_collection/raw_data/lstm_output/news_influence_score_per_stock.csv")
OUTPUT_PATH = Path("/home/claude/news_collection/raw_data/merged_dataset_with_news.csv")


def main():
    merged = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str})
    merged["날짜"] = pd.to_datetime(merged["날짜"])

    news_score = pd.read_csv(NEWS_SCORE_PATH, dtype={"종목코드": str}, parse_dates=["날짜"])

    before_rows = len(merged)
    result = merged.merge(news_score, on=["날짜", "종목코드"], how="left")

    coverage = result["news_influence_score_per_stock"].notna().mean() * 100
    print(f"병합 결과: {before_rows}행 -> {len(result)}행 (행 수는 그대로여야 정상)")
    print(f"news_influence_score_per_stock가 채워진 비율: {coverage:.1f}%")
    print("(100%가 아닌 건 정상 - LSTM 학습에 쓰인 뉴스 데이터 기간 밖의 날짜는 결측으로 남음)")

    # 종목별로 값이 실제로 다른지 확인 (같은 날짜 내에서 종목 간 분산이 0이 아니어야 정상)
    same_day_std = result.groupby("날짜")["news_influence_score_per_stock"].std()
    print(f"같은 날짜 내 종목 간 값의 표준편차 평균: {same_day_std.mean():.6f} "
          f"(0에 가까우면 종목 차별화가 거의 없다는 뜻 - 학습이 잘 안 된 신호일 수 있음)")

    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
