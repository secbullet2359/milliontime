"""
XGBoost 학습용 통합 데이터셋 구축 스크립트
- technical_indicators_5y.csv (OHLCV + 기술적 지표)
- investor_trading_5y.csv (투자자별 순매수 금액) -> 거래대금 대비 비율로 정규화
- fundamental_5y.csv (PER/PBR/EPS 등)
를 (날짜, 종목코드) 기준으로 병합한다.
 
주의:
- target 정의(다음날 수익률 등)와 train/val/test 분리는 뉴스 임베딩 변수가
  합류한 뒤에 진행할 예정이라 이 스크립트에는 포함하지 않음.
- 종목 통합(pooled) 모델을 염두에 두고, 종목코드는 category 타입으로만 표시.
"""
 
import pandas as pd
import numpy as np
from pathlib import Path
 
# ------------------------------------------------------------------
# 0) 경로 설정
# ------------------------------------------------------------------
INPUT_DIR = Path("/mnt/user-data/uploads")
TI_FILE = INPUT_DIR / "technical_indicators_5y.csv"
INV_FILE = INPUT_DIR / "investor_trading_5y.csv"
FUND_FILE = INPUT_DIR / "fundamental_5y.csv"
 
OUTPUT_FILE = Path("/home/claude/merged_dataset.csv")
 
 
# ------------------------------------------------------------------
# 1) 데이터 로드
#    종목코드는 앞자리 0이 있는 문자열(예: '005930')이라 dtype을 str로 강제
# ------------------------------------------------------------------
def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"종목코드": str}, parse_dates=["날짜"], encoding="utf-8-sig")
    return df
 
 
ti = load_csv(TI_FILE)
inv = load_csv(INV_FILE)
fund = load_csv(FUND_FILE)
 
print(f"technical_indicators: {ti.shape}, 종목수 {ti['종목코드'].nunique()}")
print(f"investor_trading:     {inv.shape}, 종목수 {inv['종목코드'].nunique()}")
print(f"fundamental:           {fund.shape}, 종목수 {fund['종목코드'].nunique()}")
 
 
# ------------------------------------------------------------------
# 1-1) 거래정지 구간 탐지
#    인적분할/유상증자 등으로 매매거래가 정지되면 시가/고가/저가=0,
#    거래량=0, 종가는 정지 직전 값으로 고정, 등락률=0 으로 기록됨.
#    (예: SK텔레콤 2021-10-26~11-26, 삼성바이오로직스 2025-10-30~11-21 등)
#    이 구간은 "뉴스에 시장이 무반응했다"가 아니라 "시장 자체가 없었다"는
#    뜻이라 target(다음날 수익률) 계산에 절대 쓰면 안 됨.
#    -> 지금 단계에서는 삭제하지 않고 플래그만 남겨서, target 정의 시점에
#       (a) 정지 구간 자체와 (b) 재상장 첫날(구조적 가격 재산정으로 수익률이
#       뉴스 반응이 아닌 왜곡값)을 함께 제외할 수 있도록 함.
# ------------------------------------------------------------------
ti = ti.sort_values(["종목코드", "날짜"]).reset_index(drop=True)
 
ti["거래정지"] = ti["거래량"] == 0
 
# 재상장 첫날 = 직전 행이 거래정지였던 날 (구조적 가격 재산정으로 수익률이 왜곡될 수 있는 날)
ti["재상장첫날"] = ti.groupby("종목코드")["거래정지"].shift(1).fillna(False) & (~ti["거래정지"])
 
n_halt = ti["거래정지"].sum()
n_resume = ti["재상장첫날"].sum()
print(f"\n거래정지 구간 탐지: {n_halt}행 (전체의 {n_halt/len(ti)*100:.2f}%)")
print(f"재상장 첫날(가격 구조적 재산정 가능): {n_resume}행")
if n_halt > 0:
    halt_stocks = ti.loc[ti["거래정지"], "종목명"].value_counts()
    print("종목별 거래정지 행 수:\n", halt_stocks)
 
 
# ------------------------------------------------------------------
# 2) investor_trading 정규화
#    절대 순매수 금액은 종목마다 스케일(시총/유동성)이 완전히 달라서
#    그대로 쓰면 XGBoost가 "종목 크기"를 우회 학습할 위험이 있음.
#    -> 그날의 거래대금(종가 * 거래량) 대비 비율로 정규화.
# ------------------------------------------------------------------
ti["거래대금"] = ti["종가"] * ti["거래량"]
 
inv_cols = ["날짜", "종목코드", "기관합계", "기타법인", "개인", "외국인합계", "전체"]
inv_slim = inv[inv_cols].copy()
 
df = ti.merge(inv_slim, on=["날짜", "종목코드"], how="left")
 
# investor_trading 쪽에만 없는 날짜(60,794 vs 60,859, 65행 차이)가 있어 병합 후 결측 발생 가능
missing_inv = df["기관합계"].isna().sum()
if missing_inv > 0:
    print(f"⚠ investor_trading 매칭 안 된 행: {missing_inv}건 (해당 종목/날짜 순매수 데이터 누락)")
 
investor_raw_cols = ["기관합계", "기타법인", "개인", "외국인합계", "전체"]
ratio_target_cols = ["기관합계", "기타법인", "개인", "외국인합계"]  # "전체"는 항상 0(합계 검증용 필드)이라 제외
for col in ratio_target_cols:
    ratio_col = f"{col}_ratio"
    df[ratio_col] = df[col] / df["거래대금"]
    # 거래대금이 0이거나 결측이면 비율도 결측 처리 (0으로 채우면 "순매수가 정확히 0"과 혼동되므로 NaN 유지)
    df.loc[~np.isfinite(df[ratio_col]), ratio_col] = np.nan
 
# 원본 절대금액 컬럼("전체" 포함)은 종목 통합 모델에는 스케일 왜곡을 주므로 제거하고 ratio만 남김
df = df.drop(columns=investor_raw_cols)
 
 
# ------------------------------------------------------------------
# 3) fundamental 병합
# ------------------------------------------------------------------
fund_cols = ["날짜", "종목코드", "BPS", "PER", "PBR", "EPS", "DIV", "DPS"]
df = df.merge(fund[fund_cols], on=["날짜", "종목코드"], how="left")
 
 
# ------------------------------------------------------------------
# 3-0) fundamental 결측 마커(0) 정제
#    확인 결과 PER=0인 행은 예외 없이 EPS=0, PBR=0인 행은 예외 없이 BPS=0.
#    실제 기업의 주당순자산이 정확히 0일 수는 없으므로, 이는 "값이 0"이 아니라
#    데이터 제공처가 산출불가/결측을 0으로 표기한 것으로 판단됨
#    (예: 우선주처럼 PER 산출 방식이 다른 종목, 특정 시점 데이터 누락 등).
#    -> 이 상태로 그대로 두면 cross-sectional z-score에서 "결측"이
#       "극단적으로 저평가"로 왜곡되므로, z-score 계산 전 NaN으로 치환.
#    (DIV=0/DPS=0은 "무배당 종목"이라는 실제 값일 수 있어 그대로 유지)
# ------------------------------------------------------------------
per_missing = (df["PER"] == 0) & (df["EPS"] == 0)
pbr_missing = (df["PBR"] == 0) & (df["BPS"] == 0)
print(f"\nPER/EPS 결측 마커로 판단, NaN 처리: {per_missing.sum()}행")
print(f"PBR/BPS 결측 마커로 판단, NaN 처리: {pbr_missing.sum()}행")
 
df.loc[per_missing, ["PER", "EPS"]] = np.nan
df.loc[pbr_missing, ["PBR", "BPS"]] = np.nan
 
 
# ------------------------------------------------------------------
# 3-1) fundamental cross-sectional 정규화 (같은 날, 50개 종목 내 상대적 위치)
#    PER=32, PBR=1.9 같은 절대 레벨은 종목마다 업종 특성이 달라 그 자체로는
#    "싸다/비싸다"를 말해주지 않음 (성장주 PER 40 vs 금융주 PER 8이 정상인 경우).
#    -> 같은 날짜 기준, 50개 종목 사이에서의 z-score로 변환해서
#       "그날 시장 내에서 상대적으로 저평가/고평가 상태인지"를 나타내는 값으로 사용.
#    (원본 레벨 컬럼은 그대로 남겨두고, *_zscore 컬럼을 별도로 추가)
# ------------------------------------------------------------------
fundamental_level_cols = ["BPS", "PER", "PBR", "EPS", "DIV", "DPS"]
 
for col in fundamental_level_cols:
    grp = df.groupby("날짜")[col]
    mean = grp.transform("mean")
    std = grp.transform("std")
    zscore = (df[col] - mean) / std
    # 그날 표본이 1개뿐이거나 std=0(전 종목 값이 동일)이면 z-score 정의 불가 -> NaN 유지
    zscore[~np.isfinite(zscore)] = np.nan
    df[f"{col}_zscore"] = zscore
 
print("\nfundamental z-score 결측 비율 (표본 부족/std=0인 날짜 존재 여부 확인):")
print(df[[f"{c}_zscore" for c in fundamental_level_cols]].isna().mean())
 
 
# ------------------------------------------------------------------
# 4) 정렬 및 종목코드 타입 정리 (XGBoost pooled 모델에서 categorical로 쓰기 위함)
# ------------------------------------------------------------------
df = df.sort_values(["종목코드", "날짜"]).reset_index(drop=True)
df["종목코드"] = df["종목코드"].astype("category")
 
# 불리언 플래그는 One-hot이 필요 없는 이진값이지만, CSV로 저장/재로딩 시
# "True"/"False" 문자열로 읽힐 위험이 있으므로 0/1 정수로 명시적 캐스팅
bool_flag_cols = ["거래정지", "재상장첫날"]
df[bool_flag_cols] = df[bool_flag_cols].astype(int)
 
print("\n최종 병합 데이터셋")
print("shape:", df.shape)
print("컬럼 목록:", list(df.columns))
print("\n컬럼별 결측치 비율 (상위 10개):")
print(df.isna().mean().sort_values(ascending=False).head(10))
 
df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
print(f"\n저장 완료: {OUTPUT_FILE}")
 
