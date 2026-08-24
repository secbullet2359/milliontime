"""
해외 뉴스 수집 - GDELT DOC 2.0 API (무료, API 키 불필요) + NewsAPI(선택, 키 필요)

목적: 외국인 수급에 영향을 줄 수 있는 "외신 원문 논조"를 확보.
     빅카인즈(국내 언론의 보도)와는 별도 소스이며, 언어도 영어 위주라
     이후 임베딩 단계에서 다국어 지원 모델(multilingual sentence embedding)로
     한국어(빅카인즈)와 영어(GDELT/NewsAPI) 기사를 같은 벡터 공간에 태워야 함.

GDELT DOC 2.0 API 제약:
    - 최근 3개월 롤링 윈도우만 검색 가능 (그 이전 과거 데이터는 BigQuery GDELT 데이터셋을
      따로 받아야 함 -> 5년치 백필이 필요하면 이 스크립트만으로는 부족, 별도 안내 필요)
    - 무료, API 키 불필요
"""

import time
import pandas as pd
import requests

from config import (
    NEWSAPI_KEY, RAW_DIR, GLOBAL_ISSUE_KEYWORDS, TOP_N_PER_DAY,
)

GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


def fetch_gdelt(query: str, start_dt: str, end_dt: str, max_records: int = 100) -> list[dict]:
    """
    GDELT DOC 2.0 API
    startdatetime/enddatetime 형식: YYYYMMDDHHMMSS
    ⚠ 최근 3개월 롤링 윈도우 제약 있음 (그 이전은 별도 백필 필요)
    """
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": max_records,
        "sort": "hybridrel",  # 관련도+최신성 혼합 정렬 (Top 기사 근사용)
        "startdatetime": start_dt,
        "enddatetime": end_dt,
    }
    resp = requests.get(GDELT_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("articles", [])


def fetch_newsapi(query: str, date_from: str, date_to: str, page_size: int = 100) -> list[dict]:
    if not NEWSAPI_KEY:
        return []
    params = {
        "q": query,
        "from": date_from,
        "to": date_to,
        "language": "en",
        "sortBy": "popularity",  # "인기도(주요 노출)" 기준 -> Top 기사 근사
        "pageSize": page_size,
        "apiKey": NEWSAPI_KEY,
    }
    resp = requests.get(NEWSAPI_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("articles", [])


def collect_gdelt_by_day(keywords: list[str], date_from: str, date_to: str) -> pd.DataFrame:
    rows = []
    dates = pd.date_range(date_from, date_to, freq="D")

    for d in dates:
        start_dt = d.strftime("%Y%m%d000000")
        end_dt = d.strftime("%Y%m%d235959")
        for kw in keywords:
            print(f"[GDELT] {d.date()} - {kw}")
            try:
                articles = fetch_gdelt(kw, start_dt, end_dt, max_records=TOP_N_PER_DAY)
            except Exception as e:
                print(f"  ⚠ 실패: {e}")
                continue

            for a in articles:
                rows.append({
                    "종목코드": None,  # 해외 매크로 뉴스는 시장 전체 공통
                    "날짜": d.strftime("%Y-%m-%d"),
                    "언론사": a.get("domain"),
                    "제목": a.get("title"),
                    "요약": a.get("title"),  # GDELT는 본문 대신 제목/URL만 제공 (본문은 원문 링크에서 크롤링 필요, 저작권 고려해 생략)
                    "URL": a.get("url"),
                    "언어": a.get("language", "en"),
                    "카테고리": f"해외이슈:{kw}",
                })
            time.sleep(0.5)  # GDELT rate limit 여유

    return pd.DataFrame(rows)


def collect_newsapi_by_period(keywords: list[str], date_from: str, date_to: str) -> pd.DataFrame:
    if not NEWSAPI_KEY:
        print("⚠ NEWSAPI_KEY가 없어 NewsAPI 수집을 건너뜁니다 (GDELT만으로도 진행 가능).")
        return pd.DataFrame()

    rows = []
    for kw in keywords:
        print(f"[NewsAPI] {kw}")
        try:
            articles = fetch_newsapi(kw, date_from, date_to, page_size=TOP_N_PER_DAY)
        except Exception as e:
            print(f"  ⚠ 실패: {e}")
            continue

        for a in articles:
            rows.append({
                "종목코드": None,
                "날짜": (a.get("publishedAt") or "")[:10],
                "언론사": a.get("source", {}).get("name"),
                "제목": a.get("title"),
                "요약": a.get("description"),
                "URL": a.get("url"),
                "언어": "en",
                "카테고리": f"해외이슈:{kw}",
            })
        time.sleep(0.5)

    return pd.DataFrame(rows)


def main():
    # GDELT는 최근 3개월만 조회 가능하므로, 최근 구간만 예시로 수집
    # (5년치 백필이 필요하면 GDELT의 BigQuery 원본 데이터셋을 별도로 받아야 함)
    recent_end = pd.Timestamp.today().normalize()
    recent_start = recent_end - pd.Timedelta(days=90)

    date_from = recent_start.strftime("%Y-%m-%d")
    date_to = recent_end.strftime("%Y-%m-%d")

    print(f"GDELT/NewsAPI 수집 기간(최근 3개월 제약): {date_from} ~ {date_to}")

    gdelt_df = collect_gdelt_by_day(GLOBAL_ISSUE_KEYWORDS, date_from, date_to)
    newsapi_df = collect_newsapi_by_period(GLOBAL_ISSUE_KEYWORDS, date_from, date_to)

    combined = pd.concat([gdelt_df, newsapi_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["제목", "날짜"])

    out_path = RAW_DIR / "global_news.csv"
    combined.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(combined)}건)")


if __name__ == "__main__":
    main()
