"""
train_xgboost.py(회귀: 수익률 예측)와 별도로, "오를지 내릴지"를 직접 분류하는 버전.

이유: tolerance(±3%/±5%)로 회귀 결과를 채점하는 방식은, 손실함수(MSE)가
실제 평가 목표(방향/구간)와 어긋나 있었음 (MSE는 "변화없음"에 가깝게 수렴하도록
모델을 유도함). 분류로 바꾸면 손실함수 자체가 "맞았다/틀렸다"를 직접 최적화함.

기존 train_xgboost.py의 load_input/ensure_halt_flags/build_target/
time_based_split/build_feature_weights를 그대로 재사용 (회귀 스크립트는
건드리지 않고, 이 스크립트만 새로 추가).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).parent if "__file__" in dir() else Path.cwd()))
import train_xgboost as base  # load_input, build_target, time_based_split, build_feature_weights 재사용

MERGED_DATASET_PATH = base.INPUT_PATH
DATA_CUTOFF_DATE = base.DATA_CUTOFF_DATE


def add_direction_target(df: pd.DataFrame) -> pd.DataFrame:
    """next_return의 부호로 방향(1=상승, 0=하락/보합)을 만든다."""
    df = df.copy()
    df["방향"] = (df["next_return"] > 0).astype(int)
    return df


def evaluate_direction(y_true: np.ndarray, y_pred: np.ndarray, label: str) -> dict:
    """
    방향적중률 + 두 종류의 베이스라인과 비교:
      - 랜덤(50%): 이론적 하한
      - 다수클래스(항상 더 흔한 쪽으로 찍기): 실제로 주가가 오르는 날이
        내리는 날보다 약간 더 많은 경향이 있어서, 랜덤보다 공정한 비교 기준
    """
    accuracy = (y_pred == y_true).mean() * 100

    majority_class = int(y_true.mean() > 0.5)
    majority_baseline_acc = (y_true == majority_class).mean() * 100

    tp = ((y_pred == 1) & (y_true == 1)).sum()
    tn = ((y_pred == 0) & (y_true == 0)).sum()
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()

    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")

    print(f"\n[{label}] 방향적중률: {accuracy:.2f}% "
          f"(랜덤=50.00%, 다수클래스베이스라인={majority_baseline_acc:.2f}%)")
    print(f"  혼동행렬: TP={tp} FP={fp} / FN={fn} TN={tn}")
    print(f"  상승 예측 시 precision={precision:.3f}, recall={recall:.3f}")

    return {
        "label": label, "accuracy": accuracy,
        "majority_baseline_acc": majority_baseline_acc,
        "precision": precision, "recall": recall,
    }


def fit_and_evaluate_classifier(train, val, test, feature_cols, tag: str):
    print(f"\n{'='*60}\n[{tag}-분류] feature 수: {len(feature_cols)}\n{'='*60}")

    X_train, y_train = train[feature_cols], train["방향"]
    X_val, y_val = val[feature_cols], val["방향"]
    X_test, y_test = test[feature_cols], test["방향"]

    print(f"Train 상승비율: {y_train.mean()*100:.1f}% / Val: {y_val.mean()*100:.1f}% / Test: {y_test.mean()*100:.1f}%")

    feature_weights = base.build_feature_weights(feature_cols)

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        enable_categorical=True,
        early_stopping_rounds=20,
        eval_metric="logloss",
        random_state=42,
        feature_weights=feature_weights,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"실제 사용된 나무 개수: {model.best_iteration + 1} / {model.n_estimators}")

    val_pred = model.predict(X_val)
    test_pred = model.predict(X_test)

    val_result = evaluate_direction(y_val.values, val_pred, f"[{tag}] Validation")
    test_result = evaluate_direction(y_test.values, test_pred, f"[{tag}] Test")

    import shap
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_val)
    shap_importance = pd.Series(np.abs(shap_values).mean(axis=0), index=feature_cols).sort_values(ascending=False)
    print(f"\n[{tag}-분류] SHAP 기준 변수중요도 Top 10:\n{shap_importance.head(10)}")

    model.save_model(f"raw_data/xgb_output/xgb_classifier_{tag}.json")

    return model, val_result, test_result, shap_importance


def main():
    print(f"입력 로딩: {MERGED_DATASET_PATH}")
    df = base.load_input(MERGED_DATASET_PATH)
    df["종목코드"] = df["종목코드"].astype("category")

    cutoff = pd.Timestamp(DATA_CUTOFF_DATE)
    df = df[df["날짜"] <= cutoff].copy()

    df = base.build_target(df)
    df = add_direction_target(df)

    train, val, test = base.time_based_split(df)

    feature_cols = [c for c in df.columns if c not in base.DROP_COLS + ["방향"]]

    model, val_result, test_result, shap_importance = fit_and_evaluate_classifier(
        train, val, test, feature_cols, tag="direction_full"
    )

    print(f"\n{'='*60}\n=== 회귀(next_xgboost.py) vs 분류(이 스크립트) 비교용 참고 ===")
    print(f"방향적중률 - Val: {val_result['accuracy']:.2f}% (다수클래스 베이스라인 {val_result['majority_baseline_acc']:.2f}%)")
    print(f"방향적중률 - Test: {test_result['accuracy']:.2f}% (다수클래스 베이스라인 {test_result['majority_baseline_acc']:.2f}%)")


if __name__ == "__main__":
    main()
