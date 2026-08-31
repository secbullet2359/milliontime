"""
DART Open API를 이용해 50개 종목의 공시 목록을 수집한다.

절차:
1. corpCode.xml(zip)을 받아 전체 상장사의 고유번호(corp_code) 매핑표를 만든다
2. merged_dataset.csv에 있는 종목코드 50개를 이 매핑표에서 찾는다
   (우선주는 corpCode.xml에 별도 등록이 없어서, 앞5자리+'0'인 보통주 코드의
    corp_code를 재사용함 - 같은 법인이라 공시 내용이 동일함)
3. 각 corp_code에 대해 list.json으로 공시 목록을 기간별로 조회한다

실행 전 필요: 환경변수 DART_API_KEY

⚠ 네트워크: 이 사내망 환경은 Session + trust_env=False + 프록시 명시적 해제 +
   verify=False 조합이 아니면 요청이 실패하는 것으로 확인됨. plain requests.get()
   방식은 여기서는 안 됨 (환경마다 다를 수 있으니 다른 환경에서 다시 안 되면
   이 조합부터 의심할 것).
"""

import io
import time
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    DART_API_KEY, RAW_DIR, MERGED_DATASET_PATH,
    START_DATE, END_DATE, DART_PBLNTF_TY,
)

DART_BASE = "https://opendart.fss.or.kr/api"


def session_get(url: str, **kwargs) -> requests.Response:
    """이 사내망에서 정상 동작이 확인된 방식: Session + 프록시 강제 해제 + verify=False."""
    session = requests.Session()
    session.trust_env = False  # 시스템/환경변수 프록시 설정 무시
    kwargs.setdefault("timeout", 30)
    return session.get(
        url,
        verify=False,
        proxies={"http": None, "https": None},  # 명시적으로 프록시 사용 안 함
        **kwargs,
    )


def get_corp_code_map() -> pd.DataFrame:
    """전체 상장사 고유번호(corp_code) - 종목코드(stock_code) 매핑표를 받아온다."""
    resp = session_get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=60)
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


def resolve_corp_map(corp_map: pd.DataFrame, stock_codes: list[str]) -> pd.DataFrame:
    """
    대상 종목코드에 대해 corp_code를 찾는다. 직접 못 찾으면 우선주로 보고
    앞5자리+'0'(보통주 코드)의 corp_code를 재사용해서 복구를 시도한다.
    """
    merged = corp_map[corp_map["종목코드"].isin(stock_codes)]
    missing = set(stock_codes) - set(merged["종목코드"])

    if missing:
        print(f"⚠ corp_code 매핑 실패한 종목코드: {missing}")
        print("  -> 우선주일 가능성 확인 중 (앞5자리+'0' = 보통주 코드로 재시도)...")

        recovered_rows = []
        still_missing = []
        for code in missing:
            common_code = code[:5] + "0"
            match = corp_map[corp_map["종목코드"] == common_code]
            if len(match) > 0:
                row = match.iloc[0].copy()
                print(f"    {code} -> 보통주 {common_code}({row['corp_name']})의 corp_code 재사용 "
                      f"(같은 법인이라 공시 내용은 동일함)")
                row["종목코드"] = code
                recovered_rows.append(row)
            else:
                still_missing.append(code)

        if recovered_rows:
            merged = pd.concat([merged, pd.DataFrame(recovered_rows)], ignore_index=True)
        if still_missing:
            print(f"  ⚠ 그래도 못 찾은 종목코드(우선주 규칙으로도 안 됨): {still_missing} "
                  f"- 상장폐지/코드변경 등 다른 원인일 수 있음")

    return merged


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

        try:
            resp = session_get(f"{DART_BASE}/list.json", params=params, timeout=30)
            data = resp.json()
        except Exception as e:
            print(f"  ⚠ corp_code={corp_code} pblntf_ty={pblntf_ty} page={page_no} "
                  f"요청 실패(예외): {type(e).__name__}: {e}")
            break

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

    print(f"[진단] MERGED_DATASET_PATH: {MERGED_DATASET_PATH}")
    print(f"[진단] 설정된 START_DATE/END_DATE: {START_DATE} ~ {END_DATE}")

    print("corp_code 매핑표 다운로드 중...")
    corp_map = get_corp_code_map()

    stock_codes = get_target_stock_codes()
    print(f"대상 종목 수: {len(stock_codes)}")
    print(f"[진단] 대상 종목코드 목록: {stock_codes}")

    merged = resolve_corp_map(corp_map, stock_codes)

    bgn_de = START_DATE.replace("-", "")
    end_de = END_DATE.replace("-", "")
    print(f"[진단] 실제 API 요청에 쓰일 bgn_de/end_de: {bgn_de} ~ {end_de} "
          f"(이 값이 기대한 날짜와 다르면 config.py 반영이 안 된 것)")

    all_rows = []
    for _, row in merged.iterrows():
        corp_code, corp_name, stock_code = row["corp_code"], row["corp_name"], row["종목코드"]
        print(f"수집 중: {corp_name} ({stock_code})")

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

    df["날짜"] = pd.to_datetime(df["rcept_dt"], format="%Y%m%d")
    df = df.drop_duplicates(subset=["rcept_no"]).sort_values(["종목코드", "날짜"])

    out_path = RAW_DIR / "dart_disclosures.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(df)}건)")
    print(f"실제 수집된 공시의 날짜범위: {df['날짜'].min().date()} ~ {df['날짜'].max().date()} "
          f"(요청한 종료일: {END_DATE})")


if __name__ == "__main__":
    main()
