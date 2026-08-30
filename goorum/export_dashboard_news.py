"""
leave_one_out_analysis.py의 run_full_analysis() 결과(loo_full_results.csv, wide
포맷 - 종목 50개가 컬럼으로 있음)에서 종목 하나를 골라 그 종목만의
날짜별 뉴스 영향력 랭킹 CSV로 뽑는다. (대시보드 HTML이 바로 읽을 수 있는 형태)

출력 컬럼: 예측대상일, 중요일, 제목, 언론사, URL, impact
"""

from pathlib import Path

import pandas as pd

LOO_RESULTS_PATH = Path("/home/claude/news_collection/raw_data/loo_output/loo_full_results.csv")
OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/dashboard_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STOCK_CODES = None  # None이면 loo 결과에 있는 impact_ 컬럼 전체(=전 종목)에 대해 생성


def main():
    loo = pd.read_csv(LOO_RESULTS_PATH)

    impact_cols = [c for c in loo.columns if c.startswith("impact_")]
    codes = STOCK_CODES or [c.replace("impact_", "") for c in impact_cols]

    meta_cols = ["예측대상일", "중요일", "제목", "언론사", "URL"]
    meta_cols = [c for c in meta_cols if c in loo.columns]

    for code in codes:
        col = f"impact_{code}"
        if col not in loo.columns:
            print(f"⚠ {code}에 대한 impact 컬럼이 없습니다. 건너뜁니다.")
            continue

        sub = loo[meta_cols + [col]].rename(columns={col: "impact"})
        sub = sub.sort_values(["예측대상일"], ascending=True)

        out_path = OUTPUT_DIR / f"dashboard_news_{code}.csv"
        sub.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"{len(codes)}개 종목 뉴스랭킹 CSV 생성 완료 -> {OUTPUT_DIR}")
    example = OUTPUT_DIR / f"dashboard_news_{codes[0]}.csv"
    print(f"예시: {example} ({len(pd.read_csv(example))}행)")


if __name__ == "__main__":
    main()
