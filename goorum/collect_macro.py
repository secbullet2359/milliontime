"""
거시 지표(환율, 금리) 수집
- 국내: 한국은행 ECOS API (원/달러 환율, 기준금리)
- 해외: FRED API (미국 연방기금 실효금리, 10년물 국채 수익률)

이 둘은 "뉴스 텍스트"가 아니라 수치 시계열이라 임베딩이 필요 없고,
전일 대비 변화량/변화율로 바로 XGBoost 변수화하면 됨.

실행 전 필요: 환경변수 ECOS_API_KEY, FRED_API_KEY
"""

import time
import pandas as pd
import requests

from config import (
    ECOS_API_KEY, FRED_API_KEY, RAW_DIR,
    START_DATE, END_DATE, ECOS_STATS, FRED_SERIES,
)

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch_ecos_series(name: str, stat_code: str, item_code1: str, cycle: str) -> pd.DataFrame:
    """
    ECOS StatisticSearch API
    URL 형식: /StatisticSearch/{인증키}/{요청형식}/{언어}/{시작건수}/{끝건수}/{통계코드}/{주기}/{시작일}/{종료일}/{통계항목코드1}
    ⚠ item_code1 값은 ECOS 사이트의 "통계코드검색"에서 최신 코드로 재확인 필요
    """
    if cycle == "D":
        start = START_DATE.replace("-", "")
        end = END_DATE.replace("-", "")
    else:  # 월별(M) 등은 YYYYMM 형식
        start = START_DATE[:7].replace("-", "")
        end = END_DATE[:7].replace("-", "")

    url = (
        f"{ECOS_BASE}/{ECOS_API_KEY}/json/kr/1/10000/"
        f"{stat_code}/{cycle}/{start}/{end}/{item_code1}"
    )
    resp = requests.get(url, timeout=30)
    data = resp.json()

    if "StatisticSearch" not in data:
        print(f"  ⚠ {name} 조회 실패: {data}")
        return pd.DataFrame()

    rows = data["StatisticSearch"]["row"]
    df = pd.DataFrame(rows)[["TIME", "DATA_VALUE"]]
    df.columns = ["날짜_raw", name]
    df[name] = pd.to_numeric(df[name], errors="coerce")

    if cycle == "D":
        df["날짜"] = pd.to_datetime(df["날짜_raw"], format="%Y%m%d")
    else:
        df["날짜"] = pd.to_datetime(df["날짜_raw"], format="%Y%m")

    return df[["날짜", name]]


def fetch_fred_series(name: str, series_id: str) -> pd.DataFrame:
    """FRED series/observations API"""
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": START_DATE,
        "observation_end": END_DATE,
    }
    resp = requests.get(FRED_BASE, params=params, timeout=30)
    data = resp.json()

    if "observations" not in data:
        print(f"  ⚠ {name} 조회 실패: {data}")
        return pd.DataFrame()

    df = pd.DataFrame(data["observations"])[["date", "value"]]
    df.columns = ["날짜", name]
    df["날짜"] = pd.to_datetime(df["날짜"])
    # FRED는 결측을 "." 문자열로 표기 (휴장일 등) -> NaN 처리
    df[name] = pd.to_numeric(df[name], errors="coerce")
    return df


def main():
    if not ECOS_API_KEY:
        print("⚠ ECOS_API_KEY가 없어 국내 거시지표 수집을 건너뜁니다.")
    if not FRED_API_KEY:
        print("⚠ FRED_API_KEY가 없어 미국 거시지표 수집을 건너뜁니다.")

    frames = []

    if ECOS_API_KEY:
        for name, spec in ECOS_STATS.items():
            print(f"ECOS 수집 중: {name}")
            df = fetch_ecos_series(name, spec["stat_code"], spec["item_code1"], spec["cycle"])
            if not df.empty:
                frames.append(df.set_index("날짜"))
            time.sleep(0.3)

    if FRED_API_KEY:
        for name, series_id in FRED_SERIES.items():
            print(f"FRED 수집 중: {name}")
            df = fetch_fred_series(name, series_id)
            if not df.empty:
                frames.append(df.set_index("날짜"))
            time.sleep(0.3)

    if not frames:
        print("수집된 거시지표가 없습니다.")
        return

    merged = pd.concat(frames, axis=1).sort_index()

    # 월별 지표(기준금리 등)는 일별로 forward-fill해서 일별 그리드에 맞춤
    merged = merged.resample("D").ffill()

    # 변화량/변화율 변수 추가 (원본 레벨 값보다 이 변화 자체가 XGBoost에 더 유용한 신호)
    for col in merged.columns:
        merged[f"{col}_diff"] = merged[col].diff()
        merged[f"{col}_pct_change"] = merged[col].pct_change()

    merged = merged.reset_index().rename(columns={"index": "날짜"})

    out_path = RAW_DIR / "macro_indicators.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(merged)}행)")


if __name__ == "__main__":
    main()
