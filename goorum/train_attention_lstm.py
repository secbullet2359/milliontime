"""
Attention-LSTM 학습 (방향 C)
    입력: 뉴스 시퀀스 (샘플수, 7, 769) - 종목 공통, 그대로
    출력: 종목별 수익률 (샘플수, 50) - Dense(50)
    -> 같은 공유 뉴스 표현(context vector)에 대해, 종목마다 다른 가중치를
       학습해서 "이 종목이 이런 뉴스 흐름에 얼마나/어느 방향으로 반응하는지"를
       종목별로 다르게 예측하게 됨.

거래정지 등으로 NaN이 섞인 종목/날짜는 masked MSE loss로 그 부분만 제외하고 계산.

⚠ 이 샌드박스는 네트워크 차단으로 TensorFlow를 설치할 수 없어 실행은
   못 해봤음 (문법만 검증). 실제 실행은 사용자 환경에서: pip install tensorflow
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.layers import Input, LSTM, Dense, Softmax
from tensorflow.keras.models import Model
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint


@keras.saving.register_keras_serializable(package="AttentionLSTM")
class WeightedSum(keras.layers.Layer):
    """
    lstm_out(batch,7,32)과 attention_weights(batch,7,1)를 받아 시간축(axis=1)으로
    가중합해서 context_vector(batch,32)를 만든다.
    ⚠ tf.reduce_sum(...)을 함수형 API에 직접 쓰면 모델을 .keras로 저장했다가
    다시 불러올 때 "Could not locate function" 에러가 남 (익명 연산이라 복원 불가).
    정식 Layer로 등록해두면 저장/로딩이 안정적으로 됨.
    """
    def call(self, inputs):
        lstm_out, attention_weights = inputs
        return tf.reduce_sum(lstm_out * attention_weights, axis=1)

INPUT_DIR = Path("/home/claude/news_collection/raw_data/lstm_input")
OUTPUT_DIR = Path("/home/claude/news_collection/raw_data/lstm_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SIZE = 7
FEATURE_DIM = 769
LSTM_UNITS = 32
VAL_RATIO = 0.2
EPOCHS = 30
BATCH_SIZE = 16


def masked_mse(y_true, y_pred):
    """NaN(거래정지 등으로 무효한 종목·날짜)을 loss 계산에서 제외."""
    mask = tf.cast(~tf.math.is_nan(y_true), tf.float32)
    y_true_safe = tf.where(tf.math.is_nan(y_true), tf.zeros_like(y_true), y_true)
    squared_error = tf.square(y_true_safe - y_pred) * mask
    # 배치 전체에서 유효한 값 개수로 나눔 (0으로 나누는 것 방지용 최소값 1e-8)
    return tf.reduce_sum(squared_error) / (tf.reduce_sum(mask) + 1e-8)


def build_model(num_stocks: int, window_size: int = WINDOW_SIZE,
                feature_dim: int = FEATURE_DIM, lstm_units: int = LSTM_UNITS) -> Model:
    inputs = Input(shape=(window_size, feature_dim))
    lstm_out = LSTM(lstm_units, return_sequences=True)(inputs)              # (batch, 7, 32)

    attention_scores = Dense(1, activation="tanh")(lstm_out)                 # (batch, 7, 1)
    attention_weights = Softmax(axis=1, name="attention_weights")(attention_scores)

    context_vector = WeightedSum()([lstm_out, attention_weights])           # (batch, 32) - 종목 공통

    # 여기서부터 종목별로 분기: Dense(num_stocks)의 각 출력 유닛이
    # "이 종목은 공유된 뉴스 표현을 이렇게 반영한다"는 자기만의 가중치를 가짐
    output = Dense(num_stocks, name="stock_returns")(context_vector)         # (batch, 50)

    model = Model(inputs=inputs, outputs=[output, attention_weights])
    model.compile(optimizer="adam", loss=[masked_mse, None])
    return model


def time_based_split(X_seq, y_seq, val_ratio: float = VAL_RATIO):
    n_val = int(len(X_seq) * val_ratio)
    n_train = len(X_seq) - n_val
    return (X_seq[:n_train], y_seq[:n_train]), (X_seq[n_train:], y_seq[n_train:])


def main():
    data = np.load(INPUT_DIR / "lstm_sequences.npz")
    X_seq, y_seq = data["X_seq"], data["y_seq"]
    dates = pd.read_csv(INPUT_DIR / "lstm_sequence_dates.csv", parse_dates=["날짜"])["날짜"]

    with open(INPUT_DIR / "stock_order.json", encoding="utf-8") as f:
        stock_order = json.load(f)
    num_stocks = len(stock_order)

    print(f"전체 시퀀스: {X_seq.shape}, target: {y_seq.shape} (종목수={num_stocks})")

    (X_train, y_train), (X_val, y_val) = time_based_split(X_seq, y_seq)
    print(f"Train: {len(X_train)}개 ({dates.iloc[0].date()} ~ {dates.iloc[len(X_train)-1].date()})")
    print(f"Val:   {len(X_val)}개 ({dates.iloc[len(X_train)].date()} ~ {dates.iloc[-1].date()})")

    model = build_model(num_stocks=num_stocks)
    model.summary()

    callbacks = [
        # validation loss가 5 epoch 동안 개선 없으면 조기종료
        # (30 epoch을 다 안 채워도 되니, 예상보다 오래 걸릴 걱정을 줄여줌)
        EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True, verbose=1),
        # 매 epoch마다 저장 -> 중간에 끊겨도 마지막으로 저장된 지점부터 다시 볼 수 있음
        ModelCheckpoint(
            OUTPUT_DIR / "attention_lstm_checkpoint.keras",
            save_best_only=True, monitor="val_loss", verbose=0,
        ),
    ]

    import time
    start = time.time()
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        callbacks=callbacks,
        verbose=2,
    )
    print(f"\n학습 소요 시간: {time.time() - start:.1f}초 "
          f"(실제 진행된 epoch 수: {len(history.history['loss'])}/{EPOCHS})")

    model.save(OUTPUT_DIR / "attention_lstm_model.keras")
    print(f"\n모델 저장 완료: {OUTPUT_DIR / 'attention_lstm_model.keras'}")

    # ------------------------------------------------------------------
    # 전체 기간 일괄 예측 -> wide(50열) 결과를 long(종목코드 1열) 형태로 변환
    # ------------------------------------------------------------------
    scores, attn = model.predict(X_seq, batch_size=BATCH_SIZE)  # scores: (샘플수, 50)

    score_df = pd.DataFrame(scores, columns=stock_order)
    score_df.insert(0, "날짜", dates.values)

    long_df = score_df.melt(id_vars="날짜", var_name="종목코드",
                             value_name="news_influence_score_per_stock")
    long_df.to_csv(OUTPUT_DIR / "news_influence_score_per_stock.csv",
                    index=False, encoding="utf-8-sig")
    print(f"\n종목별 news_influence_score 저장: "
          f"{OUTPUT_DIR / 'news_influence_score_per_stock.csv'} ({len(long_df)}행 = "
          f"{len(dates)}일 x {num_stocks}종목)")

    # attention_weights는 종목과 무관 (공유된 뉴스 시퀀스에 대한 가중치) - 날짜별로만 저장
    attn_flat = attn.reshape(attn.shape[0], attn.shape[1])
    attn_df = pd.DataFrame(attn_flat, columns=[f"day_minus_{WINDOW_SIZE - i}" for i in range(WINDOW_SIZE)])
    attn_df.insert(0, "날짜", dates.values)
    attn_df.to_csv(OUTPUT_DIR / "attention_weights.csv", index=False, encoding="utf-8-sig")
    print(f"attention_weights 저장: {OUTPUT_DIR / 'attention_weights.csv'}")

    print(f"\n최종 validation loss: {history.history['val_loss'][-1]:.6f}")


if __name__ == "__main__":
    main()
