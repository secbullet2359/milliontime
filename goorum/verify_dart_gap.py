"""
저장 없이 검증만 하는 스크립트.
특정 기간(기본: 2026-08-21 ~ 2026-08-30)에 50개 종목에 실제로 공시가
없었는지, 아니면 API 호출 자체가 실패한 건지를 구분한다.

DART list.json 응답의 status로 구분:
    "000" = 정상 조회, list가 비어있으면 진짜로 공시가 없는 것
    "013" = 조회된 데이터 없음 (역시 "진짜로 없음"과 같은 의미)
    그 외  = 키 오류/한도초과 등 실제 실패
"""

import io
import os
import time
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests

DART_API_KEY = os.environ.get("DART_API_KEY")
DART_BASE = "https://opendart.fss.or.kr/api"

CHECK_START = "20260821"
CHECK_END = "20260830"

MERGED_DATASET_PATH = "/home/claude/news_collection/raw_data/merged_dataset_with_news_macro_dart.csv"


def get_corp_code_map() -> pd.DataFrame:
    resp = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=60)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    root = ET.fromstring(zf.read(zf.namelist()[0]))

    rows = []
    for node in root.findall("list"):
        stock_code = (node.findtext("stock_code") or "").strip()
        if stock_code:
            rows.append({"corp_code": node.findtext("corp_code"),
                         "corp_name": node.findtext("corp_name"),
                         "종목코드": stock_code})
    return pd.DataFrame(rows)


def check_corp(corp_code: str, corp_name: str, stock_code: str) -> dict:
    """pblntf_ty 필터 없이(전체 유형) 조회해서, 이 기간에 뭐라도 있었는지 확인."""
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": CHECK_START,
        "end_de": CHECK_END,
        "page_no": 1,
        "page_count": 100,
    }
    resp = requests.get(f"{DART_BASE}/list.json", params=params, timeout=30)
    data = resp.json()
    status = data.get("status")

    if status == "013":
        return {"종목코드": stock_code, "corp_name": corp_name, "status": "정상(공시없음)", "건수": 0}
    if status == "000":
        n = len(data.get("list", []))
        return {"종목코드": stock_code, "corp_name": corp_name, "status": "정상", "건수": n}
    return {"종목코드": stock_code, "corp_name": corp_name,
            "status": f"⚠API오류({status}): {data.get('message')}", "건수": None}


def main():
    if not DART_API_KEY:
        raise RuntimeError("환경변수 DART_API_KEY가 없습니다.")

    print(f"검증 기간: {CHECK_START} ~ {CHECK_END} (pblntf_ty 필터 없이 전체 유형 조회)\n")

    corp_map = get_corp_code_map()
    target_codes = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str},
                                usecols=["종목코드"])["종목코드"].unique()
    merged = corp_map[corp_map["종목코드"].isin(target_codes)]

    results = []
    for _, row in merged.iterrows():
        r = check_corp(row["corp_code"], row["corp_name"], row["종목코드"])
        results.append(r)
        time.sleep(0.2)

    df = pd.DataFrame(results)
    n_api_errors = (df["status"].str.startswith("⚠")).sum()
    total_found = df["건수"].sum(skipna=True)

    print(df.to_string(index=False))
    print(f"\n=== 결론 ===")
    print(f"API 오류로 확인 못 한 종목: {n_api_errors}개 (0이어야 신뢰 가능)")
    print(f"이 기간 전체 종목 공시 건수 합계: {total_found}건")

    if n_api_errors == 0 and total_found == 0:
        print("-> API 호출은 전부 정상(status 000/013)이었고, 실제로 이 기간에 공시가 없었던 것으로 확인됨.")
    elif n_api_errors > 0:
        print("-> API 오류가 있는 종목이 있어, '공시가 없다'고 단정할 수 없음. 위 표에서 ⚠ 표시된 항목 확인 필요.")
    else:
        print(f"-> 공시가 {total_found}건 실제로 있었음. 기존 dart_disclosures.csv에 이게 빠져있다면 수집 스크립트 쪽 문제.")


if __name__ == "__main__":
    main()
