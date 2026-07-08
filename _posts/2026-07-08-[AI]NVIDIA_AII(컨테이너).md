# GPU/컨테이너 환경 검증 - 핵심 기술 설명

이 주제를 마스터하려면 아래 4가지 핵심 기술 스택의 **작동 원리와 순서**를 이해해야 합니다.

## 1. NVIDIA Container Toolkit (핵심 미들웨어)

**역할**: Docker/Podman/Containerd가 호스트의 GPU 하드웨어를 "인식"할 수 있게 해주는 브릿지 역할입니다.

**왜 필요한가?**
컨테이너는 기본적으로 격리된 환경이라 호스트의 GPU 디바이스 노드(`/dev/nvidia0` 등)나 드라이버 라이브러리에 접근할 수 없습니다. Container Toolkit이 이 매핑을 자동으로 처리합니다.

**설치 순서 (시험에 자주 나옴)**:
```
1. GPG 키 등록 (패키지 무결성 보장)
2. repository(.list) 파일 등록
3. apt-get update (패키지 인덱스 갱신)
4. apt-get install -y nvidia-container-toolkit  ← 이 단계가 핵심
5. nvidia-ctk runtime configure --runtime docker (daemon.json 수정)
6. systemctl restart docker  ← 반드시 필요! (데몬은 재시작 시에만 설정 다시 읽음)
```

⚠️ **시험 포인트**: 4번 이후 "다음 단계는?"이라고 물으면 재부팅이 아니라 **패키지 설치**가 먼저입니다. 5번 이후 "다음 단계는?"이라고 물으면 **Docker 재시작**입니다. 이 두 단계를 헷갈리지 않아야 합니다.

## 2. --gpus 플래그 문법 (GPU 자원 할당)

### 어떤 명령어에서 사용하는가?

`--gpus`는 **`docker run`** 명령어의 옵션입니다. Docker 19.03 버전부터 NVIDIA Container Toolkit과 함께 정식 지원되기 시작했습니다.

**전체 명령어 구조**:
```bash
docker run [옵션들] <이미지명> [컨테이너 내부에서 실행할 명령]
```

`--gpus`는 이 "옵션들" 자리에 들어가며, 컨테이너를 **생성/실행하는 시점**에만 지정할 수 있습니다. (이미 실행 중인 컨테이너에 나중에 추가할 수 없음 → 이 경우 컨테이너를 새로 생성해야 함)

### `--gpus` 옵션의 세부 문법

| 문법 | 의미 | 예시 |
|---|---|---|
| `--gpus all` | 호스트의 **모든 GPU**를 컨테이너에 노출 | `docker run --gpus all ...` |
| `--gpus N` (숫자) | GPU를 **개수**로만 지정 (어떤 GPU인지는 런타임이 결정) | `docker run --gpus 2 ...` (GPU 2개 할당) |
| `--gpus '"device=0,2"'` | **특정 GPU 인덱스**를 지정 | 0번, 2번 GPU만 |
| `--gpus '"device=GPU-UUID"'` | GPU의 **UUID**로 지정 (멀티테넌트 환경에서 더 안전) | `nvidia-smi -L`로 UUID 확인 후 사용 |
| `--gpus '"capabilities=utility"'` | GPU의 **특정 기능(capability)**만 노출 (compute, utility, graphics 등) | 모니터링 전용 컨테이너 등 |

⚠️ **문법 주의**: `device=0,2`처럼 콤마로 구분된 값을 지정할 때는 반드시 **큰따옴표를 작은따옴표로 감싸는 이중 인용**(`'"..."'`)이 필요합니다. Shell이 콤마와 등호를 잘못 해석하지 않도록 하는 문법입니다.

### 왜 이 옵션이 "필요"한가 (동작 원리)

`docker run` 명령이 실행되면 Docker 데몬은 컨테이너 생성 요청을 **NVIDIA Container Runtime**(`nvidia-container-runtime`)에 넘깁니다. 이때 `--gpus` 플래그가 있어야만:

1. 지정된 GPU 디바이스 노드(`/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm` 등)를 컨테이너 네임스페이스에 매핑
2. 호스트의 NVIDIA 드라이버 라이브러리(`libnvidia-ml.so` 등)를 컨테이너 내부로 마운트
3. CUDA 유저스페이스와 커널 드라이버 간의 통신 경로 연결

이 세 가지가 **자동으로** 이루어집니다. `--gpus` 없이 실행하면 이 과정이 전혀 발생하지 않아 컨테이너 내부에서 `nvidia-smi`를 실행해도 "command not found" 또는 GPU가 아예 인식되지 않습니다.

### 실전 명령어 조합 예시

```bash
# 모든 GPU + smoke test
docker run --gpus all --rm nvcr.io/nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi

# 특정 GPU(0,2번)만 할당해서 학습 컨테이너 실행
docker run --gpus '"device=0,2"' -it --rm pytorch/pytorch:latest python train.py

# GPU 2개, 백그라운드 실행 (멀티테넌트 환경)
docker run --gpus 2 -d --name training_job nvcr.io/nvidia/pytorch:24.01-py3
```

### 레거시 방식과 혼용 시 주의점

| 항목 | 레거시 (nvidia-docker2) | 최신 방식 |
|---|---|---|
| 사용 명령 | `docker run` (별도 런타임 `nvidia-docker` 필요) | `docker run --gpus` (표준 docker에 통합) |
| GPU 지정 방법 | `-e NVIDIA_VISIBLE_DEVICES=0,2` (환경변수) | `--gpus '"device=0,2"'` |
| 우선순위 | 낮음 | `--gpus`가 있으면 이게 우선 적용됨 |

⚠️ **시험 함정**: 두 방식을 동시에 사용하면 혼란이 생길 수 있으므로, 최신 환경(Docker 19.03+, NVIDIA Container Toolkit 사용)에서는 **`--gpus` 플래그만 사용하는 것이 표준**이라고 기억하시면 됩니다.

## 3. "Smoke Test" — nvidia-smi 검증 로직

컨테이너에서 GPU 접근이 되는지 확인하는 **정석 커맨드**:
```bash
docker run --gpus all --rm nvcr.io/nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

이 명령이 검증하는 3가지 계층:
1. **`--gpus all`**: NVIDIA Container Toolkit이 정상 작동하는지
2. **`nvcr.io/nvidia/cuda` 이미지**: NGC의 공식 CUDA 이미지에 드라이버와 통신할 유저스페이스 라이브러리가 있는지
3. **`nvidia-smi` 실행 결과**: 실제로 GPU 테이블(온도, 메모리, 사용률)이 출력되는지 → 물리 하드웨어 → 커널 드라이버 → 컨테이너 런타임 → 툴킷까지 **전체 스택이 정상**임을 증명

⚠️ **오답 패턴**: `ls -la`나 `systemctl` 같은 명령은 컨테이너가 "실행"되는 것만 확인할 뿐, **GPU 접근 가능 여부는 검증하지 못함**. `--gpus` 플래그 없이 `nvidia-smi`를 실행하면 GPU가 안 보이므로 이 역시 오답 함정입니다.

## 4. NGC (NVIDIA GPU Cloud) 인증

**개념**: NGC는 AI 최적화 컨테이너/모델/SDK의 중앙 레포지토리입니다. Private 컨테이너를 pull하려면 인증이 필요합니다.

**인증 순서**:
```bash
ngc config set   # ← 이게 최초 필수 단계 (API Key 입력 요구)
```
- 이 명령 실행 시 NGC 포털에서 발급받은 **API Key**를 입력하라는 프롬프트가 뜸
- 결과물: `~/.ngc/config` 파일 생성 (인증 토큰, org/team 정보 저장)

**"Authentication failed" 트러블슈팅**:
- 원인 대부분 → API Key를 입력하지 않았거나 만료된 키 사용
- 해결 → `ngc config set` 재실행 후 올바른 키 입력
- ❌ `docker restart`는 무관 (NGC CLI 인증은 애플리케이션 레벨 문제, 컨테이너 런타임 문제 아님)

# NGC(NVIDIA GPU Cloud) 사용법 상세 설명

| NGC에 있는 것 | 용도 |
|---|---|
| 컨테이너 이미지 (`nvcr.io/nvidia/pytorch` 등) | CUDA/드라이버가 최적화된 사전 빌드 컨테이너 |
| 사전학습 모델 (Pretrained Models) | BERT, ResNet 등 바로 쓸 수 있는 모델 가중치 |
| SDK/헬름차트 | NeMo, Triton, Riva 등 NVIDIA AI 소프트웨어 |
| Resources | 학습 스크립트, 데이터셋 예제 등 |

즉, **NGC는 "무엇을 다운로드해서 쓸 것인가"를 관리하는 곳**이고, 클러스터(DGX 노드들, BCM으로 관리되는 GPU 서버들)는 **NGC에서 받아온 컨테이너를 실행하는 장소**입니다. 클러스터 자체를 NGC 계정에 등록하는 절차는 없습니다.

```
[NGC 레지스트리] ---(pull)---> [DGX 클러스터 노드] ---(docker run --gpus all)---> [실행]
   컨테이너/모델 저장소            실제 GPU가 있는 곳
```

##  NGC CLI 인증 흐름 (실제 사용 절차)

### 1. API Key 발급
1. NGC 웹포털(ngc.nvidia.com) 로그인
2. Setup → API Key → Generate API Key
3. 발급된 키를 안전하게 보관 (재발급 시 기존 키 무효화됨)

### 2. CLI 설치 후 인증
```bash
ngc config set
```
실행하면 대화형으로 다음을 순서대로 물어봅니다:
```
Enter API key: [여기에 API Key 입력]
Enter CLI output format type: [ascii/json/csv]
Enter org: [소속된 Organization 선택]
Enter team: [소속된 Team 선택, 없으면 no-team]
```

결과적으로 `~/.ngc/config` 파일이 생성되며, 이후 모든 `ngc`/`docker pull nvcr.io/...` 명령이 이 인증정보를 사용합니다.

### 3. 인증 확인/조회
```bash
ngc config get     # 현재 설정된 인증정보 확인 (이미 설정된 값 조회용)
```
⚠️ `ngc config get`은 "이미 설정이 끝난 후 확인"용이지, **최초 설정 단계에서는 쓸 수 없습니다** (Q4의 오답 포인트).

## NGC를 클러스터/DGX 환경에서 실제로 쓰는 3가지 시나리오

### 시나리오 A: 컨테이너 Pull (가장 흔함)
```bash
# Docker 로그인 (NGC는 Docker Registry 프로토콜도 지원)
docker login nvcr.io
Username: $oauthtoken
Password: <API Key 입력>

# 컨테이너 pull & 실행
docker pull nvcr.io/nvidia/pytorch:24.01-py3
docker run --gpus all -it nvcr.io/nvidia/pytorch:24.01-py3
```

### 시나리오 B: 모델 다운로드
```bash
ngc registry model list nvidia/*
ngc registry model download-version nvidia/nemo/megatron_gpt:1.0
```

### 시나리오 C: BCM/Kubernetes와의 연동
BCM으로 관리되는 클러스터나 Kubernetes(Run:ai 등) 환경에서는, **각 노드(worker)가 자체적으로 nvcr.io 레지스트리에 접근할 수 있도록** 이미지 pull 시크릿(Kubernetes의 `imagePullSecrets`)이나 노드 단위 `docker login` 설정이 필요합니다. 즉, "클러스터를 NGC에 등록"하는 게 아니라 **"각 노드가 NGC 레지스트리를 인증된 상태로 접근 가능하게" 설정**하는 것입니다.


## 📌 이 주제 문제를 풀 때의 판단 기준

| 상황 | 확인할 것 |
|---|---|
| "GPU가 컨테이너에서 안 보임" | `--gpus` 플래그 누락 여부 |
| "toolkit 설치했는데 GPU 여전히 안됨" | `systemctl restart docker` 했는지 |
| "특정 GPU만 쓰고 싶음" | `--gpus '"device=N,M"'` 문법 |
| "NGC pull 인증 실패" | `ngc config set`으로 API Key 입력했는지 |
| "GPU 접근을 완전히 검증하고 싶음" | `--gpus all` + NGC 공식 이미지 + `nvidia-smi` 조합 |




