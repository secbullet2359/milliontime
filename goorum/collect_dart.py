"""
DART Open API를 이용해 50개 종목의 공시 목록을 수집한다.

절차:
1. corpCode.xml(zip)을 받아 전체 상장사의 고유번호(corp_code) 매핑표를 만든다
2. merged_dataset.csv에 있는 종목코드 50개를 이 매핑표에서 찾는다
3. 각 corp_code에 대해 list.json으로 공시 목록을 기간별로 조회한다
   (corp_code를 지정하면 3개월 제한이 없어짐 - dart-fss 문서 기준)

실행 전 필요: 환경변수 DART_API_KEY
참고: 이 샌드박스는 네트워크가 차단되어 있어 실제 API 호출은 테스트하지 못했음.
     실제 실행 환경(네트워크 가능한 곳)에서 사용할 것.
"""

import io
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

import pandas as pd
import requests

from config import (
    DART_API_KEY, RAW_DIR, MERGED_DATASET_PATH,
    START_DATE, END_DATE, DART_PBLNTF_TY,
)

DART_BASE = "https://opendart.fss.or.kr/api"


def get_corp_code_map() -> pd.DataFrame:
    """전체 상장사 고유번호(corp_code) - 종목코드(stock_code) 매핑표를 받아온다."""
    resp = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=60)
    resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)

    rows = []
    for node in root.findall("list"):
        stock_code = (node.findtext("stock_code") or "").strip()
        if not stock_code:
            continue  # 비상장사는 stock_code가 공백 -> 제외
        rows.append({
            "corp_code": node.findtext("corp_code"),
            "corp_name": node.findtext("corp_name"),
            "종목코드": stock_code,
        })
    return pd.DataFrame(rows)


def get_target_stock_codes() -> list[str]:
    """기존에 만든 merged_dataset.csv에서 대상 50개 종목코드를 가져온다."""
    df = pd.read_csv(MERGED_DATASET_PATH, dtype={"종목코드": str})
    return sorted(df["종목코드"].unique().tolist())


def fetch_disclosures_for_corp(corp_code: str, bgn_de: str, end_de: str, pblntf_ty: str) -> list[dict]:
    """corp_code 하나, 공시유형 하나에 대해 기간 내 공시 목록을 페이지네이션으로 전부 수집."""
    results = []
    page_no = 1
    while True:
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "pblntf_ty": pblntf_ty,
            "page_no": page_no,
            "page_count": 100,
        }

        resp = requests.get(f"{DART_BASE}/list.json", params=params, timeout=30)
        data = resp.json()

        if data.get("status") == "013":  # 조회된 데이터 없음
            break
        if data.get("status") != "000":
            print(f"  ⚠ corp_code={corp_code} pblntf_ty={pblntf_ty} 오류: {data.get('message')}")
            break

        results.extend(data.get("list", []))

        total_page = data.get("total_page", 1)
        if page_no >= total_page:
            break
        page_no += 1
        time.sleep(0.2)  # 과도한 연속 호출 방지

    return results


def main():
    if not DART_API_KEY:
        raise RuntimeError("환경변수 DART_API_KEY가 설정되어 있지 않습니다.")

    print("corp_code 매핑표 다운로드 중...")
    corp_map = get_corp_code_map()

    stock_codes = get_target_stock_codes()
    print(f"대상 종목 수: {len(stock_codes)}")

    merged = corp_map[corp_map["종목코드"].isin(stock_codes)]
    missing = set(stock_codes) - set(merged["종목코드"])
    if missing:
        print(f"⚠ corp_code 매핑 실패한 종목코드: {missing}")

    bgn_de = START_DATE.replace("-", "")
    end_de = END_DATE.replace("-", "")

    all_rows = []
    for _, row in merged.iterrows():
        corp_code, corp_name, stock_code = row["corp_code"], row["corp_name"], row["종목코드"]
        print(f"수집 중: {corp_name} ({stock_code})")

        # pblntf_ty는 API가 한 번에 하나만 받으므로 유형별로 순회
        for pty in DART_PBLNTF_TY:
            disclosures = fetch_disclosures_for_corp(corp_code, bgn_de, end_de, pty)
            for d in disclosures:
                d["종목코드"] = stock_code
                d["pblntf_ty_filter"] = pty
            all_rows.extend(disclosures)
            time.sleep(0.3)

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("수집된 공시가 없습니다. API 키/기간을 확인하세요.")
        return

    # rcept_dt(YYYYMMDD) -> 날짜 컬럼으로 표준화 (다른 데이터셋과 병합 키를 맞추기 위함)
    df["날짜"] = pd.to_datetime(df["rcept_dt"], format="%Y%m%d")
    df = df.drop_duplicates(subset=["rcept_no"]).sort_values(["종목코드", "날짜"])

    out_path = RAW_DIR / "dart_disclosures.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(df)}건)")


if __name__ == "__main__":
    main()
