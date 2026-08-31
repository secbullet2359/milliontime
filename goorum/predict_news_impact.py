"""
predict_tomorrow.py가 만든 "오늘 기준 내일 예측"에 대해, 그 예측에 가장 크게
기여한 뉴스 기사가 무엇인지 계산한다 (leave_one_out_analysis.py와 같은 방식,
전체 기간이 아니라 "오늘" 하루만).

출력: dashboard_news_<종목코드>.csv (export_dashboard_news.py와 동일한 스키마라
      대시보드가 그대로 읽을 수 있음)
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_SIZE = 7

MERGED_DATASET_PATH = Path("kospi_top50_data/predict/merged_dataset.csv")
DAILY_EMB_PATH = Path("raw_data/predict/embeddings/daily_news_embeddings.parquet")
ARTICLE_EMB_PATH = Path("raw_data/predict/embeddings/article_embeddings.npy")
ARTICLE_META_PATH = Path("raw_data/predict/embeddings/article_meta.csv")
MODEL_PATH = Path("raw_data/lstm_output/attention_lstm_model.keras")
STOCK_ORDER_PATH = Path("raw_data/lstm_input/stock_order.json")
OUTPUT_DIR = Path("raw_data/dashboard_csv_predict")  # predict_tomorrow.py의 가격/SHAP CSV와 같은 폴더
RECENT_WINDOW_DAYS = 7  # 이보다 오래된 예측대상일 항목은 자동으로 정리


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


def load_stock_order() -> list[str]:
    """
    ⚠ leave_one_out_analysis.py / predict_today_news_score.py와 동일한 이유로,
    이 파일이 없으면 임시 대체를 하지 않고 명확히 멈춤 (Dense(50) 출력 순서가
    틀리면 50개 종목 전체의 결과가 조용히 잘못 배정되는 치명적 지점이기 때문).
    """
    if not STOCK_ORDER_PATH.exists():
        raise FileNotFoundError(
            f"{STOCK_ORDER_PATH}가 없습니다. LSTM 학습 때 저장된 종목 순서 파일을 "
            f"정확한 경로로 지정해주세요."
        )
    with open(STOCK_ORDER_PATH, encoding="utf-8") as f:
        return json.load(f)


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
    today = pd.Timestamp(today_str) if today_str else merged["날짜"].max()
    print(f"'오늘' 기준일: {today.date()}")

    stock_order = load_stock_order()

    daily_emb_raw = load_daily_embeddings_raw(DAILY_EMB_PATH)
    daily_emb, emb_cols = build_daily_calendar_embeddings(daily_emb_raw)

    window_start = today - pd.Timedelta(days=WINDOW_SIZE)
    window_end = today - pd.Timedelta(days=1)
    window = daily_emb.loc[window_start:window_end]
    if len(window) != WINDOW_SIZE:
        raise ValueError(f"{today.date()} 기준 최근 {WINDOW_SIZE}일치 뉴스 임베딩이 부족합니다 "
                          f"(있는 날: {len(window)}일).")

    model = load_model(MODEL_PATH, compile=False)

    original_seq = build_window_features(window, emb_cols)[np.newaxis, :, :]
    scores, attn = model.predict(original_seq, verbose=0)
    original_pred = scores[0]              # (50,)
    attn_flat = attn[0].flatten()          # (7,)

    important_offset = attn_flat.argmax()
    important_day = window.index[important_offset]
    print(f"오늘 예측에서 가장 중요했던 뉴스 날짜: {important_day.date()} "
          f"(가중치 {attn_flat[important_offset]:.3f})")

    article_meta = pd.read_csv(ARTICLE_META_PATH, parse_dates=["일자"])
    article_emb = np.load(ARTICLE_EMB_PATH)

    day_mask = article_meta["일자"] == important_day
    day_idxs = article_meta.index[day_mask].to_numpy()
    if len(day_idxs) == 0:
        print(f"⚠ {important_day.date()}에 해당하는 기사 원문을 찾지 못했습니다.")
        return
    print(f"{important_day.date()}에 있던 기사 수: {len(day_idxs)}건")

    day_embeddings = article_emb[day_idxs]
    impact_matrix = np.zeros((len(day_idxs), len(original_pred)), dtype=np.float32)

    for pos, article_idx in enumerate(day_idxs):
        if len(day_idxs) > 1:
            without_i = np.delete(day_embeddings, pos, axis=0).mean(axis=0)
            new_count = len(day_idxs) - 1
        else:
            without_i = np.zeros_like(day_embeddings[0])
            new_count = 0

        modified_window = window.copy()
        modified_window.loc[important_day, emb_cols] = without_i
        modified_window.loc[important_day, "기사수"] = new_count

        modified_seq = build_window_features(modified_window, emb_cols)[np.newaxis, :, :]
        modified_scores, _ = model.predict(modified_seq, verbose=0)
        impact_matrix[pos] = original_pred - modified_scores[0]

    # ------------------------------------------------------------------
    # 종목별 dashboard_news_<code>.csv로 저장 (export_dashboard_news.py와 동일한 스키마)
    # ------------------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    articles = article_meta.loc[day_idxs]

    for s_idx, code in enumerate(stock_order):
        rows = []
        for pos, (_, art) in enumerate(articles.iterrows()):
            rows.append({
                "예측대상일": today.strftime("%Y-%m-%d"),
                "중요일": important_day.strftime("%Y-%m-%d"),
                "제목": art["제목"],
                "언론사": art["언론사"],
                "URL": art.get("URL", ""),
                "종목코드": code,
                "impact": impact_matrix[pos, s_idx],
            })
        new_df = pd.DataFrame(rows)

        out_path = OUTPUT_DIR / f"dashboard_news_{code}.csv"
        if out_path.exists():
            old_df = pd.read_csv(out_path, dtype={"종목코드": str})
            old_dates = pd.to_datetime(old_df["예측대상일"])
            # 오늘과 같은 날짜(재실행 중복)는 버리고, RECENT_WINDOW_DAYS보다 오래된 것도 정리
            window_start = today - pd.Timedelta(days=RECENT_WINDOW_DAYS)
            keep_mask = (old_dates >= window_start) & (old_dates != today)
            old_df = old_df[keep_mask]
            new_df = pd.concat([old_df, new_df], ignore_index=True)

        new_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n{len(stock_order)}개 종목의 뉴스 영향력 랭킹 저장 완료 (최근 {RECENT_WINDOW_DAYS}일치만 유지) "
          f"-> {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
