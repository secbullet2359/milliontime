"""
Attention-LSTM 학습 데이터 준비 (방향 C: 출력을 50개 종목 벡터로)

핵심 변경점 (방향 A -> C):
    - 기존: target = 날짜별 "시장 평균 수익률" 1개 (스칼라)
    - 변경: target = 날짜별 "50개 종목 각각의 수익률" (50차원 벡터)
    - 입력(X_seq)은 그대로 유지 - 뉴스는 종목을 구분하지 않는 시장 공통 정보라서
      시퀀스 자체는 안 바뀜. 대신 출력을 50차원으로 늘려서, LSTM이 "이 공유된
      뉴스 흐름에 종목마다 얼마나 다르게(다른 방향으로) 반응하는지"를
      Dense(50) 레이어의 종목별 가중치로 학습하게 함.
    - 거래정지 등으로 그날 특정 종목의 수익률이 무효면 NaN으로 남겨두고
      (행을 통째로 버리지 않음), 학습 시 마스킹된 loss로 그 종목만 제외하고 계산.

⚠ stock_order.json에 저장된 종목코드 순서가 Dense(50) 출력의 각 열 순서와
   정확히 일치해야 함 - 이후 학습/추론/병합 전 단계에서 이 순서를 그대로 재사용.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

MERGED_DATASET_PATH = Path("/mnt/user-data/outputs/merged_dataset.csv")
DAILY_EMB_PATH = Path("/home/claude/news_collection/raw_data/embeddings/daily_news_embeddings.csv")
OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/lstm_input")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SIZE = 7


def build_stock_return_matrix(merged: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    날짜(행) x 종목코드(열) 형태의 수익률 행렬을 만든다.
    거래정지/재상장첫날에 해당하는 값은 NaN으로 남김 (버리지 않고 마스킹으로 처리).
    """
    df = merged[["날짜", "종목코드", "종가", "거래정지", "재상장첫날"]].copy()
    df = df.sort_values(["종목코드", "날짜"])

    df["수익률"] = df.groupby("종목코드")["종가"].pct_change()

    invalid = (
        df["거래정지"].astype(bool)
        | df["재상장첫날"].astype(bool)
        | df.groupby("종목코드")["거래정지"].shift(1).fillna(False).astype(bool)
    )
    df.loc[invalid, "수익률"] = np.nan

    stock_order = sorted(df["종목코드"].unique().tolist())  # 고정된 순서 - 이후 전 단계에서 재사용
    wide = df.pivot(index="날짜", columns="종목코드", values="수익률")
    wide = wide[stock_order]  # 컬럼 순서를 명시적으로 고정

    n_total = wide.size
    n_valid = wide.notna().sum().sum()
    print(f"종목별 수익률 행렬: {wide.shape} (날짜 x 종목), "
          f"유효값 {n_valid}/{n_total} ({n_valid/n_total*100:.1f}%)")

    return wide, stock_order


def build_daily_calendar_embeddings(daily_emb: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """뉴스 임베딩을 달력일(매일) 기준으로 재정렬, 기사 없는 날은 0벡터+기사수0으로 채움."""
    daily_emb = daily_emb.copy()
    daily_emb["날짜"] = pd.to_datetime(daily_emb["날짜"])
    daily_emb = daily_emb.set_index("날짜").sort_index()

    emb_cols = [c for c in daily_emb.columns if c.startswith("e")]

    full_range = pd.date_range(daily_emb.index.min(), daily_emb.index.max(), freq="D")
    daily_emb = daily_emb.reindex(full_range)
    daily_emb[emb_cols] = daily_emb[emb_cols].fillna(0.0)
    daily_emb["기사수"] = daily_emb["기사수"].fillna(0).astype(int)

    print(f"뉴스 임베딩 달력일 재정렬: {len(daily_emb)}일 "
          f"({daily_emb.index.min().date()} ~ {daily_emb.index.max().date()}), "
          f"기사 0건인 날: {(daily_emb['기사수'] == 0).sum()}일")

    return daily_emb, emb_cols


def build_sequences(daily_emb: pd.DataFrame, emb_cols: list[str],
                     stock_return_wide: pd.DataFrame, window_size: int = WINDOW_SIZE):
    """
    거래일 D 하나마다: D 이전 7일(달력일)의 뉴스 시퀀스(X) + D일의 50종목 수익률 벡터(y).
    y는 NaN을 포함할 수 있음 (학습 시 마스킹 처리).
    """
    sequences, targets, seq_dates = [], [], []
    stock_return_wide.index = pd.to_datetime(stock_return_wide.index)

    for d in stock_return_wide.index:
        y_row = stock_return_wide.loc[d].values  # (50,), NaN 포함 가능
        if np.isnan(y_row).all():
            continue  # 그날 전 종목이 무효면(사실상 없음) 스킵

        window_start = d - pd.Timedelta(days=window_size)
        window_end = d - pd.Timedelta(days=1)
        if window_start < daily_emb.index.min():
            continue

        window = daily_emb.loc[window_start:window_end]
        if len(window) != window_size:
            continue

        emb_part = window[emb_cols].values
        count_part = np.log1p(window["기사수"].values).reshape(-1, 1)
        seq = np.concatenate([emb_part, count_part], axis=1)  # (7, 769)

        sequences.append(seq)
        targets.append(y_row)
        seq_dates.append(d)

    X_seq = np.array(sequences, dtype=np.float32)
    y_seq = np.array(targets, dtype=np.float32)  # (샘플수, 50), NaN 포함 가능

    print(f"\n시퀀스 생성 완료: X_seq {X_seq.shape}, y_seq {y_seq.shape} "
          f"(y_seq의 NaN 비율: {np.isnan(y_seq).mean()*100:.1f}%)")
    return X_seq, y_seq, seq_dates


def main():
    print("정형 데이터(merged_dataset) 로딩...")
    merged = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str})
    merged["날짜"] = pd.to_datetime(merged["날짜"])

    print("뉴스 임베딩 로딩...")
    daily_emb_raw = pd.read_csv(DAILY_EMB_PATH)

    stock_return_wide, stock_order = build_stock_return_matrix(merged)
    daily_emb, emb_cols = build_daily_calendar_embeddings(daily_emb_raw)

    X_seq, y_seq, seq_dates = build_sequences(daily_emb, emb_cols, stock_return_wide)

    if len(X_seq) == 0:
        print("\n⚠ 생성된 시퀀스가 0개입니다. 날짜 범위가 겹치는지 확인하세요.")
        return

    np.savez(OUTPUT_DIR / "lstm_sequences.npz", X_seq=X_seq, y_seq=y_seq)
    pd.DataFrame({"날짜": seq_dates}).to_csv(
        OUTPUT_DIR / "lstm_sequence_dates.csv", index=False, encoding="utf-8-sig"
    )
    with open(OUTPUT_DIR / "stock_order.json", "w", encoding="utf-8") as f:
        json.dump(stock_order, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료: {OUTPUT_DIR / 'lstm_sequences.npz'}")
    print(f"종목 순서 저장: {OUTPUT_DIR / 'stock_order.json'} ({len(stock_order)}개 종목)")
    print(f"기간: {min(seq_dates).date()} ~ {max(seq_dates).date()}, 샘플 수: {len(seq_dates)}")


if __name__ == "__main__":
    main()
