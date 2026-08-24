"""
통합된 뉴스 CSV(bigkinds_combined.csv 등)를 입력으로 받아
    1) 기사 하나하나를 다국어 sentence-transformer로 임베딩
    2) 같은 날짜의 기사 임베딩들을 평균 풀링해서 "하루 하나의 벡터"로 압축
    3) 기사 수(그날 얼마나 많은 기사가 있었는지)도 별도 컬럼으로 보존
한다.

모델: paraphrase-multilingual-mpnet-base-v2
    - 50개 이상 언어 지원 (한국어/영어 모두 포함) -> 빅카인즈(한국어) +
      GDELT/NewsAPI(영어) 기사를 같은 벡터공간에 태우기 위한 필수 조건
    - 768차원, 속도/품질 균형이 좋아 대량 배치 처리에 적합
    - 필요시 intfloat/multilingual-e5-large 등으로 교체 가능 (단, e5는
      "query: "/"passage: " 접두어를 텍스트 앞에 붙여야 하는 등 사용법이 다름)

⚠ 이 스크립트는 인터넷에서 모델을 내려받아야 하므로, 네트워크가 되는
   환경(사용자 PC)에서 실행해야 함:
   pip install sentence-transformers
"""

from pathlib import Path

import numpy as np
import pandas as pd

try:
    from tqdm import tqdm
except ImportError:  # tqdm 없어도 동작하게 (진행률 표시만 생략)
    def tqdm(iterable, **kwargs):
        return iterable

# ------------------------------------------------------------------
# 경로/설정
# ------------------------------------------------------------------
INPUT_CSV = Path("/home/claude/news_collection/raw_data/bigkinds_combined.csv")
OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/embeddings")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
BATCH_SIZE = 64
MAX_TEXT_LEN = 500  # 제목+본문이 짧아서(본문 200자) 사실상 안전장치 용도


def build_text_column(df: pd.DataFrame) -> pd.Series:
    """임베딩에 넣을 텍스트를 만든다: 제목 + 본문(요약)."""
    title = df.get("제목", "").fillna("")
    body = df.get("본문", "").fillna("")
    # 해외뉴스(GDELT 등)를 나중에 합칠 때는 '요약' 컬럼명이 다를 수 있으므로 대체 처리
    if body.eq("").all() and "요약" in df.columns:
        body = df["요약"].fillna("")

    text = (title + ". " + body).str.slice(0, MAX_TEXT_LEN)
    return text


def embed_articles(texts: list[str], model_name: str = MODEL_NAME) -> np.ndarray:
    """기사 단위 임베딩. 실제 실행 시 sentence-transformers가 필요."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,  # 코사인 유사도 기반 후속 분석을 염두에 두고 정규화
    )
    return embeddings


def pool_by_day(df: pd.DataFrame, embeddings: np.ndarray) -> pd.DataFrame:
    """같은 날짜의 기사 임베딩을 평균 풀링해서 하루 1개 벡터로 압축."""
    df = df.copy()
    df["_emb_idx"] = np.arange(len(df))

    rows = []
    for date, group in tqdm(df.groupby("일자"), desc="일자별 풀링"):
        idxs = group["_emb_idx"].values
        day_vecs = embeddings[idxs]

        mean_vec = day_vecs.mean(axis=0)
        rows.append({
            "날짜": date,
            "기사수": len(idxs),
            **{f"e{i}": v for i, v in enumerate(mean_vec)},
        })

    return pd.DataFrame(rows).sort_values("날짜").reset_index(drop=True)


def main():
    print(f"입력 로딩: {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV, parse_dates=["일자"])
    print(f"기사 수: {len(df)}")

    texts = build_text_column(df).tolist()
    print(f"임베딩 대상 텍스트 예시:\n  {texts[0][:100]}...")

    print(f"\n임베딩 모델 로딩 및 인코딩 시작 ({MODEL_NAME})...")
    embeddings = embed_articles(texts)
    print(f"임베딩 shape: {embeddings.shape}")  # (기사수, 768)

    # 기사 단위 임베딩 원본도 보존 (나중에 Leave-One-Out 등 기사 단위 분석에 필요)
    np.save(OUTPUT_DIR / "article_embeddings.npy", embeddings)
    df[["기사ID", "일자", "언론사", "제목", "URL"]].to_csv(
        OUTPUT_DIR / "article_meta.csv", index=False, encoding="utf-8-sig"
    )
    print(f"기사 단위 임베딩 저장: {OUTPUT_DIR / 'article_embeddings.npy'} "
          f"(article_meta.csv의 행 순서와 1:1 대응)")

    daily_df = pool_by_day(df, embeddings)

    try:
        daily_df.to_parquet(OUTPUT_DIR / "daily_news_embeddings.parquet", index=False)
        out_name = "daily_news_embeddings.parquet"
    except ImportError:
        # pyarrow/fastparquet 미설치 시 CSV로 대체 (실제 환경에서는 pip install pyarrow 권장:
        # parquet은 768차원 float를 훨씬 빠르고 작게 저장함)
        daily_df.to_csv(OUTPUT_DIR / "daily_news_embeddings.csv", index=False, encoding="utf-8-sig")
        out_name = "daily_news_embeddings.csv"

    print(f"\n일자별 풀링 결과: {daily_df.shape}")
    print(f"저장 완료: {OUTPUT_DIR / out_name}")
    print(daily_df[["날짜", "기사수"]].describe())


if __name__ == "__main__":
    main()
