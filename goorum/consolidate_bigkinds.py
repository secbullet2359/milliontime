"""
빅카인즈에서 반기 단위(20,000행 제한)로 나눠 받은 엑셀 파일들을
하나의 CSV로 통합한다.

파일명 규칙 (예): NewsResult_20250101-20250630_매일경제.xlsx
                  NewsResult_20220629-20221231_매일경제.xlsx
파일명에서 시작일/종료일/언론사를 파싱해서 검증용으로만 쓰고,
실제 그룹핑·정렬은 파일 내부의 "일자" 컬럼(진짜 데이터)을 기준으로 한다.
-> 이전에 확인했듯 파일명이 실제 데이터 범위와 다를 수 있기 때문
   (예: "20220101-20221231"이라 적혀 있어도 실제로는 6/29~12/31만 있었음)

CSV는 xlsx와 달리 실질적인 행 개수 제한이 없고, 텍스트가 많은 데이터를
다룰 때 로딩도 더 빠르기 때문에 통합 결과물은 CSV로 저장한다.
"""

import re
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------
# 경로 설정 (필요에 맞게 수정)
# ------------------------------------------------------------------
INPUT_DIR = Path("/mnt/user-data/uploads")          # 원본 엑셀 파일들이 있는 폴더
OUTPUT_PATH = Path("/home/claude/news_collection/raw_data/bigkinds_combined.csv")

FILENAME_PATTERN = re.compile(r"NewsResult_(\d{8})-(\d{8})_(.+)\.xlsx$")


def parse_filename(path: Path) -> dict:
    """파일명에서 시작일/종료일/언론사를 파싱 (검증용 메타데이터)."""
    m = FILENAME_PATTERN.search(path.name)
    if not m:
        return {"파일명_시작일": None, "파일명_종료일": None, "파일명_언론사": None}
    start, end, press = m.groups()
    return {
        "파일명_시작일": pd.to_datetime(start, format="%Y%m%d"),
        "파일명_종료일": pd.to_datetime(end, format="%Y%m%d"),
        "파일명_언론사": press,
    }


def _sniff_and_read(path: Path) -> pd.DataFrame:
    """실제 파일 시그니처를 보고 적절한 리더를 선택해서 읽는다.
    (BigKinds 등 일부 다운로드 시스템은 확장자가 .xlsx라도 실제로는
     옛날 바이너리 .xls(OLE)이거나 HTML 표인 경우가 있어서, 확장자만 믿고
     무조건 openpyxl로 열면 'BadZipFile' 에러로 전체가 멈추는 문제가 생김)
    """
    with open(path, "rb") as f:
        head = f.read(16)

    if head[:2] == b"PK":
        return pd.read_excel(path, engine="openpyxl")
    elif head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return pd.read_excel(path, engine="xlrd")  # pip install xlrd 필요
    elif head[:5] in (b"<html", b"<!DOC", b"<?xml"):
        tables = pd.read_html(path)
        return tables[0]
    else:
        # 마지막 시도: 기본 엔진으로 시도 (실패하면 위 호출자에서 잡음)
        return pd.read_excel(path)


def load_one_file(path: Path) -> pd.DataFrame:
    df = _sniff_and_read(path)
    meta = parse_filename(path)

    df["일자"] = pd.to_datetime(df["일자"], format="%Y%m%d")
    df["원본파일"] = path.name

    # 파일명이 말하는 기간과 실제 데이터 기간이 다르면 경고
    # (지난번 실제로 발생했던 문제라 자동으로 재확인하도록 넣어둠)
    if meta["파일명_시작일"] is not None:
        actual_min, actual_max = df["일자"].min(), df["일자"].max()
        if actual_min < meta["파일명_시작일"] or actual_max > meta["파일명_종료일"]:
            print(f"  ⚠ {path.name}: 파일명 기간과 실제 데이터 기간이 다릅니다 "
                  f"(파일명: {meta['파일명_시작일'].date()}~{meta['파일명_종료일'].date()}, "
                  f"실제: {actual_min.date()}~{actual_max.date()})")

    return df


def main():
    files = sorted(INPUT_DIR.glob("NewsResult_*.xlsx"))
    if not files:
        print(f"'{INPUT_DIR}'에서 NewsResult_*.xlsx 파일을 찾지 못했습니다.")
        return

    print(f"발견된 파일 {len(files)}개:")
    for f in files:
        print(f"  - {f.name}")

    frames = []
    failed_files = []
    for f in files:
        print(f"\n로딩 중: {f.name}")
        try:
            df = load_one_file(f)
        except Exception as e:
            print(f"  ✗ 로딩 실패: {type(e).__name__}: {e}")
            print(f"    -> diagnose_file.py '{f}' 로 실제 포맷을 확인해보세요.")
            failed_files.append((f.name, str(e)))
            continue

        print(f"  {len(df)}행, 기간 {df['일자'].min().date()} ~ {df['일자'].max().date()}, "
              f"언론사: {df['언론사'].unique().tolist()}")
        frames.append(df)

    if not frames:
        print("\n정상적으로 로딩된 파일이 하나도 없습니다.")
        return

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)

    # ⚠ "뉴스 식별자" 컬럼은 원래 "언론사코드.날짜.일련번호" 형태의 문자열인데,
    #    엑셀이 이를 숫자(float64)로 자동 인식하면서 float64 정밀도(15~17자리) 한계에
    #    걸려 뒷부분(일련번호)이 뭉개져 서로 다른 기사가 같은 값으로 겹쳐버림.
    #    (실제 확인: 20,000행 중 552개 값으로 뭉개짐 -> 이 컬럼으로 중복제거하면 안 됨)
    #    URL은 19,993/20,000이 고유해서 훨씬 안전한 중복판별 키.
    #    (일자, 제목, URL) 조합으로 중복 제거 -> 반기 파일 경계에서 같은 기사가
    #    중복 수집된 경우만 제거하고, 진짜 다른 기사는 보존.
    combined = combined.drop_duplicates(subset=["URL"])
    after = len(combined)
    if before != after:
        print(f"\n중복 제거(URL 기준): {before}행 -> {after}행 ({before - after}건 제거)")

    combined = combined.sort_values(["일자", "언론사"]).reset_index(drop=True)

    # "뉴스 식별자"는 위에서 확인한 정밀도 손실 문제가 있어 그대로 두면 나중에
    # 혼동을 줄 수 있음 -> URL 기반 해시로 신뢰 가능한 대체 ID를 새로 생성
    import hashlib
    combined["기사ID"] = combined["URL"].apply(
        lambda u: hashlib.md5(str(u).encode("utf-8")).hexdigest()[:12]
    )

    # ------------------------------------------------------------------
    # 최종 점검용 요약 출력
    # ------------------------------------------------------------------
    print(f"\n=== 통합 결과 ===")
    print(f"전체 행 수: {len(combined)}")
    print(f"전체 기간: {combined['일자'].min().date()} ~ {combined['일자'].max().date()}")
    print(f"\n언론사별 건수:\n{combined['언론사'].value_counts()}")
    print(f"\n연도별 건수:\n{combined['일자'].dt.year.value_counts().sort_index()}")

    # 연도별로 실제 수집된 날짜 수도 확인 (365일 대비 커버리지 - 수집 공백 조기 발견용)
    coverage = combined.groupby(combined["일자"].dt.year)["일자"].nunique()
    print(f"\n연도별 수집된 날짜 수 (365/366일 기준):\n{coverage}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_PATH}")

    if failed_files:
        print(f"\n⚠ 로딩 실패한 파일 {len(failed_files)}개 (별도 확인 필요):")
        for name, err in failed_files:
            print(f"  - {name}: {err}")


if __name__ == "__main__":
    main()
