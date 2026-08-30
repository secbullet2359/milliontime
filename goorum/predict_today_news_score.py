"""
내일 예측 파이프라인 - 1단계: 오늘의 news_influence_score_per_stock 추론

⚠ prepare_lstm_dataset.py와는 다른 스크립트입니다. 그 스크립트는 "정답(y)이 있는
   과거 데이터로 학습셋을 만드는" 용도라 예측(정답 없음)에는 쓸 수 없습니다.
   이 스크립트는 정답 없이, 딱 하루치 시퀀스만 만들어서 predict()만 합니다.

경로 규칙: kospi_top50_data/predict/, raw_data/predict/ 구조를 그대로 따름
(A옵션: 정형데이터의 마지막 날짜를 "오늘"로 보고, 그 기준 최근 7일 뉴스를 사용)
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_SIZE = 7

MERGED_DATASET_PATH = Path("kospi_top50_data/predict/merged_dataset.csv")
DAILY_EMB_PATH = Path("raw_data/predict/embeddings/daily_news_embeddings.parquet")
MODEL_PATH = Path("raw_data/lstm_output/attention_lstm_model.keras")  # 학습 때 저장된 모델 (경로 확인 필요)
STOCK_ORDER_PATH = Path("raw_data/lstm_input/stock_order.json")       # 학습 때 저장된 종목순서 (경로 확인 필요)
OUTPUT_PATH = Path("raw_data/predict/today_news_score.csv")


def load_daily_embeddings_raw(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        try:
            return pd.read_parquet(path)
        except ImportError:
            csv_alt = path.with_suffix(".csv")
            if csv_alt.exists():
                print(f"⚠ parquet 리더가 없어 {csv_alt.name}로 대체 로딩")
                return pd.read_csv(csv_alt)
            raise
    return pd.read_csv(path)


def build_daily_calendar_embeddings(daily_emb: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    daily_emb = daily_emb.copy()
    daily_emb["날짜"] = pd.to_datetime(daily_emb["날짜"])
    daily_emb = daily_emb.set_index("날짜").sort_index()

    emb_cols = [c for c in daily_emb.columns if c.startswith("e")]

    full_range = pd.date_range(daily_emb.index.min(), daily_emb.index.max(), freq="D")
    daily_emb = daily_emb.reindex(full_range)
    daily_emb[emb_cols] = daily_emb[emb_cols].fillna(0.0)
    daily_emb["기사수"] = daily_emb["기사수"].fillna(0).astype(int)

    return daily_emb, emb_cols


def build_window_features(window: pd.DataFrame, emb_cols: list[str]) -> np.ndarray:
    emb_part = window[emb_cols].values
    count_part = np.log1p(window["기사수"].values).reshape(-1, 1)
    return np.concatenate([emb_part, count_part], axis=1)


def load_stock_order(merged: pd.DataFrame) -> list[str]:
    """
    학습 때 저장해둔 stock_order.json을 우선 사용 (Dense(50) 출력 열 순서와
    정확히 일치해야 하므로 이게 원칙). 파일이 없으면 이 정형데이터에서
    sorted(유니크 종목코드)로 대체 생성하되, 같은 50개 종목 구성이라면
    sorted() 특성상 동일한 순서가 나오므로 대부분 안전함 - 다만 학습 때와
    종목 구성이 달라졌다면(상장폐지/신규 등) 절대 안전하지 않으니 주의.
    """
    if STOCK_ORDER_PATH.exists():
        with open(STOCK_ORDER_PATH, encoding="utf-8") as f:
            return json.load(f)

    print(f"⚠ {STOCK_ORDER_PATH}가 없어, 정형데이터에서 종목순서를 새로 만듭니다 "
          f"(학습 때와 종목 구성이 동일해야 안전합니다).")
    return sorted(merged["종목코드"].unique().tolist())


def main(today_str: str | None = None):
    import tensorflow as tf
    try:
        from tensorflow.keras.saving import register_keras_serializable
    except (ImportError, AttributeError):
        from tensorflow.keras.utils import register_keras_serializable

    @register_keras_serializable(package="AttentionLSTM")
    class WeightedSum(tf.keras.layers.Layer):
        def call(self, inputs):
            lstm_out, attention_weights = inputs
            return tf.reduce_sum(lstm_out * attention_weights, axis=1)

    from tensorflow.keras.models import load_model

    merged = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str}, parse_dates=["날짜"])

    # "오늘" = 명시적으로 안 주면 정형데이터의 마지막 날짜로 자동 설정 (A옵션)
    today = pd.Timestamp(today_str) if today_str else merged["날짜"].max()
    print(f"'오늘' 기준일: {today.date()} "
          f"({'직접 지정' if today_str else '정형데이터 마지막 날짜로 자동 설정'})")

    daily_emb_raw = load_daily_embeddings_raw(DAILY_EMB_PATH)
    daily_emb, emb_cols = build_daily_calendar_embeddings(daily_emb_raw)

    window_start = today - pd.Timedelta(days=WINDOW_SIZE)
    window_end = today - pd.Timedelta(days=1)
    window = daily_emb.loc[window_start:window_end]

    if len(window) != WINDOW_SIZE:
        raise ValueError(
            f"{today.date()} 기준 최근 {WINDOW_SIZE}일치 뉴스 임베딩이 부족합니다 "
            f"(있는 날: {len(window)}일, 필요한 범위: {window_start.date()} ~ {window_end.date()}, "
            f"실제 임베딩 범위: {daily_emb.index.min().date()} ~ {daily_emb.index.max().date()}). "
            f"뉴스 임베딩을 이 기간으로 다시 만들어야 합니다."
        )
    print(f"뉴스 윈도우: {window.index.min().date()} ~ {window.index.max().date()} "
          f"(기사수: {window['기사수'].tolist()})")

    stock_order = load_stock_order(merged)

    model = load_model(MODEL_PATH, compile=False)  # predict만 할 거라 compile 불필요

    X = build_window_features(window, emb_cols)[np.newaxis, :, :]
    scores, attn = model.predict(X, verbose=0)

    result = pd.DataFrame({
        "종목코드": stock_order,
        "news_influence_score_per_stock": scores[0],
    })
    result.insert(0, "날짜", today.strftime("%Y-%m-%d"))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    attn_flat = attn[0].flatten()
    important_offset = attn_flat.argmax()
    important_day = window.index[important_offset]
    print(f"\n오늘 예측에서 가장 중요했던 뉴스 날짜: {important_day.date()} "
          f"(가중치 {attn_flat[important_offset]:.3f})")
    print(f"저장 완료: {OUTPUT_PATH} ({len(result)}개 종목)")
    print(result.sort_values("news_influence_score_per_stock", ascending=False).head(5))


if __name__ == "__main__":
    main()  # 필요하면 main("2026-08-28") 처럼 날짜를 직접 지정 가능
