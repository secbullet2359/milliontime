"""
Leave-One-Out 기사 단위 영향력 분석

두 가지 사용 방식:
    1) analyze_date(): 특정 (날짜, 종목코드) 하나를 대상으로 상세 분석 + 출력
    2) run_full_analysis(): 전체 기간의 모든 거래일 x 50개 종목을 일괄 처리

전체 기간 처리 시 효율화 포인트:
    - Attention(어느 날이 중요한지)은 종목과 무관하게 공유 뉴스 시퀀스에서만
      계산되므로, 날짜당 "중요한 날/그날 기사 목록"은 한 번만 구하면 됨
    - 기사 하나를 뺐을 때의 영향력도 50개 종목 출력을 한 번에 받아오면 되므로,
      종목별로 반복 예측할 필요가 없음 (계산량 50배 절감)
    - 임베딩 단계에서 겪었던 장시간 작업 문제를 감안해, 날짜 단위 체크포인트/
      재시작 기능을 기본으로 포함

⚠ 이 샌드박스는 TensorFlow가 없어 실제 모델 추론은 못 해봤음. 데이터 연결/정렬/
   체크포인트 로직은 가짜 모델로 전부 검증했음. 실제 실행은 TensorFlow가 설치된
   환경에서.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW_SIZE = 7  # prepare_lstm_dataset.py와 반드시 동일한 값을 유지해야 함 (학습 때와 같은 윈도우 크기)


def _register_weighted_sum_layer():
    """
    train_attention_lstm.py에서 학습한 모델은 WeightedSum이라는 커스텀 레이어를 씀.
    모델을 불러오기(load_model) 전에 이 클래스가 반드시 import(정의)되어 있어야
    Keras가 저장된 모델을 복원할 수 있음 (register_keras_serializable로 등록된 이름을
    찾는 방식이라, 이 함수를 호출해서 클래스를 정의/등록해두는 것).
    train_attention_lstm.py와 정의가 반드시 동일해야 함 (구조가 다르면 로딩은 되어도
    실제 계산이 달라짐).
    """
    import tensorflow as tf
    from tensorflow import keras

    @keras.saving.register_keras_serializable(package="AttentionLSTM")
    class WeightedSum(keras.layers.Layer):
        def call(self, inputs):
            lstm_out, attention_weights = inputs
            return tf.reduce_sum(lstm_out * attention_weights, axis=1)

    return WeightedSum


_register_weighted_sum_layer()  # 모듈 로딩 시점에 바로 등록


def load_daily_embeddings_raw(path: Path) -> pd.DataFrame:
    """
    daily_news_embeddings 파일 로더. parquet이 기본이지만, 확장자가 .csv이거나
    pyarrow/fastparquet이 없는 환경이면 CSV로도 시도.
    """
    if path.suffix == ".parquet":
        try:
            return pd.read_parquet(path)
        except ImportError:
            csv_alt = path.with_suffix(".csv")
            if csv_alt.exists():
                print(f"⚠ parquet 리더(pyarrow 등)가 없어 {csv_alt.name}로 대체 로딩")
                return pd.read_csv(csv_alt)
            raise
    return pd.read_csv(path)


def build_daily_calendar_embeddings(daily_emb: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    (prepare_lstm_dataset.py의 동일 함수를 그대로 복사해온 것 - 주피터 노트북 등에서
     cross-file import가 불안정할 수 있어, 다른 파일에 의존하지 않도록 자체 포함시킴.
     두 파일을 같이 수정할 일이 생기면 이 함수도 같이 맞춰줘야 함)

    뉴스 임베딩을 달력일(매일) 기준으로 재정렬, 기사 없는 날은 0벡터+기사수0으로 채움.
    """
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

DAILY_EMB_PATH = Path("/home/claude/news_collection/raw_data/embeddings/daily_news_embeddings.parquet")
ARTICLE_EMB_PATH = Path("/home/claude/news_collection/raw_data/embeddings/article_embeddings.npy")
ARTICLE_META_PATH = Path("/home/claude/news_collection/raw_data/embeddings/article_meta.csv")
MODEL_PATH = Path("/home/claude/news_collection/raw_data/lstm_output/attention_lstm_model.keras")
STOCK_ORDER_PATH = Path("/home/claude/news_collection/raw_data/lstm_input/stock_order.json")

# prepare_lstm_dataset.py가 만들어둔, "실제 학습/예측에 쓰인 거래일 목록"을 그대로 재사용
# (거래일 + 7일치 뉴스가 확보된 날만 이미 걸러져 있음)
VALID_DATES_PATH = Path("/home/claude/news_collection/raw_data/lstm_input/lstm_sequence_dates.csv")

OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/loo_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = OUTPUT_DIR / "progress.json"
RESULT_FILE = OUTPUT_DIR / "loo_full_results.csv"


def load_stock_order() -> list[str]:
    with open(STOCK_ORDER_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_window_features(window: pd.DataFrame, emb_cols: list[str]) -> np.ndarray:
    """7일치 (임베딩+로그변환 기사수)를 이어붙여 (7, 769) 시퀀스로."""
    emb_part = window[emb_cols].values
    count_part = np.log1p(window["기사수"].values).reshape(-1, 1)
    return np.concatenate([emb_part, count_part], axis=1)


def compute_loo_for_date(model, daily_emb, emb_cols, article_meta, article_emb,
                          target_date: pd.Timestamp):
    """
    한 날짜에 대해: 원 예측(50종목) + 중요한 날 특정 + 그날 기사별 50종목 영향력 계산.
    반환: important_day, articles_df(그날 기사 메타), impact_matrix(기사수 x 50)
          -> 데이터가 부족하거나 기사가 없으면 (None, None, None)
    """
    window_start = target_date - pd.Timedelta(days=WINDOW_SIZE)
    window_end = target_date - pd.Timedelta(days=1)
    window = daily_emb.loc[window_start:window_end]
    if len(window) != WINDOW_SIZE:
        return None, None, None

    original_seq = build_window_features(window, emb_cols)[np.newaxis, :, :]
    scores, attn = model.predict(original_seq, verbose=0)
    original_pred = scores[0]              # (50,) - 50종목 전체
    attn_flat = attn[0].flatten()          # (7,)

    important_offset = attn_flat.argmax()
    important_day = window.index[important_offset]

    day_mask = article_meta["일자"] == important_day
    day_idxs = article_meta.index[day_mask].to_numpy()
    if len(day_idxs) == 0:
        return important_day, None, None

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
        impact_matrix[pos] = original_pred - modified_scores[0]   # (50,) 종목별 영향력

    return important_day, article_meta.loc[day_idxs], impact_matrix


def analyze_date(target_date_str: str, stock_code: str, top_n: int = 5):
    """특정 (날짜, 종목코드) 하나를 대상으로 상세 분석 + 콘솔 출력 (인터랙티브 조회용)."""
    from tensorflow.keras.models import load_model

    target_date = pd.Timestamp(target_date_str)
    stock_order = load_stock_order()
    if stock_code not in stock_order:
        raise ValueError(f"'{stock_code}'가 stock_order에 없습니다.")
    stock_idx = stock_order.index(stock_code)

    daily_emb_raw = load_daily_embeddings_raw(DAILY_EMB_PATH)
    daily_emb, emb_cols = build_daily_calendar_embeddings(daily_emb_raw)
    article_meta = pd.read_csv(ARTICLE_META_PATH, parse_dates=["일자"])
    article_emb = np.load(ARTICLE_EMB_PATH)
    model = load_model(MODEL_PATH)

    important_day, articles, impact_matrix = compute_loo_for_date(
        model, daily_emb, emb_cols, article_meta, article_emb, target_date
    )
    if important_day is None:
        print(f"⚠ {target_date.date()} 기준 최근 {WINDOW_SIZE}일 뉴스 데이터가 부족합니다.")
        return None
    if articles is None:
        print(f"⚠ 중요한 날({important_day.date()})에 해당하는 기사 원문을 찾지 못했습니다.")
        return None

    print(f"예측 대상: {target_date.date()} / {stock_code}")
    print(f"-> 가장 중요한 날: {important_day.date()} / 기사 {len(articles)}건")

    impacts = impact_matrix[:, stock_idx]
    result = articles.assign(impact=impacts, abs_impact=np.abs(impacts)) \
                      .sort_values("abs_impact", ascending=False)

    print(f"\n=== 영향력 Top {top_n} 기사 ===")
    print(result[["제목", "언론사", "impact"]].head(top_n).to_string(index=False))
    return result


# ------------------------------------------------------------------
# 전체 기간 x 전체 종목 일괄 처리 (체크포인트 지원)
# ------------------------------------------------------------------
def load_progress() -> int:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)["completed_dates"]
    return 0


def save_progress(n: int):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"completed_dates": n}, f)


def run_full_analysis():
    from tensorflow.keras.models import load_model

    stock_order = load_stock_order()
    daily_emb_raw = load_daily_embeddings_raw(DAILY_EMB_PATH)
    daily_emb, emb_cols = build_daily_calendar_embeddings(daily_emb_raw)
    article_meta = pd.read_csv(ARTICLE_META_PATH, parse_dates=["일자"])
    article_emb = np.load(ARTICLE_EMB_PATH)
    model = load_model(MODEL_PATH)

    target_dates = pd.read_csv(VALID_DATES_PATH, parse_dates=["날짜"])["날짜"].tolist()
    print(f"전체 분석 대상 날짜 수: {len(target_dates)} x 종목 {len(stock_order)}개")

    start_idx = load_progress()
    if start_idx > 0:
        print(f"이전 진행상황 발견: {start_idx}/{len(target_dates)}일까지 완료 -> 이어서 진행")

    write_header = start_idx == 0
    mode = "w" if write_header else "a"

    for i in range(start_idx, len(target_dates)):
        target_date = target_dates[i]
        important_day, articles, impact_matrix = compute_loo_for_date(
            model, daily_emb, emb_cols, article_meta, article_emb, target_date
        )

        if important_day is not None and articles is not None:
            # wide 형식: 기사 하나당 한 행, 종목 50개는 컬럼으로 (long으로 펼치면
            # 전체 행수가 날짜x기사x종목으로 폭증하므로 파일 크기 관리를 위해 wide 유지)
            rows = []
            for pos, (article_idx, article_row) in enumerate(articles.iterrows()):
                row = {
                    "예측대상일": target_date.strftime("%Y-%m-%d"),
                    "중요일": important_day.strftime("%Y-%m-%d"),
                    "기사ID": article_row.get("기사ID", article_idx),
                    "제목": article_row["제목"],
                    "언론사": article_row["언론사"],
                    "URL": article_row.get("URL", ""),
                }
                for s_idx, s_code in enumerate(stock_order):
                    row[f"impact_{s_code}"] = impact_matrix[pos, s_idx]
                rows.append(row)

            chunk_df = pd.DataFrame(rows)
            chunk_df.to_csv(RESULT_FILE, mode=mode, header=write_header, index=False, encoding="utf-8-sig")
            mode, write_header = "a", False  # 이후로는 계속 append

        save_progress(i + 1)
        if (i + 1) % 50 == 0 or (i + 1) == len(target_dates):
            print(f"진행: {i + 1}/{len(target_dates)} ({target_date.date()}) 완료, 체크포인트 저장")

    print(f"\n전체 완료. 결과 저장: {RESULT_FILE}")


if __name__ == "__main__":
    # 단일 사례 조회 예시
    # analyze_date(target_date_str="2022-10-15", stock_code="005930")

    # 전체 기간 x 전체 종목 일괄 처리
    run_full_analysis()
