"""
저장 없이 검증만 하는 스크립트.
특정 기간(기본: 2026-08-21 ~ 2026-08-30)에 50개 종목에 실제로
"수집 대상 유형(B/C/I)"의 공시가 있었는지 확인한다.

⚠ 이전 버전의 실수: DART list.json 응답 항목에는 애초에 pblntf_ty(공시유형)
   필드가 없다 (그건 요청 시 넣는 "필터" 파라미터일 뿐, 응답에 포함되는
   값이 아님). 그래서 필터 없이 조회한 뒤 사후에 유형을 가려내려던 이전
   버전은 항상 실패했다 (전부 None으로 잡혀서 조용히 통계가 비어버림).
   -> 그래서 collect_dart.py와 동일하게, pblntf_ty를 "요청 파라미터"로
      직접 넣어서 B/C/I 각각 조회하는 방식으로 재작성함.
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
PBLNTF_TYPES_TO_CHECK = ["B", "C", "I"]  # config.py의 DART_PBLNTF_TY와 반드시 동일하게 유지

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


def check_corp_by_type(corp_code: str, corp_name: str, stock_code: str, pblntf_ty: str) -> dict:
    """collect_dart.py와 완전히 동일한 방식: pblntf_ty를 요청 파라미터로 직접 지정."""
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": CHECK_START,
        "end_de": CHECK_END,
        "pblntf_ty": pblntf_ty,
        "page_no": 1,
        "page_count": 100,
    }
    resp = requests.get(f"{DART_BASE}/list.json", params=params, timeout=30)
    data = resp.json()
    status = data.get("status")

    if status == "013":
        return {"종목코드": stock_code, "corp_name": corp_name, "pblntf_ty": pblntf_ty,
                "status": "정상(공시없음)", "건수": 0, "제목목록": []}
    if status == "000":
        items = data.get("list", [])
        titles = [item.get("report_nm") for item in items]
        return {"종목코드": stock_code, "corp_name": corp_name, "pblntf_ty": pblntf_ty,
                "status": "정상", "건수": len(items), "제목목록": titles}
    return {"종목코드": stock_code, "corp_name": corp_name, "pblntf_ty": pblntf_ty,
            "status": f"⚠API오류({status}): {data.get('message')}", "건수": None, "제목목록": []}


def main():
    if not DART_API_KEY:
        raise RuntimeError("환경변수 DART_API_KEY가 없습니다.")

    print(f"검증 기간: {CHECK_START} ~ {CHECK_END}, 검증할 유형: {PBLNTF_TYPES_TO_CHECK}\n")

    corp_map = get_corp_code_map()
    target_codes = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str},
                                usecols=["종목코드"])["종목코드"].unique()
    merged = corp_map[corp_map["종목코드"].isin(target_codes)]

    results = []
    for _, row in merged.iterrows():
        for pty in PBLNTF_TYPES_TO_CHECK:
            r = check_corp_by_type(row["corp_code"], row["corp_name"], row["종목코드"], pty)
            results.append(r)
            time.sleep(0.2)

    df = pd.DataFrame(results)
    n_api_errors = (df["status"].str.startswith("⚠")).sum()
    total_found = df["건수"].sum(skipna=True)

    found = df[df["건수"].fillna(0) > 0]
    if len(found) > 0:
        print("=== B/C/I 유형으로 실제 발견된 공시 ===")
        for _, r in found.iterrows():
            print(f"  {r['종목코드']} {r['corp_name']} (유형 {r['pblntf_ty']}): {r['제목목록']}")

    print(f"\n=== 결론 ===")
    print(f"API 오류: {n_api_errors}건 (0이어야 신뢰 가능)")
    print(f"B/C/I 유형 공시 건수 합계: {total_found}건")

    if n_api_errors > 0:
        print("-> API 오류가 있어 '없다'고 단정할 수 없습니다.")
    elif total_found == 0:
        print("-> B/C/I 유형 공시는 이 기간에 실제로 없었습니다. "
              "(이전 197건은 A/D/E/F 등 수집 대상 외 유형이었을 가능성이 높음 - "
              "다만 이전 검증 방식이 깨져있었어서 이 결론도 '아마 그럴 것'이라는 추정입니다. "
              "확실히 하려면 dart_disclosures.csv 자체를 열어서 이 기간 corp_code별 "
              "report_nm을 직접 눈으로 확인해보시는 걸 권장합니다.)")
    else:
        print(f"-> B/C/I 유형 공시가 {total_found}건 실제로 있는데 dart_disclosures.csv에 없습니다. "
              f"이건 진짜 collect_dart.py의 수집 버그입니다. predict_tomorrow.py로 넘어가기 전에 "
              f"먼저 collect_dart.py를 재실행해서 이 공시들을 채워야 합니다.")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
