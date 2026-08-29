"""
embed_daily_news.py 결과물(daily_news_embeddings.parquet 또는 .csv)의
결측치/공백 구간을 진단한다.

확인하는 것:
    1) 전체 커버 기간과 실제 존재하는 날짜 수 (달력일 기준 빠진 날 찾기)
    2) 임베딩 컬럼(e0~e767)에 NaN이 있는지
    3) 기사수가 0인 날 (뉴스가 실제로 없었는지, 수집이 안 된 건지 구분 필요)
    4) 최근 구간(예: 2026-04-06 이후)이 실제로 비어있는지 - XGBoost 단계에서
       발견됐던 결측 구간이 이 임베딩 파일 자체에서부터 비어있는지, 아니면
       그 이후 병합 과정에서 생긴 문제인지를 구분하기 위함
"""

from pathlib import Path

import numpy as np
import pandas as pd

# 실제 파일 경로로 수정
EMBEDDING_PATH = Path("daily_news_embeddings.parquet")  # 없으면 .csv로 자동 대체 시도


def load_embedding_file(path: Path) -> pd.DataFrame:
    if path.exists():
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)

    csv_alt = path.with_suffix(".csv")
    if csv_alt.exists():
        print(f"⚠ {path.name} 없음 -> {csv_alt.name}로 대체 로딩 "
              f"(pyarrow 미설치로 CSV에 저장됐을 가능성)")
        return pd.read_csv(csv_alt)

    raise FileNotFoundError(f"{path} / {csv_alt} 둘 다 없습니다. 경로를 확인하세요.")


def main():
    df = load_embedding_file(EMBEDDING_PATH)
    df["날짜"] = pd.to_datetime(df["날짜"])
    df = df.sort_values("날짜").reset_index(drop=True)

    emb_cols = [c for c in df.columns if c.startswith("e")]

    print(f"파일 shape: {df.shape} (임베딩 차원: {len(emb_cols)})")
    print(f"날짜 범위: {df['날짜'].min().date()} ~ {df['날짜'].max().date()}")

    # 1) 달력일 기준으로 빠진 날짜 찾기
    full_range = pd.date_range(df["날짜"].min(), df["날짜"].max(), freq="D")
    missing_dates = full_range.difference(df["날짜"])
    print(f"\n실제 존재하는 날짜 수: {len(df)} / 전체 달력일수 {len(full_range)}")
    print(f"완전히 빠진 날짜 수: {len(missing_dates)}")
    if len(missing_dates) > 0:
        print(f"  빠진 날짜 예시(앞 5개): {[d.date() for d in missing_dates[:5]]}")
        print(f"  빠진 날짜 예시(뒤 5개): {[d.date() for d in missing_dates[-5:]]}")

        # 연속으로 빠진 구간(공백) 찾기 - 하루씩 흩어진 결측과 몇 달짜리 공백을 구분
        gap_groups = (missing_dates.to_series().diff() != pd.Timedelta(days=1)).cumsum()
        gaps = missing_dates.to_series().groupby(gap_groups).agg(["min", "max", "count"])
        print(f"\n연속 공백 구간 Top 5 (길이 기준):")
        print(gaps.sort_values("count", ascending=False).head(5))

    # 2) 임베딩 컬럼 자체의 NaN 체크 (달력일 재정렬 전, 원본 파일 단계)
    n_nan = df[emb_cols].isna().sum().sum()
    print(f"\n임베딩 컬럼(e0~e{len(emb_cols)-1}) 내 NaN 총 개수: {n_nan} "
          f"({'정상 - 이 단계에서는 보통 없어야 함' if n_nan == 0 else '⚠ 확인 필요'})")

    # 3) 기사수 0인 날
    if "기사수" in df.columns:
        zero_days = (df["기사수"] == 0).sum()
        print(f"\n기사수=0인 날: {zero_days}일")
        print(df["기사수"].describe())

    # 4) 특정 구간 직접 확인 (XGBoost 단계에서 발견된 공백과 비교)
    check_start, check_end = "2026-04-01", "2026-08-19"
    window = df[(df["날짜"] >= check_start) & (df["날짜"] <= check_end)]
    print(f"\n=== {check_start} ~ {check_end} 구간 확인 ===")
    print(f"이 구간에 존재하는 날짜 수: {len(window)} "
          f"(달력일 기준 예상: {(pd.Timestamp(check_end)-pd.Timestamp(check_start)).days + 1}일)")
    if len(window) == 0:
        print("⚠ 이 임베딩 파일 자체에 이 구간이 통째로 없습니다 "
              "-> 뉴스 수집/임베딩이 여기까지 안 된 것 (병합 문제가 아니라 수집 단계 문제)")
    elif len(window) < (pd.Timestamp(check_end) - pd.Timestamp(check_start)).days + 1:
        print("⚠ 이 구간에 부분적으로 빠진 날짜가 있습니다 (위 '빠진 날짜' 목록 참고)")
    else:
        print("이 구간은 임베딩 파일 자체에는 빠짐없이 존재합니다 "
              "-> XGBoost 단계 이후(시퀀스 생성/병합)에서 문제가 생겼을 가능성")


if __name__ == "__main__":
    main()
