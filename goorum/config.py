"""
공통 설정
모든 API 키는 환경변수로 관리 (코드에 하드코딩하지 않음)

필요한 환경변수:
    DART_API_KEY      - OpenDART (https://opendart.fss.or.kr) 발급 키
    ECOS_API_KEY      - 한국은행 ECOS (https://ecos.bok.or.kr/api) 발급 키
    FRED_API_KEY      - FRED (https://fred.stlouisfed.org/docs/api/api_key.html) 발급 키
    BIGKINDS_API_KEY  - 빅카인즈 OPEN API 신청 승인 후 발급받는 키
    NEWSAPI_KEY       - (선택) NewsAPI.org 발급 키
"""

import os
from pathlib import Path

# ------------------------------------------------------------------
# 경로
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw_data"
RAW_DIR.mkdir(exist_ok=True)

# 기존에 만든 정형 데이터 (종목코드/종목명 매핑 재사용)
MERGED_DATASET_PATH = Path("/mnt/user-data/outputs/merged_dataset.csv")

# ------------------------------------------------------------------
# API 키 (환경변수에서 로드, 없으면 None -> 해당 모듈 실행 시 에러 메시지 출력)
# ------------------------------------------------------------------
DART_API_KEY = os.environ.get("DART_API_KEY")
ECOS_API_KEY = os.environ.get("ECOS_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
BIGKINDS_API_KEY = os.environ.get("BIGKINDS_API_KEY")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")

# ------------------------------------------------------------------
# 수집 기간 (필요에 맞게 조정)
# ------------------------------------------------------------------
START_DATE = "2021-01-01"   # YYYY-MM-DD
END_DATE = "2026-08-20"

# ------------------------------------------------------------------
# 공시(DART) 필터링 - 주가에 영향이 큰 유형만 우선 수집
#   A: 정기공시, B: 주요사항보고, C: 발행공시, D: 지분공시,
#   E: 기타공시, F: 외부감사관련, I: 거래소공시
#   (전체를 다 받으면 노이즈가 너무 많아서 우선순위를 좁혀둠. 필요시 추가)
# ------------------------------------------------------------------
DART_PBLNTF_TY = ["B", "C", "I"]

# ------------------------------------------------------------------
# 거시 지표 (ECOS/FRED 통계코드)
#   ⚠ ECOS 통계코드는 한국은행 ECOS 사이트의 "통계코드검색"에서
#      최신 코드로 재확인 후 사용할 것 (개편으로 코드가 바뀔 수 있음)
# ------------------------------------------------------------------
ECOS_STATS = {
    "usd_krw": {"stat_code": "731Y001", "item_code1": "0000001", "cycle": "D"},   # 원/달러 매매기준율
    "base_rate": {"stat_code": "722Y001", "item_code1": "0101000", "cycle": "M"},  # 한국은행 기준금리
    # ⚠ 아래 두 개는 item_code1이 세부 옵션(평잔/말잔, 총지수 등)에 따라 달라질 수 있어
    #    ECOS 사이트의 "통계코드검색"에서 최신 값으로 재확인 필요
    "m2": {"stat_code": "101Y003", "item_code1": "BBHS00", "cycle": "M"},          # M2(광의통화, 평잔)
    "cpi": {"stat_code": "901Y009", "item_code1": "0", "cycle": "M"},              # 소비자물가지수(총지수)
}

FRED_SERIES = {
    "fed_funds_rate": "DFF",      # 미국 연방기금 실효금리 (일별)
    "us_10y_treasury": "DGS10",   # 미국 10년물 국채 수익률 (일별)
}

# ------------------------------------------------------------------
# 뉴스 검색 키워드 (Track B: 간접 영향 뉴스)
# ------------------------------------------------------------------
DOMESTIC_MACRO_KEYWORDS = ["부동산 정책", "주택 공급", "금융 규제", "세제 개편"]
GLOBAL_ISSUE_KEYWORDS = [
    "Federal Reserve", "interest rate", "war", "geopolitical tension",
    "trade tariff", "oil price", "recession",
]

TOP_N_PER_DAY = 100
