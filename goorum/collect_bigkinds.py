"""
빅카인즈(BIG KINDS) Open API로 국내 뉴스를 수집한다.

⚠ 중요: 빅카인즈 Open API는 신청서 제출 → 승인 → 매뉴얼/키 메일 발송 절차를
   거쳐야 정확한 요청 스펙(엔드포인트, 파라미터명)을 받을 수 있다.
   아래 코드는 공공기관 뉴스 검색 API들에서 흔히 쓰이는 구조
   (access_key + argument 딕셔너리를 JSON POST)를 기준으로 작성한 "틀"이며,
   실제 매뉴얼을 받으면 ENDPOINT / payload 필드명을 거기에 맞춰 조정해야 한다.

수집 대상 두 갈래:
    1) 50개 기업명으로 개별 검색  -> 종목코드와 연결되는 기업 관련 뉴스
    2) 사회정책/부동산 등 키워드로 검색 -> 종목코드와 무관한 시장 전체 공통 뉴스
   두 갈래 모두 "일별 상위 노출 기사"를 근사하기 위해, 언론사 중요도/게재 위치
   기준 정렬(relevance/rank)을 요청하고 상위 TOP_N_PER_DAY 건만 남긴다.
"""

import time
import json
import pandas as pd
import requests

from config import (
    BIGKINDS_API_KEY, RAW_DIR, MERGED_DATASET_PATH,
    START_DATE, END_DATE, DOMESTIC_MACRO_KEYWORDS, TOP_N_PER_DAY,
)

# ⚠ 실제 매뉴얼 수신 후 정확한 URL로 교체할 것
ENDPOINT = "https://tools.kinds.or.kr/search/news"


def get_target_companies() -> pd.DataFrame:
    df = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str})
    return df[["종목코드", "종목명"]].drop_duplicates()


def _request(query: str, date_from: str, date_to: str, size: int = 100) -> list[dict]:
    """빅카인즈에 뉴스 검색을 요청하는 공통 함수 (필드명은 매뉴얼 수신 후 검증 필요)"""
    payload = {
        "access_key": BIGKINDS_API_KEY,
        "argument": {
            "query": query,
            "published_at": {"from": date_from, "until": date_to},
            "sort": {"date": "desc"},
            "return_from": 0,
            "return_size": size,
            "fields": ["title", "content", "published_at", "provider", "byline", "category"],
        },
    }
    resp = requests.post(ENDPOINT, data=json.dumps(payload), timeout=30,
                          headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    return data.get("return_object", {}).get("documents", [])


def collect_company_news(companies: pd.DataFrame, date_from: str, date_to: str) -> pd.DataFrame:
    rows = []
    for _, row in companies.iterrows():
        stock_code, name = row["종목코드"], row["종목명"]
        print(f"[기업뉴스] 수집 중: {name} ({stock_code})")
        try:
            docs = _request(query=name, date_from=date_from, date_to=date_to, size=TOP_N_PER_DAY)
        except Exception as e:
            print(f"  ⚠ 실패: {e}")
            continue

        for d in docs:
            rows.append({
                "종목코드": stock_code,
                "날짜": d.get("published_at", "")[:10],
                "언론사": d.get("provider"),
                "제목": d.get("title"),
                "요약": (d.get("content") or "")[:300],  # 본문 전체 저장은 저작권상 지양, 앞부분만
                "카테고리": "기업관련",
            })
        time.sleep(0.3)

    return pd.DataFrame(rows)


def collect_macro_news(date_from: str, date_to: str) -> pd.DataFrame:
    rows = []
    for kw in DOMESTIC_MACRO_KEYWORDS:
        print(f"[국내매크로뉴스] 수집 중: {kw}")
        try:
            docs = _request(query=kw, date_from=date_from, date_to=date_to, size=TOP_N_PER_DAY)
        except Exception as e:
            print(f"  ⚠ 실패: {e}")
            continue

        for d in docs:
            rows.append({
                "종목코드": None,  # 시장 전체 공통 뉴스 -> 특정 종목에 종속되지 않음
                "날짜": d.get("published_at", "")[:10],
                "언론사": d.get("provider"),
                "제목": d.get("title"),
                "요약": (d.get("content") or "")[:300],
                "카테고리": f"국내매크로:{kw}",
            })
        time.sleep(0.3)

    return pd.DataFrame(rows)


def main():
    if not BIGKINDS_API_KEY:
        raise RuntimeError("환경변수 BIGKINDS_API_KEY가 설정되어 있지 않습니다.")

    companies = get_target_companies()

    # 빅카인즈는 통상 기간을 나눠서(예: 월별) 조회하는 게 안전 (대량 조회 시 타임아웃 방지)
    date_range = pd.date_range(START_DATE, END_DATE, freq="MS")
    all_company_rows, all_macro_rows = [], []

    for period_start in date_range:
        period_end = (period_start + pd.offsets.MonthEnd(1))
        d_from, d_to = period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d")
        print(f"\n=== 기간: {d_from} ~ {d_to} ===")

        all_company_rows.append(collect_company_news(companies, d_from, d_to))
        all_macro_rows.append(collect_macro_news(d_from, d_to))

    company_df = pd.concat(all_company_rows, ignore_index=True)
    macro_df = pd.concat(all_macro_rows, ignore_index=True)

    company_df.to_csv(RAW_DIR / "bigkinds_company_news.csv", index=False, encoding="utf-8-sig")
    macro_df.to_csv(RAW_DIR / "bigkinds_macro_news.csv", index=False, encoding="utf-8-sig")

    print(f"\n기업관련 뉴스: {len(company_df)}건 저장")
    print(f"국내매크로 뉴스: {len(macro_df)}건 저장")


if __name__ == "__main__":
    main()
