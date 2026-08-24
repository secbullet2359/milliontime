"""
전체 수집 파이프라인 실행
    1) DART 공시
    2) 거시지표 (ECOS/FRED)
    3) 빅카인즈 (국내 기업뉴스 + 국내 매크로뉴스)
    4) GDELT/NewsAPI (해외뉴스, 다국어)

각 단계는 독립적으로도 실행 가능 (API 키가 없는 단계는 자동으로 skip 메시지 출력).
결과는 raw_data/ 폴더에 소스별 CSV로 저장 (아직 병합/타겟 정의는 하지 않음 -
다음 단계인 "다국어 임베딩"에서 이 CSV들을 입력으로 사용).
"""

import traceback

import collect_dart
import collect_macro
import collect_bigkinds
import collect_global_news


def run_step(name, func):
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    try:
        func()
    except Exception:
        print(f"⚠ {name} 단계 실패:")
        traceback.print_exc()


if __name__ == "__main__":
    run_step("1. DART 공시 수집", collect_dart.main)
    run_step("2. 거시지표 수집 (ECOS/FRED)", collect_macro.main)
    run_step("3. 빅카인즈 국내 뉴스 수집", collect_bigkinds.main)
    run_step("4. GDELT/NewsAPI 해외 뉴스 수집", collect_global_news.main)

    print("\n전체 수집 완료. raw_data/ 폴더를 확인하세요.")
