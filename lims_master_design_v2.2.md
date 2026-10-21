# 도금강판 연구개발 특화 LIMS 통합 기술 백서 및 마스터 설계서 (v2.2)

> **문서 버전:** v2.2 (Full Master Specification)
> **작성일:** 2026-10-21 (KST)
> **작성:** 황현석 (표면연구그룹)
> **대상 독자:** 도금강판 연구원, 시험 담당자, LIMS 개발자, 인프라 관리자
> **문서 구성:** 1~11장은 "무엇을, 어떻게 만드는가"(구조·데이터·파이프라인·구현 방법)만 기술합니다. "왜 이렇게 결정했는가"는 **12장 설계 결정 이력**에 모았습니다. 본문 곳곳의 `[D-xx]` 표시는 12장의 해당 결정 번호입니다.

---

## 1. 시스템 개요

### 1.1 목적

연구원 20명 내외, 4~5개 팀이 만드는 도금 시편의 **이력(어디서 태어나 무엇을 겪었는가)** 과 **시험 데이터(사진·수치·분석 파일)** 를 한곳에 쌓는 연구실 전용 LIMS입니다.

### 1.2 한 줄 요약

> 도금 조건은 **CGL 모사장치 HMI 화면에서 프리셋을 눌러** 입력하고, 시편은 **약식번호 10자** 하나로 원소재부터 SEM 조각까지 추적하며, 사진·분석 파일은 **파일명만 맞추면 자동으로 제자리에 붙는** 시스템.

### 1.3 범위

| 구분 | 포함 | 제외(현 단계) |
| :--- | :--- | :--- |
| 이력 | 원소재 로트 → 공정런(도금 1회) → 원판 → 쿠폰 → 분석 조각, 후처리 이벤트 | 공장 생산 코일 이력 |
| 시험 | 시험런(CCT, SST, SEM, 전기화학, 가공 등), 주기별 결과, 첨부 파일 | 장비 직접 제어 |
| 조회 | 시편 상세·계보, 조건 검색, Excel 내보내기 | 관리자용 KPI·입력률 대시보드 |
| 연동 | CGL 모사장치 HMI(조건 입력), 장비 파일 업로드 | PLC 실행기록 자동 수신(3단계) |

---

## 2. 설계 원칙 (7대 원칙)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           7대 핵심 설계 원칙                             │
│                                                                         │
│ 1. 혈통(Genealogy)과 활동(Event)의 분리                                 │
│ 2. 물리적 조각이 생기면 새 번호 (길이 불변)                              │
│ 3. 물리적 표기의 이원화 (금속 레이저 각인 vs 실링 테이프 임시 표기)       │
│ 4. 규칙은 엄격하게, 시험 확장은 유연하게 (템플릿 + JSONB)                │
│ 5. 누락은 강제가 아니라 "입력이 가장 쉬운 길"로 줄인다                   │
│ 6. 한 번 입력, 가능하면 자동 입력 (상속·프리셋·파일명 매칭)              │
│ 7. 모든 공정조건은 목표값과 실측값을 따로 기록한다                       │
└─────────────────────────────────────────────────────────────────────────┘
```

1. **혈통과 활동의 분리** — 시편번호에는 "어디서 태어났는가"만 담고, "무슨 시험을 치르는가"는 시험런으로 연결합니다. `[D-01]`
2. **길이 불변** — 원판·쿠폰·SEM 조각 모두 정식 16자, 약식 10자. 부모-자식 관계는 DB가 기억합니다. `[D-02]`
3. **표기 이원화** — 금속에는 영구 식별자, 실링 테이프에는 시험 정보. `[D-05]`
4. **유연한 시험 확장** — 공통 컬럼 + JSONB, 필드 정의는 시험 템플릿이 관리합니다. `[D-09]`
5. **누락 최소화 방식** — 알림·예정일 강제·관리자 감시는 두지 않습니다. 입력 단계를 줄이고, 빈칸은 연구원 본인 화면에서 자연스럽게 보이게만 합니다. `[D-16]`
6. **자동 입력 우선** — 상위 단계 값은 하위로 상속하고, 도금 조건은 프리셋에서, 파일은 파일명으로 자동 연결합니다. `[D-15]`
7. **목표·실측 분리** — 레시피는 목표값(계획)이고, 실측값은 측정할 때마다 같은 파라미터 키로 따로 쌓입니다. 조회·검색은 "실측이 있으면 실측, 없으면 목표"를 쓰고 값마다 출처를 표시합니다. `[D-29]`

---

## 3. 시편번호 체계 (Specimen ID System v2.2)

### 3.1 번호 구조

```
   M 2 0 6 K  -  2 6 P 4  -  C 0 1 5 3
   └─조건부─┘    └과제코드┘    │ └일련번호┘
     (5자)        (4자)      단계  (숫자 4자리)
     표시용 라벨   ────── 약식번호(10자) = 업무 고유키 ──────
```

| 구분 | 형식 | 예시 | 길이 | 역할 |
| :--- | :--- | :--- | :--- | :--- |
| **약식번호** | `과제코드-단계일련번호` | `26P4-C0153` | 10자 | **업무 고유키.** 전사 유일. SEM 몰드, 장비 파일명, QR 내용 |
| **정식번호** | `조건부-약식번호` | `M206K-26P4-C0153` | 16자 | 레이저 각인·라벨용 **표시 문자열** |
| 내부키 | BIGSERIAL | `48213` | - | DB 기본키(화면에 노출하지 않음) |

- 조건부는 **기본키가 아닙니다.** 공정런 데이터에서 자동 생성되는 라벨입니다. `[D-10]`
- 각인 시점의 정식번호는 `engraved_label`로 영구 보관합니다. 이후 조건이 정정되면 화면에 "각인 라벨 ≠ 현재 조건" 표시만 띄웁니다. 시편 신원(약식번호)은 바뀌지 않습니다.

### 3.2 조건부 5자 (자동 생성)

| 자리 | 의미 | 생성 규칙 |
| :---: | :--- | :--- |
| 1 | 도금 계열 | 원판의 목표 레시피에 사용한 프리셋의 계열 코드 (부록 A) |
| 2 | 도금욕 조성 | 숫자 1자. 계열 글자와 붙여 읽음(`M2`, `Z1`). 욕 조성이 코드 허용오차를 벗어나면 `X` `[D-12]` |
| 3~4 | 단면 목표 부착량 | `round_half_up(목표 g/m² ÷ 10)`을 2자리로. 45 → `05`, 60 → `06` `[D-13]` |
| 5 | 소둔 조건 | 목표 최고판온·이슬점·균열시간을 부록 D와 비교해 일치하는 코드, 없으면 `X` |

조건부는 **원판(P) 단위로 목표값에서** 만듭니다. 같은 공정런 안에서 원판마다 목표가 다를 수 있기 때문입니다(6.9절 시리즈 실험). 쿠폰·조각은 부모 원판의 조건부를 물려받습니다. `[D-31]` `[D-32]`

```python
# app/services/condition_code.py (개념 코드)
def build_condition_code(panel: Specimen, codes: CodeBook, basis="target") -> str:
    rcp = effective_recipe(panel, basis)   # target: 기본 레시피 + 원판별 목표 변경
                                           # actual: 각 키의 대표 실측값(없으면 목표)
    sys_code = panel.process_run.preset.coating_system          # 'M'
    bath = codes.match_bath(sys_code, rcp["pot"])               # '2' 또는 'X'
    cw = f"{round_half_up(rcp['out']['cw'] / 10):02d}"           # '06'
    ann = codes.match_annealing(rcp["rth"], rcp["rts"])         # 'K' 또는 'X'
    return f"{sys_code}{bath}{cw}{ann}"
```

- `X`는 "비표준 조건, 상세는 공정런 참조"라는 뜻입니다. 실제 조건값은 항상 공정런의 `recipe` JSON이 원본입니다.
- 각인·라벨에는 **목표 기준 조건부**(`basis="target"`)만 씁니다. 실측이 들어온 뒤 같은 함수를 `basis="actual"`로 돌린 **실측 기준 조건부**는 시편 상세 화면에만 표시합니다(예: `각인 M206K · 실측 기준 M205K`). 시편 신원은 바뀌지 않습니다.

### 3.3 과제코드 4자

- 사내 과제번호 `2026P1234` → `26P4` (연도 2자리 + 성격 1자 + 일련번호 끝 1자리). `[D-08]`
- 같은 해 끝자리가 겹치면 시스템이 `26PA`, `26PB`…를 배정하고, 과제 선택 화면에 `26PA = 2026P1004`처럼 원 번호를 항상 함께 표시합니다.
- 과제 미연계 업무용 **공통 과제코드**를 둡니다. `[D-22]`

| 코드 | 용도 |
| :--- | :--- |
| `26X0` | 팀 공통 실험·기초 데이터 |
| `26X1` | 탐색 실험(과제 착수 전) |
| `26X9` | 고객 클레임·현장 문제 분석 |

### 3.4 단계 1자 + 일련번호 4자

| 단계 | 대상 | 크기 기준 |
| :---: | :--- | :--- |
| `P` | 도금원판 (모사장치 출구) | 200×300 mm 수준 |
| `C` | 시험편 (CCT/SST 평판, 가공 시편) | 70×150 mm 수준 |
| `S` | 분석용 조각 (SEM·XRD·GDS 마운팅) | 수 mm ~ 20 mm |

- 원소재 블랭크는 번호를 주지 않고 `materials` 테이블의 로트로 관리합니다. `[D-23]`
- 도장·화성처리처럼 자르지 않는 상태 변화는 새 번호 없이 **공정 이벤트**로 기록합니다.
- 일련번호는 **숫자 4자리, 연구원 자율 입력**입니다. 시스템은 입력란에 "다음 빈 번호"를 미리 채워 제안만 합니다. `[D-04]`
- 분기 시 일괄 발번: 원판 `P0102` → 쿠폰 8장을 만들면 `C0102`~`C0109`처럼 시작 번호와 개수만 입력합니다. 중간에 이미 쓰인 번호가 있으면 저장 전에 충돌 목록을 보여줍니다.

### 3.5 중복 검사 규칙

> **유일성 기준 = 약식번호(`과제코드 + 단계 + 일련번호`)** `[D-03]`

```sql
ALTER TABLE specimens ADD CONSTRAINT uq_short UNIQUE (project_code, stage, serial_no);
```

조건부가 달라도 같은 과제에서 `C0153`은 하나뿐입니다. 따라서 약식번호 10자만으로 시편 1개를 특정하고, 장비 파일명 매칭(7장 P5)의 기반이 됩니다.

### 3.6 물리적 표기

```
┌────────────────────────────────────────────────────────────────────────┐
│ [시편 뒷면 상단 10mm 마진]                                             │
│  ┌───────────────────────────┐                                         │
│  │ ■■■■■  M206K-26P4-C0153  │ ◄── 영구 레이저 각인                     │
│  │ ■■■■■                    │     DataMatrix 5×5mm(내용=약식번호) + 16자│
│  └───────────────────────────┘                                         │
│ ══════════════════════════════════════════════════════════════════════ │
│  ┌───────────────────────────┐                                         │
│  │ TR-CCT-26001 / Slot A-03  │ ◄── 실링 테이프 위 임시 표기(시험 중만)  │
│  └───────────────────────────┘                                         │
└────────────────────────────────────────────────────────────────────────┘
```

| 대상 | 표기 | 시스템 출력 |
| :--- | :--- | :--- |
| 원판·쿠폰 | 레이저 각인 | [각인 CSV] 버튼 — `short_id, display_id, datamatrix_text` |
| SEM 몰드 | 약식번호 라벨 스티커 | [라벨 출력] — 라벨프린터용 PDF/CSV |
| 시험 중 시편 | 실링 테이프 수기 또는 라벨 | [시험런 라벨] — 시험런 번호 + 슬롯 |

QR·DataMatrix에는 **약식번호만** 넣습니다. 스캐너로 읽으면 곧바로 시편 상세가 열립니다.

---

## 4. 전체 구조

### 4.1 개념 구조

```
기준 정보   [과제] [사용자·팀] [마스터 코드] [시험 템플릿] [공정 프리셋]
              │                                │              │
혈통        [원소재 로트] ──► [공정런] ──► [시편 P] ──► [시편 C] ──► [시편 S]
                              (목표 recipe)  (원판별 목표 변경)  parent_id 트리
                                  │            │        │
실측                          [실측값(세션)] [실측값(원판)] [실측값(쿠폰)]  ◄── [욕 분석]
                                  └────────────┴────────┴──► [대표값 캐시] ──► 검색·비교
                                                └── [공정 이벤트]
활동        [시험런] ◄── [시험런 탑승(N:M)] ──► [시편]
               │
               └──► [시험 결과(주기별, metrics JSONB)] ──► [첨부 파일]
공통        [감사 로그]  [미분류 파일함]
```

### 4.2 시스템 계층

```
┌──────────────────────────────────────────────────────────────────────┐
│ 브라우저 (PC / 태블릿)                                               │
│  • 서버 렌더링 화면: Jinja2 템플릿 + HTMX(부분 갱신) + Alpine.js      │
│  • 공정조건 입력기: CGL HMI 모듈(Vanilla JS, SVG 미믹) 재사용         │
│  • 바코드 스캐너(키보드 입력 방식) → 검색창 자동 포커스               │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP (HTML 조각 + JSON API)
┌──────────────────────────────▼───────────────────────────────────────┐
│ 백엔드: Python 3.11 + FastAPI (uvicorn, supervisord로 상시 구동)      │
│  routers/   화면·API 엔드포인트                                       │
│  services/  번호 발급 · 조건부 생성 · 계보 조회 · 파일 수집 · 내보내기 │
│  workers/   썸네일 생성 · (2단계) 폴더 감시                           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ SQLAlchemy 2.0 + Alembic(마이그레이션)
┌──────────────────────────────▼───────────────────────────────────────┐
│ 저장소                                                                │
│  • PostgreSQL 15+ : 정규 테이블 + JSONB(recipe, metrics, conditions)  │
│  • 파일: /data/lims/files/{yyyy}/{short_id}/  원본 + WebP 썸네일      │
│  • 백업: 매일 pg_dump + 파일 rsync → 사내 백업 위치(11장 확인 필요)    │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.3 기술 스택

| 계층 | 선택 | 비고 |
| :--- | :--- | :--- |
| 언어·서버 | Python 3.11, FastAPI, uvicorn | 연구원 1인 개발·유지에 맞춤 `[D-17]` |
| 화면 | Jinja2 + HTMX + Alpine.js | 빌드 도구(npm) 불필요, 화면 대부분을 서버에서 렌더링 `[D-18]` |
| 공정조건 입력 | 기존 `CGL 모사장치 HMI.html`의 스크립트를 모듈로 분리 | 파라미터 사전·프리셋은 서버에서 공급 `[D-15]` |
| DB | PostgreSQL 15+, SQLAlchemy 2.0, Alembic | JSONB + GIN 인덱스 |
| 이미지 | Pillow (WebP 썸네일 400px / 1600px) | 원본은 그대로 보관 |
| 내보내기 | openpyxl (1단계), python-pptx (3단계) | |
| 검증 | Pydantic v2 | 템플릿 필드 정의 → 동적 검증 모델 |
| 테스트 | pytest + httpx | 번호 발급·조건부·파일명 파서 단위 테스트 필수 |
| 운영 | supervisord, cron(백업) | 회사 Docker 컨테이너 1개(Linux, 500 GB) 안에서 구동 |

### 4.4 코드 저장소 구조

```
lims/
├─ app/
│  ├─ main.py                 # FastAPI 앱, 라우터 등록, 정적 파일
│  ├─ config.py               # 경로·DB URL·업로드 한도 (환경변수)
│  ├─ db.py                   # 세션, Base
│  ├─ auth.py                 # 로그인·세션·권한
│  ├─ models/                 # SQLAlchemy 모델 (8장 DDL과 1:1)
│  ├─ schemas/                # Pydantic 입출력 스키마
│  ├─ routers/
│  │  ├─ home.py  specimens.py  process_runs.py  presets.py
│  │  ├─ test_runs.py  results.py  files.py  search.py  admin.py
│  ├─ services/
│  │  ├─ numbering.py         # 다음 빈 번호, 일괄 발번, 충돌 검사
│  │  ├─ condition_code.py    # 3.2절 조건부 생성 (목표/실측 기준)
│  │  ├─ actuals.py           # 6.6~6.8절 실측 기록·대표값 산출·편차
│  │  ├─ lineage.py           # 계보 재귀 조회
│  │  ├─ file_ingest.py       # 파일명 파서, 매칭, 저장, 미분류함
│  │  ├─ thumbnails.py
│  │  ├─ templates_engine.py  # 시험 템플릿 → 입력폼·검증
│  │  └─ export.py            # Excel (후에 PPT)
│  ├─ templates/              # Jinja2 화면
│  └─ static/
│     ├─ hmi/hmi-core.js      # HMI에서 분리한 미믹·열사이클·점검 로직
│     ├─ hmi/hmi-lims.js      # LIMS 기록 모드(저장 버튼, 프리셋 불러오기)
│     └─ css/ js/
├─ data/seed/
│  ├─ param_dictionary.json   # HMI의 구간·파라미터 사전 (단일 원본)
│  ├─ presets.json            # 공용 프리셋 초기값
│  ├─ master_codes.json       # 부록 A~D
│  └─ test_templates/*.json   # 팀별 대표 시험 템플릿
├─ alembic/
├─ scripts/  backup.sh  seed.py  import_excel.py
└─ tests/
```

---

## 5. 화면 구성

### 5.1 화면 목록 (6개)

| # | 화면 | 하는 일 | 핵심 동작 수 목표 |
| :---: | :--- | :--- | :--- |
| 1 | 내 작업(홈) | 내 진행 중 시험런, 최근 공정런, 내 미분류 파일 | - |
| 2 | 공정런 등록·실측 | HMI 미믹에서 프리셋 선택 → 조정 → 원판 N매 생성 / [실측] 탭에서 원판별 실측 입력 | 프리셋 1클릭 + 저장 1클릭 |
| 3 | 시편 상세 | 신상, 계보 타임라인, 시험 이력, 사진 갤러리, [분기] | 스캔 1회로 열림 |
| 4 | 시험런 | 시편×회차 결과 그리드, 사진 일괄 업로드 | 사진 20장 드래그 1회 |
| 5 | 검색·비교 | 조건·과제·시험·수치 필터, 2~5개 시편 나란히 보기, Excel | - |
| 6 | 관리 | 과제, 코드표, 프리셋, 시험 템플릿, 사용자 | - |

상단 공통 바: `[검색창(약식번호·코일번호·시험런·이름, 자동완성)] [+공정런] [+시험런]`. 바코드 스캐너는 키보드처럼 입력되므로 어느 화면에서든 스캔하면 검색창으로 들어가 해당 시편이 열립니다.

### 5.2 공정런 등록 화면 (HMI 기록 모드)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 공정런 등록   과제 [26P4 ▼]  원소재 [POS-26-8891 SPCC 0.8T ▼]  일자 [2026-10-21]│
│ 프리셋: [GI][GA][ZAM][AZ][AS][M1][M2●]  [내 프리셋 ▼]  [지난 공정런 복제 ▼]  │
├──────────────────────────────────────────────────────────────────────────────┤
│  (CGL 미믹 — 기존 HMI와 동일)                                                 │
│  NOF ─ RTH ─ RTS ─ SJC ─ RJC ─ OA ─ SNOUT ─ POT ─ A/K ─ GA ─ APC ─ W/Q         │
│        800°C  60s                      465   460°C 30kPa OFF                  │
│  구간 클릭 → 우측 패널에서 값 수정 / 프리셋 대비 바뀐 값은 굵게 + ● 표시     │
├───────────────────────────────┬──────────────────────────────────────────────┤
│ 열사이클 그래프 (기존 HMI)     │ 점검: ⚠ 이슬점 −20 °C — 통상 −30 °C 이하     │
├───────────────────────────────┴──────────────────────────────────────────────┤
│ 목표 부착량(단면) [60] g/m²   원판 [5]매   시작 번호 [P0101]   [시리즈 설정…] │
│ 조건부 미리보기: M206K   →  M206K-26P4-P0101 ~ P0105                          │
│ 메모 [                                  ]        [내 프리셋으로 저장] [저장] │
└──────────────────────────────────────────────────────────────────────────────┘
```

- HMI의 "PLC로 전송" 버튼은 이 모드에서 숨기고 **[저장]** 으로 바꿉니다.
- HMI의 점검 규칙(`checks()`)은 **경고만** 표시하고 저장을 막지 않습니다. 허용 범위 밖 값(파라미터 사전의 min/max)만 저장 전 확인을 한 번 받습니다.
- [시리즈 설정…]은 원판마다 목표를 다르게 주는 실험(예: 나이프 압력 20~60 kPa)을 위한 입력입니다(6.9절).

### 5.3 실측 입력 화면 (공정런 [실측] 탭)

```
PR-26-0137  M2 프리셋  2026-10-21  원판 5매                      [엑셀 붙여넣기] [욕 분석 적용]
┌─ 세션 공통 ────────────────────────────────────────────────────────────────────┐
│ 욕온  목표 460  실측 [458.5] °C [열전대]    이슬점  목표 −40  실측 [−36 ] °C [노점계] │
│ 욕 조성  목표 Al-26Zn-3Si-0.5Mg   실측  ICP 2026-10-21 적용 → Zn 25.1 / Si 2.9 / Mg 0.46 │
└────────────────────────────────────────────────────────────────────────────────┘
┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│ 원판         │ 최고판온 °C  │ 나이프 kPa   │ 부착량 윗면  │ 부착량 아랫면 │
│              │ 목표 800     │ 목표 30      │ 목표 60 g/m² │ 목표 60 g/m² │
├──────────────┼──────────────┼──────────────┼──────────────┼──────────────┤
│ 26P4-P0101   │ 796          │ 30           │ 54 ●         │ 58           │
│ 26P4-P0102   │ 802          │ 30           │ 57           │ 61           │
│ 26P4-P0103   │ ·            │ ·            │ [CW_MEASURE] │ [CW_MEASURE] │
└──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘
 · = 아직 실측 없음(목표값으로 간주)   ● = 허용편차 밖(색 표시만)   [CW_MEASURE] = 시험 결과에서 자동 채움
```

- 표의 열은 파라미터 사전에서 `"quick": true`로 지정한 키만 보여줍니다(초안: 욕온, 이슬점, 최고판온, 침지시간, 나이프 압력, 부착량 윗면·아랫면). [열 추가]로 다른 키도 입력할 수 있습니다.
- 모든 칸은 선택 입력입니다. 비워 두면 목표값으로 간주하고 출처를 "목표"로 표시합니다.

### 5.4 시험런 결과 그리드

```
TR-CCT-26001  CCT 1호기  2026-10-23 시작  템플릿 CCT_STD v1 (기본 8회, 7일 간격)
┌──────────────┬───────┬───────┬───────┬───────┬─────┬───────┬──────┐
│ 시편 \ 회차   │  W00  │  W01  │  W02  │  W03  │ ... │  W08  │ [+열] │
├──────────────┼───────┼───────┼───────┼───────┼─────┼───────┼──────┤
│ 26P4-C0102   │ [▣]0% │ [▣]0% │ [▣]0% │       │     │       │      │
│ 26P4-C0103   │ [▣]0% │ [▣]0% │ [▣]1% │       │     │       │      │
└──────────────┴───────┴───────┴───────┴───────┴─────┴───────┴──────┘
 셀 클릭 → 사진 + 적청률·백청률 빠른 입력   |   [사진 폴더 드래그] → 파일명으로 자동 배치
```

- 열(회차)은 템플릿 기본값으로 미리 그려두고, 연구원이 추가·삭제할 수 있습니다. 예정일이나 마감은 없습니다.
- 빈 셀은 옅은 회색으로만 보입니다. 이것이 누락을 드러내는 유일한 장치입니다. `[D-16]`

---

## 6. 공정조건 입력과 목표·실측 관리: CGL HMI 통합 설계

### 6.1 HMI 코드 재사용 방식

현재 `CGL 모사장치 HMI.html`은 한 파일 안에 ① 구간·파라미터 사전(`S`), ② 도금 종류별 프리셋(`PRE`), ③ 열사이클 계산(`cycle()`), ④ 점검 규칙(`checks()`), ⑤ 미믹 그리기(`drawMimic()`)를 갖고 있습니다. 이를 다음처럼 나눕니다.

| HMI 구성 요소 | LIMS에서의 위치 | 원본(단일 출처) |
| :--- | :--- | :--- |
| `S` 구간·파라미터 사전 | `data/seed/param_dictionary.json` → `GET /api/param-dictionary` | **LIMS 서버.** HMI도 이 파일을 읽도록 바꿈 |
| `PRE` 프리셋 | `process_presets` 테이블 → `GET /api/presets` | LIMS DB |
| `cycle()`, `checks()`, `drawMimic()` | `static/hmi/hmi-core.js` | 공통 JS 모듈 (HMI·LIMS가 같은 파일 사용) |
| PLC 전송·인터락·상태 | HMI 전용 (LIMS에는 미포함) | HMI |
| 저장·프리셋 불러오기 | `static/hmi/hmi-lims.js` | LIMS 전용 |

파라미터 사전에는 버전(`dict_version`, 예: `2026.10-1`)을 붙이고, 모든 공정런이 저장 당시 버전을 기록합니다. 구간이나 파라미터가 추가돼도 과거 공정런을 정확히 해석할 수 있습니다.

### 6.2 프리셋 3단계

| 범위 | 만드는 사람 | 예 |
| :--- | :--- | :--- |
| 공용(PUBLIC) | 관리자 | `GI`, `GA`, `ZAM`, `AZ`, `AS`, `M1`, `M2` (기존 HMI 프리셋 + 연구실 성분계) |
| 팀(TEAM) | 팀원 누구나 | "M2 저이슬점 표준" |
| 개인(PERSONAL) | 본인 | "내 0.5Mg 스크리닝 기본" |

- 프리셋은 **전체 레시피가 아니라 기본값과 다른 값만** 저장합니다(기존 HMI `PRE`와 같은 방식). 사전에 파라미터가 추가돼도 프리셋이 깨지지 않습니다.
- 각 프리셋은 `coating_system`, `bath_code`를 가지므로 조건부 1~2자리가 자동으로 정해집니다.
- **[지난 공정런 복제]**: 내 최근 공정런 10개를 목록으로 보여주고, 고르면 그 레시피가 그대로 채워집니다. 실제로 가장 자주 쓰일 입력 경로입니다.

### 6.3 저장 페이로드 (`POST /api/process-runs`)

```json
{
  "source": "manual",
  "dict_version": "2026.10-1",
  "preset_id": 12,
  "project_code": "26P4",
  "material_id": 31,
  "run_date": "2026-10-21",
  "coating_weight_target": 60,
  "panel_count": 5,
  "serial_start": 101,
  "recipe": {
    "nof":  {"on": false},
    "rth":  {"rate": 10, "T": 800, "H2": 5, "DP": -40},
    "rts":  {"t": 60},
    "sjc":  {"T": 680, "rate": 10},
    "rjc":  {"T": 460, "rate": 50, "H2": 30},
    "oa":   {"t": 20},
    "snout":{"SET": 465},
    "pot":  {"T": 460, "Al": 0.20, "Mg": 0, "Si": 0, "t": 3},
    "ak":   {"gas": "N2", "P": 30, "d": 10, "h": 250, "v": 500},
    "ga":   {"on": false},
    "apc":  {"rate": 15, "T": 300},
    "wq":   {"T": 40}
  },
  "series": {"key": "ak.P", "values": [20, 30, 40, 50, 60]},
  "changed_from_preset": ["rth.DP", "ak.P"],
  "warnings": ["이슬점 −40 °C"],
  "note": ""
}
```

`series`는 선택 항목입니다. 넣으면 원판 수만큼 값을 주고, 각 원판의 `target_overrides`에 저장됩니다(6.9절). `recipe.out.cw`가 단면 목표 부착량이며 `coating_weight_target` 컬럼과 같은 값입니다.

응답: `run_no`(예: `PR-26-0137`), 원판 목록과 원판별 목표 조건부(`26P4-P0101` `M206K` …).

### 6.4 서버 처리 순서

1. Pydantic으로 형식 검증 → 파라미터 사전의 min/max로 범위 재검증(브라우저 검증은 신뢰하지 않음).
2. 시리즈가 있으면 원판별 `target_overrides` 생성 → `condition_code.py`로 원판마다 목표 기준 조건부 생성(3.2절).
3. `numbering.py`로 `P0101`~`P0105` 충돌 검사 → 하나라도 겹치면 409와 충돌 목록 반환.
4. 한 트랜잭션에서 `process_runs` 1행 + `specimens` N행 생성. 원판은 공정런의 과제·원소재·조건을 상속.
5. `audit_log` 기록 → 응답 화면에서 [각인 CSV] [라벨 출력] 버튼 제공.

### 6.5 3단계: 장치 실행기록 자동 연동

모사장치가 실제 운전되면 HMI가 원판 1매의 사이클이 끝날 때마다 PV 시계열 파일과 구간별 요약(유지 구간의 평균·최소·최대)을 `POST /api/process-runs/{run_no}/actuals`로 보냅니다(출처 `pv`). 목표(레시피)는 1단계와 같은 `POST /api/process-runs`로 먼저 저장되므로, 장치 연동은 **실측 경로 하나만 자동으로 바뀌는** 구조입니다.

### 6.6 목표값–실측값 이중 기록 모델

모든 공정 파라미터는 목표값 1개와 실측값 0~N개를 가집니다. 둘은 파라미터 사전의 **같은 키**로 연결됩니다.

| 구분 | 저장 위치 | 개수 | 예 |
| :--- | :--- | :--- | :--- |
| 목표값 | `process_runs.recipe` + 원판 `specimens.target_overrides` | 원판당 키마다 1개 | `pot.T = 460` |
| 실측값 | `param_actuals` (긴 형식, 1측정 = 1행) | 0~N개 | `pot.T = 458.5 (열전대, 10:42)` |
| 대표값 | `effective_params` (캐시) | 시편·키마다 1개 | `458.5, 출처=수기, 수준=세션` |

**실측값의 수준(level).** 같은 키라도 어디에 걸린 값인지가 다릅니다. 파라미터 사전에 키마다 기본 수준을 정합니다.

| 수준 | 의미 | 대표 키 | `param_actuals` |
| :--- | :--- | :--- | :--- |
| 세션(run) | 같은 공정런의 모든 원판이 공유 | 욕 조성, 욕온, 로 분위기(H₂, 이슬점) | `specimen_id IS NULL` |
| 원판(P) | 모사장치는 원판을 1매씩 처리하므로 매수마다 다름 | 최고판온, 균열·침지 시간, 나이프 압력, 부착량, GA Fe% | `specimen_id = 원판` |
| 쿠폰·조각(C/S) | 원판 안 위치 편차 | 쿠폰별 부착량 재측정 | `specimen_id = 쿠폰` |

**파라미터 사전 확장.** 기존 HMI 항목에 `actual` 블록을 더하고, 설비 설정값이 아닌 **출력 특성** 구간 `out`을 새로 둡니다.

```json
{"id": "pot", "p": [
  {"k": "T", "l": "욕온", "u": "°C", "min": 400, "max": 720, "v": 460,
   "actual": {"level": "run", "tol": 3, "agg": "mean", "quick": true,
              "methods": ["열전대", "PV"], "pv_tag": "POT.TT01"}}
]},
{"id": "out", "nm": "OUT", "full": "출력 특성", "setpoint": false, "p": [
  {"k": "cw",        "l": "목표 부착량(단면)", "u": "g/m²", "min": 10, "max": 300, "v": 60},
  {"k": "cw_top",    "l": "부착량 윗면", "u": "g/m²", "target_from": "cw",
   "actual": {"level": "panel", "tol_pct": 10, "agg": "mean", "quick": true, "methods": ["중량법", "XRF"]}},
  {"k": "cw_bottom", "l": "부착량 아랫면", "u": "g/m²", "target_from": "cw",
   "actual": {"level": "panel", "tol_pct": 10, "agg": "mean", "quick": true, "methods": ["중량법", "XRF"]}},
  {"k": "fe_pct",    "l": "도금층 Fe", "u": "wt%", "only_if": "ga.on",
   "actual": {"level": "panel", "tol": 1.0, "agg": "mean", "methods": ["ICP", "XRF"]}}
]}
```

- `setpoint: false`인 구간은 HMI 미믹에 그리지 않고 LIMS 실측 화면에만 나타납니다.
- `tol`(절대) 또는 `tol_pct`(상대)는 편차 색 표시 기준입니다. 알림은 없습니다. `[D-36]`
- `agg`는 같은 키를 여러 번 잰 경우 대표값 계산법입니다(`mean`, `last`, `median`). 측정점별 원값은 `param_actuals.stats.points`에 모두 남습니다.

### 6.7 대표값(유효값) 산출 규칙

시편 하나의 키 하나에 대해 아래 순서로 첫 번째로 찾은 값을 대표값으로 씁니다.

```python
# app/services/actuals.py (개념 코드)
def effective_value(spec: Specimen, key: str) -> Effective:
    for node in lineage_up(spec):                 # 자신 → 부모 원판 (→ 조부모)
        rows = actuals(specimen_id=node.id, key=key)
        if rows:
            return Effective(agg(rows, key), source=rows[-1].source,
                             level=node.stage, inherited_from=None if node is spec else node.short_id)
    rows = actuals(process_run_id=spec.process_run_id, specimen_id=None, key=key)
    if rows:
        return Effective(agg(rows, key), source=rows[-1].source, level="run")
    return Effective(target_value(spec, key), source="target", level="target")
```

| 화면 배지 | 뜻 |
| :--- | :--- |
| `실측` | 이 시편에서 직접 잰 값 |
| `실측·P0102` | 부모 원판에서 잰 값을 상속 |
| `세션` | 공정런 공통으로 잰 값 |
| `PV` / `분석` / `시험` | 출처가 장치 로그 / 욕 분석 / 시험 결과 |
| `목표` | 실측이 없어 목표값으로 간주 |

- 값이 바뀔 때마다(`param_actuals` 추가·수정, 분기, 목표 변경) 해당 시편과 자손의 `effective_params`를 다시 계산합니다. 검색은 이 캐시 테이블을 씁니다.
- 검색·비교 화면에는 기준 토글을 둡니다: **[대표값(실측 우선)]** 기본 / [목표 기준] / [실측 있는 것만]. 같은 데이터를 계획 기준으로도, 실제 기준으로도 묶어 볼 수 있습니다. `[D-34]`
- 시편 상세의 공정 계보 카드에는 키마다 `목표 → 실측 (편차)`를 함께 표시합니다(예: `부착량 윗면 60 → 54 g/m² (−10%)`).

### 6.8 실측값이 들어오는 네 가지 경로

| 경로 | 언제 | 출처(`source`) | 단계 |
| :--- | :--- | :--- | :--- |
| ① 실측 탭 수기·엑셀 붙여넣기 | 도금 직후, 측정 후 | `manual` | 1단계 |
| ② 욕 분석 적용 | 욕 시료 분석 결과가 나왔을 때 | `lab` | 1단계 |
| ③ 시험 결과 연동 | `CW_MEASURE`, `GDS_PROFILE` 등 결과 저장 시 | `test` | 1단계 |
| ④ 장치 PV 로그 | 사이클 종료 시 | `pv` | 3단계 |

- **② 욕 분석:** 욕 시료 1회 분석은 여러 공정런에 걸칩니다. `bath_analyses`에 1번 등록하고 [적용할 공정런 선택] 화면에서 고릅니다(기본 제안: 같은 포트, 시료 채취 시각 ±1일). 적용하면 각 공정런에 세션 수준 `pot.Al`, `pot.Mg`, `pot.Si` 등의 실측 행이 분석 ID 참조와 함께 생깁니다.
- **③ 시험 결과 연동:** 템플릿 필드에 `"maps_to": "out.cw_top"`을 지정하면, 결과가 저장될 때 해당 시편의 실측 행이 자동으로 생기거나 갱신됩니다. 부착량을 시험 결과와 실측 탭에 두 번 넣지 않습니다. `[D-33]`
- 같은 키에 여러 경로의 값이 있으면 모두 보관하고, 대표값은 가장 최근 행의 출처 순위(`test` > `lab` > `manual` > `pv`)로 고릅니다. 순위는 설정값입니다.

### 6.9 의도된 목표 변화: 시리즈 실험

한 세션에서 나이프 압력만 바꿔 부착량 시리즈를 만드는 경우처럼, **원판마다 목표가 다른 것**은 실측 편차와 구분해야 합니다.

- [시리즈 설정…]에서 키(예: `ak.P`)와 원판별 값 목록(20, 30, 40, 50, 60)을 넣습니다. 키는 둘까지 조합할 수 있습니다.
- 각 원판의 `target_overrides`에 `{"ak.P": 40}`처럼 바뀐 키만 저장합니다. 원판의 목표 = 기본 레시피 + `target_overrides`.
- 목표 부착량(`out.cw`)도 원판별로 줄 수 있으므로, 조건부는 원판마다 만듭니다(3.2절).
- 화면에서 "목표 변경(의도)"은 파란색 ◆, "목표 대비 편차(결과)"는 주황색 ●으로 구분합니다.

---

## 7. 데이터 파이프라인

### P1. 공정런 → 원판 생성
6장 참조. 결과: 공정런 1건, 원판 N매(원판별 목표), 각인 CSV.

### P1b. 실측 기록
```
[실측] 탭 입력 / 욕 분석 적용 / 시험 결과 저장 / (3단계) PV 수신
  → param_actuals 행 추가 → actuals.py가 해당 시편·자손의 effective_params 재계산
  → 실측 기준 조건부 재계산(표시용) → audit_log
```

### P2. 분기 (P→C, C→S)

```
시편 상세 [분기] → 단계(C/S) · 개수 · 시작 번호 · 크기/위치(선택) 입력 → 저장
```
- 자식은 부모의 과제·공정런·원소재를 상속합니다. 연구원은 다른 값(채취 위치, RD/TD, 평가면)만 고칩니다.
- 부모 상태 자동 변경: 모두 잘려 나갔으면 `CONSUMED`로 바꿀지 저장 시 한 번 묻습니다.

### P3. 시험런 생성·탑승
```
[+시험런] → 템플릿 선택(CCT_STD 등) → 설비·운전조건(템플릿 기본값 채움) → 시편 스캔 또는 목록 선택 → 슬롯 입력(선택) → 저장
```
- 시험런 번호 `TR-{시험종류}-{YY}{순번3}` 자동 발번(예: `TR-CCT-26001`). `[D-21]`
- 탑승 시 시편 상태 `IN_TEST`, 회수(`unloaded_at`) 시 `AVAILABLE`.

### P4. 결과 입력
- **그리드 셀 입력**: 셀 클릭 → 템플릿 필드로 만든 작은 폼(숫자·선택·체크) → 저장.
- **엑셀 붙여넣기**: 그리드 상단 [붙여넣기] 칸에 엑셀에서 복사한 표(시편 × 값)를 붙이면 미리보기 후 일괄 저장.
- 템플릿에 없는 키는 저장하지 않고 경고합니다(키 난립 방지). 새 항목이 필요하면 템플릿에 필드를 추가합니다.

### P5. 파일 수집·자동 매칭

**파일명 규칙(권장):**
```
{약식번호}_{태그}_{자유}.{확장자}
26P4-C0102_W03_front.jpg        → C0102 시편, 회차 3
26P4-S0102_SEM_x5000_bse.tif    → S0102 시편, SEM
```

```python
# app/services/file_ingest.py (핵심 정규식)
SHORT_ID = re.compile(r"(?P<proj>\d{2}[A-Z][0-9A-Z])-(?P<stage>[PCS])(?P<serial>\d{4})")
CYCLE    = re.compile(r"_(?:W|C)(?P<n>\d{1,3})(?=[_.])")
```

처리 순서:
1. 업로드(드래그&드롭, 다중 파일·폴더) → 임시 저장.
2. 파일명에서 약식번호 추출 → 시편 조회. 회차 태그가 있고 시험런 화면에서 올렸으면 해당 결과 셀에 연결.
3. SHA-256 해시로 중복 업로드 검사(같은 파일은 다시 저장하지 않음).
4. `/data/lims/files/{yyyy}/{short_id}/{hash12}_{원본명}`에 저장, 썸네일(400/1600 px WebP) 생성.
5. 매칭 실패 파일 → **미분류함**(올린 사람의 홈 화면에만 표시). 미분류함에서 시편을 골라 끌어 놓으면 연결.

**2단계 확장:** 장비 PC 폴더 감시. 장비 PC(Windows)와 서버 컨테이너 사이의 공유 경로가 확보되면 `workers/watcher.py`가 주기적으로 새 파일을 가져와 같은 파이프라인에 넣습니다(11장 확인 필요).

### P6. 조회·계보

```sql
-- 시편 한 개의 조상과 자손 전체 (재귀 CTE)
WITH RECURSIVE up AS (
  SELECT id, parent_id, short_id, 0 AS depth FROM specimens WHERE short_id = :sid
  UNION ALL
  SELECT s.id, s.parent_id, s.short_id, up.depth - 1
  FROM specimens s JOIN up ON s.id = up.parent_id
), down AS (
  SELECT id, parent_id, short_id, 0 AS depth FROM specimens WHERE short_id = :sid
  UNION ALL
  SELECT s.id, s.parent_id, s.short_id, down.depth + 1
  FROM specimens s JOIN down ON s.parent_id = down.id
)
SELECT * FROM up UNION SELECT * FROM down ORDER BY depth;
```

조건 검색은 `process_runs.recipe` JSONB를 직접 질의합니다(예: 욕온 450~470 °C, 이슬점 −40 °C 이하). 자주 쓰는 키(`pot.T`, `rth.DP`, `rth.T`)는 표현식 인덱스를 둡니다.

### P7. 내보내기
- 1단계: 검색 결과·시험런 그리드를 Excel로(조건 + 회차별 수치 + 사진 링크).
- 3단계: PPT 자동 생성(회사 표준 A4 가로 템플릿).

### P8. 백업
```bash
# scripts/backup.sh — cron 매일 02:00
pg_dump -Fc lims > /data/backup/db/lims_$(date +%F).dump
rsync -a --delete /data/lims/files/ <백업 위치>/files/
find /data/backup/db -mtime +30 -delete
```
DB 덤프는 컨테이너 안에 30일 보관하고, 원본 파일과 덤프는 컨테이너 밖 백업 위치로 복제해야 합니다(위치는 11장).

---

## 8. 데이터베이스 DDL (PostgreSQL 15+)

```sql
-- ── 기준 정보 ───────────────────────────────────────────
CREATE TABLE teams (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    emp_no     VARCHAR(20) NOT NULL UNIQUE,          -- 사번 (로그인 ID)
    name       VARCHAR(50) NOT NULL,
    team_id    INT REFERENCES teams(id),
    role       VARCHAR(10) NOT NULL DEFAULT 'USER',  -- USER / ADMIN
    pw_hash    TEXT NOT NULL,
    is_active  BOOLEAN DEFAULT TRUE
);

CREATE TABLE projects (
    project_code        VARCHAR(4) PRIMARY KEY,       -- '26P4', '26X0'
    company_project_no  VARCHAR(20),                  -- '2026P1234' (공통코드는 NULL)
    project_name        VARCHAR(150) NOT NULL,
    manager_id          INT REFERENCES users(id),
    is_common           BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE master_codes (
    category     VARCHAR(20) NOT NULL,   -- 'COATING_SYS', 'BATH', 'ANNEALING'
    code         VARCHAR(4)  NOT NULL,   -- 'M', 'M2', 'K'
    name         VARCHAR(100) NOT NULL,
    spec         JSONB,                  -- 매칭 기준 {"Al":[...], "tol":...} / {"T":800,"DP":-30,"t":60}
    description  TEXT,
    is_active    BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (category, code)
);

CREATE TABLE process_presets (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(60) NOT NULL,
    scope           VARCHAR(10) NOT NULL,        -- PUBLIC / TEAM / PERSONAL
    owner_id        INT REFERENCES users(id),
    team_id         INT REFERENCES teams(id),
    coating_system  CHAR(1) NOT NULL,
    bath_code       CHAR(1) NOT NULL,
    overrides       JSONB NOT NULL,              -- 사전 기본값과 다른 값만
    dict_version    VARCHAR(20) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT now()
);

CREATE TABLE test_templates (
    id                     SERIAL PRIMARY KEY,
    code                   VARCHAR(30) NOT NULL,   -- 'CCT_STD', 'BEND_0T'
    version                INT NOT NULL,
    name                   VARCHAR(80) NOT NULL,
    test_type              VARCHAR(20) NOT NULL,   -- 'CCT','SST','SEM','ECHEM','BEND',...
    field_schema           JSONB NOT NULL,         -- [{"key":"red_rust_pct","label":"적청률","unit":"%","type":"number","min":0,"max":100}, ...]
    condition_schema       JSONB,                  -- 시험런 운전조건 필드
    default_cycles         INT,                    -- 그리드 기본 열 수 (예: 9 = W00~W08)
    default_interval_days  INT,                    -- 열 머리글 표시용 (강제 아님)
    team_id                INT REFERENCES teams(id),
    is_active              BOOLEAN DEFAULT TRUE,
    UNIQUE (code, version)
);

-- ── 혈통 ────────────────────────────────────────────────
CREATE TABLE materials (
    id             SERIAL PRIMARY KEY,
    coil_no        VARCHAR(50) NOT NULL UNIQUE,  -- 'POS-26-8891'
    steel_grade    VARCHAR(50),
    thickness_mm   NUMERIC(4,2),
    composition    JSONB,                        -- 소지 성분(선택)
    received_date  DATE,
    note           TEXT
);

CREATE TABLE process_runs (
    id                     BIGSERIAL PRIMARY KEY,
    run_no                 VARCHAR(20) NOT NULL UNIQUE,   -- 'PR-26-0137'
    run_date               DATE NOT NULL,
    operator_id            INT REFERENCES users(id),
    project_code           VARCHAR(4) REFERENCES projects(project_code),
    material_id            INT REFERENCES materials(id),
    preset_id              INT REFERENCES process_presets(id),
    source                 VARCHAR(10) NOT NULL DEFAULT 'manual',  -- manual / hmi
    dict_version           VARCHAR(20) NOT NULL,
    recipe                 JSONB NOT NULL,                -- 기본 목표 레시피 스냅샷 (out.cw 포함)
    changed_from_preset    JSONB,
    coating_weight_target  NUMERIC(5,1),                  -- 단면 g/m²
    base_condition_code    VARCHAR(5) NOT NULL,           -- 기본 레시피 기준 'M206K' (원판별 코드는 specimens)
    pv_log_path            TEXT,                          -- 3단계
    note                   TEXT,
    created_at             TIMESTAMP DEFAULT now()
);

CREATE TABLE specimens (
    id                       BIGSERIAL PRIMARY KEY,
    project_code             VARCHAR(4) NOT NULL REFERENCES projects(project_code),
    stage                    CHAR(1) NOT NULL CHECK (stage IN ('P','C','S')),
    serial_no                CHAR(4) NOT NULL CHECK (serial_no ~ '^[0-9]{4}$'),
    short_id                 VARCHAR(10) GENERATED ALWAYS AS
                               (project_code || '-' || stage || serial_no) STORED,
    engraved_label           VARCHAR(16),                 -- 각인 당시 정식번호
    parent_id                BIGINT REFERENCES specimens(id) ON DELETE RESTRICT,
    process_run_id           BIGINT REFERENCES process_runs(id) ON DELETE RESTRICT,
    material_id              INT REFERENCES materials(id),
    owner_id                 INT REFERENCES users(id),
    target_overrides         JSONB,                       -- 원판별 목표 변경 {"ak.P":40} (시리즈)
    condition_code           VARCHAR(5),                  -- 목표 기준 조건부 (P에서 생성, C/S는 상속)
    sample_position          VARCHAR(10),                 -- 'DS','C','WS'
    rolling_direction        VARCHAR(5),                  -- 'RD','TD'
    surface_side             VARCHAR(10),                 -- 'TOP','BOTTOM'
    size_text                VARCHAR(30),                 -- '70x150'
    status                   VARCHAR(12) DEFAULT 'AVAILABLE', -- AVAILABLE/IN_TEST/CONSUMED/SCRAP
    storage_location         VARCHAR(100),
    is_deleted               BOOLEAN DEFAULT FALSE,
    created_at               TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_short UNIQUE (project_code, stage, serial_no)
);
-- 화면 표시용 정식번호 = specimens.condition_code || '-' || short_id (뷰에서 조합)

-- ── 실측 ────────────────────────────────────────────────
CREATE TABLE bath_analyses (
    id            SERIAL PRIMARY KEY,
    pot           VARCHAR(20) NOT NULL,       -- 'POT-1'
    sampled_at    TIMESTAMP NOT NULL,
    method        VARCHAR(20),                -- 'ICP', '습식'
    composition   JSONB NOT NULL,             -- {"Zn":25.1,"Si":2.9,"Mg":0.46,"Fe":0.4,"Al":"bal."}
    user_id       INT REFERENCES users(id),
    note          TEXT
);

CREATE TABLE param_actuals (
    id                BIGSERIAL PRIMARY KEY,
    process_run_id    BIGINT NOT NULL REFERENCES process_runs(id) ON DELETE RESTRICT,
    specimen_id       BIGINT REFERENCES specimens(id) ON DELETE RESTRICT,  -- NULL = 세션 공통
    param_key         VARCHAR(40) NOT NULL,     -- 'pot.T', 'rth.DP', 'out.cw_top'
    value             NUMERIC,                  -- 대표 수치
    value_text        VARCHAR(50),              -- 선택형 값 (가스 종류 등)
    stats             JSONB,                    -- {"points":[53.2,54.8,54.1],"min":53.2,"max":54.8,"n":3}
    source            VARCHAR(10) NOT NULL,     -- manual / lab / test / pv
    method            VARCHAR(30),              -- '열전대', '중량법', 'XRF', 'ICP'
    ref_result_id     BIGINT,                   -- FK는 test_results 생성 뒤 ALTER로 추가
    ref_analysis_id   INT REFERENCES bath_analyses(id),
    measured_at       TIMESTAMP,
    user_id           INT REFERENCES users(id),
    note              TEXT,
    is_deleted        BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMP DEFAULT now()
);

CREATE TABLE effective_params (               -- 대표값 캐시 (actuals.py가 갱신)
    specimen_id     BIGINT NOT NULL REFERENCES specimens(id),
    param_key       VARCHAR(40) NOT NULL,
    target          NUMERIC,
    actual          NUMERIC,                  -- 대표 실측 (없으면 NULL)
    effective       NUMERIC NOT NULL,         -- COALESCE(actual, target)
    source          VARCHAR(10) NOT NULL,     -- target / manual / lab / test / pv
    level           VARCHAR(6) NOT NULL,      -- target / run / P / C / S
    inherited_from  VARCHAR(10),              -- 상속한 부모 약식번호
    deviation       NUMERIC,                  -- actual − target
    out_of_tol      BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (specimen_id, param_key)
);

CREATE TABLE specimen_events (
    id           BIGSERIAL PRIMARY KEY,
    specimen_id  BIGINT NOT NULL REFERENCES specimens(id),
    event_type   VARCHAR(20) NOT NULL,     -- 'POST_TREAT','PAINT','HEAT','MOVE','SCRAP','NOTE'
    params       JSONB,                    -- {"type":"Cr-free","product":"...","dry_T":150}
    event_date   DATE NOT NULL,
    user_id      INT REFERENCES users(id),
    created_at   TIMESTAMP DEFAULT now()
);

-- ── 활동 ────────────────────────────────────────────────
CREATE TABLE test_runs (
    id                BIGSERIAL PRIMARY KEY,
    test_run_no       VARCHAR(20) NOT NULL UNIQUE,   -- 'TR-CCT-26001'
    test_type         VARCHAR(20) NOT NULL,
    template_id       INT NOT NULL REFERENCES test_templates(id),
    equipment         VARCHAR(50),                   -- 'CCT-01'
    conditions        JSONB,                         -- {"salt_conc":5,"temp_dry":60,...}
    start_date        DATE NOT NULL,
    end_date          DATE,
    owner_id          INT REFERENCES users(id),
    status            VARCHAR(10) DEFAULT 'RUNNING', -- RUNNING / DONE
    note              TEXT
);

CREATE TABLE run_specimens (
    test_run_id   BIGINT REFERENCES test_runs(id) ON DELETE RESTRICT,
    specimen_id   BIGINT REFERENCES specimens(id) ON DELETE RESTRICT,
    slot          VARCHAR(20),
    loaded_at     DATE,
    unloaded_at   DATE,
    PRIMARY KEY (test_run_id, specimen_id)
);

CREATE TABLE test_results (
    id             BIGSERIAL PRIMARY KEY,
    test_run_id    BIGINT NOT NULL REFERENCES test_runs(id) ON DELETE RESTRICT,
    specimen_id    BIGINT NOT NULL REFERENCES specimens(id) ON DELETE RESTRICT,
    cycle_no       INT NOT NULL DEFAULT 0,          -- W00=0, W01=1 ...
    eval_date      DATE,
    inspector_id   INT REFERENCES users(id),
    template_id    INT NOT NULL REFERENCES test_templates(id),  -- 버전 고정
    metrics        JSONB,
    is_deleted     BOOLEAN DEFAULT FALSE,
    created_at     TIMESTAMP DEFAULT now(),
    updated_at     TIMESTAMP DEFAULT now(),
    UNIQUE (test_run_id, specimen_id, cycle_no)
);

-- ── 공통 ────────────────────────────────────────────────
CREATE TABLE attachments (
    id             BIGSERIAL PRIMARY KEY,
    specimen_id    BIGINT REFERENCES specimens(id),        -- NULL = 미분류
    result_id      BIGINT REFERENCES test_results(id),
    process_run_id BIGINT REFERENCES process_runs(id),
    kind           VARCHAR(10),                            -- PHOTO / SEM / RAW / DOC
    path           TEXT NOT NULL,
    thumb_path     TEXT,
    original_name  TEXT NOT NULL,
    sha256         CHAR(64) NOT NULL UNIQUE,
    size_bytes     BIGINT,
    source         VARCHAR(10) DEFAULT 'upload',           -- upload / watcher / hmi
    uploaded_by    INT REFERENCES users(id),
    uploaded_at    TIMESTAMP DEFAULT now(),
    is_deleted     BOOLEAN DEFAULT FALSE
);

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    table_name  VARCHAR(40) NOT NULL,
    row_id      BIGINT NOT NULL,
    action      VARCHAR(10) NOT NULL,   -- INSERT / UPDATE / DELETE(논리)
    before      JSONB,
    after       JSONB,
    user_id     INT REFERENCES users(id),
    at          TIMESTAMP DEFAULT now()
);

ALTER TABLE param_actuals ADD CONSTRAINT fk_act_result
    FOREIGN KEY (ref_result_id) REFERENCES test_results(id);

-- ── 인덱스 ──────────────────────────────────────────────
CREATE INDEX idx_spec_parent   ON specimens(parent_id);
CREATE INDEX idx_spec_run      ON specimens(process_run_id);
CREATE INDEX idx_spec_owner    ON specimens(owner_id);
CREATE INDEX idx_res_spec      ON test_results(specimen_id);
CREATE INDEX idx_res_metrics   ON test_results USING gin (metrics);
CREATE INDEX idx_pr_recipe     ON process_runs USING gin (recipe);
CREATE INDEX idx_act_spec_key  ON param_actuals (specimen_id, param_key) WHERE NOT is_deleted;
CREATE INDEX idx_act_run_key   ON param_actuals (process_run_id, param_key) WHERE NOT is_deleted;
CREATE INDEX idx_eff_key_val   ON effective_params (param_key, effective);
CREATE INDEX idx_eff_key_tgt   ON effective_params (param_key, target);
CREATE INDEX idx_att_unmatched ON attachments(uploaded_by) WHERE specimen_id IS NULL;
```

**운영 규칙**
- 물리 삭제는 하지 않습니다. 삭제 버튼은 `is_deleted = TRUE`로 바꾸고, 외래키는 모두 `RESTRICT`입니다. `[D-20]`
- `audit_log`는 SQLAlchemy `after_flush` 이벤트에서 자동 기록합니다.
- 권한: 누구나 조회, 수정은 작성자·시편 소유자·ADMIN. 다른 사람 시편에 결과 추가는 허용(공동 실험).

---

## 9. 시험 템플릿

### 9.1 템플릿 정의 예 (`data/seed/test_templates/cct_std.json`)

```json
{
  "code": "CCT_STD", "version": 1, "name": "복합부식시험 표준", "test_type": "CCT",
  "default_cycles": 9, "default_interval_days": 7,
  "condition_schema": [
    {"key": "salt_conc", "label": "염수 농도", "unit": "%", "type": "number", "default": 5},
    {"key": "temp_dry", "label": "건조 온도", "unit": "°C", "type": "number", "default": 60},
    {"key": "temp_wet", "label": "습윤 온도", "unit": "°C", "type": "number", "default": 50}
  ],
  "field_schema": [
    {"key": "red_rust_pct",   "label": "적청률", "unit": "%",  "type": "number", "min": 0, "max": 100, "grid": true},
    {"key": "white_rust_pct", "label": "백청률", "unit": "%",  "type": "number", "min": 0, "max": 100},
    {"key": "blister_width_mm","label": "블리스터 폭", "unit": "mm", "type": "number", "min": 0},
    {"key": "note",           "label": "비고",   "type": "text"}
  ]
}
```

- `"grid": true`인 필드가 시험런 그리드 셀에 표시됩니다.
- 모든 필드는 선택 입력입니다. 필수 항목은 두지 않습니다.
- 템플릿을 고치면 새 버전이 생기고, 기존 결과는 저장 당시 버전으로 해석합니다.

### 9.2 1단계 기본 템플릿 (팀별 대표 시험)

| 팀(예) | 템플릿 | 주요 필드 |
| :--- | :--- | :--- |
| 부식 | `CCT_STD`, `SST_STD` | 적청률, 백청률, 블리스터 폭, 에지 크리프 |
| 표면·전기화학 | `ECHEM_POL`, `SEM_SECTION` | E_corr, i_corr, 배율·검출기, 관찰 부위 |
| 가공 | `BEND_0T`, `CUP_DRAW` | 크랙 유무, 박리 등급 |
| 도금 품질 | `CW_MEASURE`, `GDS_PROFILE` | 부착량 윗면·아랫면(`maps_to: out.cw_top/out.cw_bottom`), 방법, 측정점, Fe·Al·Mg 프로파일 파일 |

실제 팀 구성과 시험 목록은 0단계에서 팀별로 2~3개씩 받아 확정합니다. 1단계에서는 템플릿을 JSON 시드로 관리하고, 화면 편집기는 2단계에 만듭니다. `[D-24]`

---

## 10. API 명세 (주요)

| 메서드 | 경로 | 설명 |
| :--- | :--- | :--- |
| GET | `/api/param-dictionary` | HMI 파라미터 사전(버전 포함) |
| GET/POST | `/api/presets` | 프리셋 목록(내가 볼 수 있는 범위) / 저장 |
| POST | `/api/process-runs` | 공정런 저장 + 원판 일괄 생성 (6.3절) |
| GET | `/api/process-runs/{run_no}` | 공정런 상세(레시피, 원판, 목표·실측 표) |
| POST | `/api/process-runs/{run_no}/actuals` | 실측값 추가(여러 행, 세션·원판 수준) |
| POST | `/api/process-runs/{run_no}/actuals/paste` | 실측 탭 엑셀 붙여넣기 |
| POST | `/api/bath-analyses` | 욕 분석 등록 |
| POST | `/api/bath-analyses/{id}/apply` | 분석값을 선택한 공정런들에 실측으로 적용 |
| GET | `/api/specimens/{short_id}/params` | 키별 목표·실측·대표값·출처·편차 |
| GET | `/api/numbering/next?project=26P4&stage=C&count=8` | 다음 빈 번호 제안 + 충돌 검사 |
| POST | `/api/specimens/{short_id}/split` | 분기(자식 일괄 생성) |
| GET | `/api/specimens/{short_id}` | 시편 상세 + 계보 + 시험 이력 |
| POST | `/api/specimens/{short_id}/events` | 공정 이벤트 추가 |
| POST | `/api/test-runs` | 시험런 생성 + 탑승 |
| PUT | `/api/test-runs/{no}/results/{short_id}/{cycle}` | 결과 셀 저장(업서트) |
| POST | `/api/test-runs/{no}/paste` | 엑셀 붙여넣기 일괄 저장 |
| POST | `/api/files` | 다중 업로드 → 자동 매칭 결과(매칭/미분류) 반환 |
| PATCH | `/api/files/{id}` | 미분류 파일을 시편·결과에 연결 |
| GET | `/api/search?basis=effective\|target\|actual` | 조건·과제·시험·수치 필터 검색 (기준 선택) |
| GET | `/api/export/xlsx` | 검색 결과·시험런 Excel |
| GET | `/api/labels/engrave.csv`, `/api/labels/print.pdf` | 각인 CSV, 라벨 |

화면(HTML) 경로는 같은 리소스 이름을 쓰고 HTMX 요청이면 HTML 조각을, 그 외에는 전체 페이지를 반환합니다.

---

## 11. 구현 로드맵과 확인 필요 사항

### 11.1 단계별 구현

| 단계 | 기간(예상) | 만드는 것 | 완료 기준 |
| :--- | :--- | :--- | :--- |
| 0. 준비 | 2주 | 컨테이너에 PostgreSQL·FastAPI 기동, 외부 접속 포트 확보, 코드표(부록) 확정, HMI에서 `param_dictionary.json`·`hmi-core.js` 분리, 팀별 템플릿 수집 | 브라우저에서 LIMS 첫 화면 접속, HMI가 분리된 사전으로 동일하게 동작 |
| 1. MVP | 6~8주 | 로그인, 과제·코드, 공정런 등록(HMI 기록 모드·프리셋·복제·시리즈), 실측 탭·욕 분석 적용·시험 결과 연동, 시편 생성·분기·각인 CSV·라벨, 시험런·탑승, 결과 그리드·엑셀 붙여넣기, 파일 업로드 자동 매칭·미분류함, 시편 상세·계보, 검색, Excel 내보내기, 백업 | 11.2 기준 시나리오를 실제 시편으로 처음부터 끝까지 재현 |
| 2. 확장 | 2~3개월 | 템플릿 편집 화면, 태블릿 화면, 장비 폴더 감시, 다중 시편 비교, 과거 엑셀 데이터 일괄 가져오기 | 4~5개 팀 모두 자기 시험을 템플릿으로 등록 |
| 3. 고도화 | 이후 | HMI 실행기록(PV 실측) 자동 수신, 목표–실측 산점도, 좌우 동기화 사진 뷰어, PPT 자동 생성(A4 가로 사내 템플릿), X-cut 블리스터 측정 앱 결과 연동 | - |

### 11.2 기준 시나리오 (1단계 완료 검증용)

- 원소재 `POS-26-8891`(SPCC 0.8T), 과제 `2026P1234` → `26P4`
- 프리셋 `M2`로 공정런 등록, 목표 60 g/m², 원판 5매 → `M206K-26P4-P0101`~`P0105`

| 순서 | 실물 | LIMS 동작 |
| :--- | :--- | :--- |
| 1 | 원판 5매 출구 | 공정런 화면: 프리셋 `M2` 클릭 → 이슬점만 수정 → 원판 5매, 시작 `P0101` → 저장 → 각인 CSV |
| 1b | 욕온·이슬점·최고판온 측정 | [실측] 탭: 세션 욕온 458.5, 이슬점 −36 / 원판별 최고판온 입력 |
| 1c | `P0102` 부착량 측정 | `CW_MEASURE` 결과 윗면 54, 아랫면 58 → 실측 탭에 자동 반영, `P0102` 상세에 `각인 M206K · 실측 기준 M205K` |
| 2 | `P0101` 20×20 mm 절단·마운팅 | 시편 상세(스캔) → [분기] S 1개 `S0101` → 라벨 출력 → 시험런 `TR-SEM-26001` 탑승 |
| 3 | SEM 촬영 | 파일 `26P4-S0101_SEM_init.tif` 업로드 → 자동 연결 |
| 4 | `P0102`, `P0103`에서 쿠폰 절단 | 각 원판 [분기] → `C0102`, `C0103` (조건·과제·원소재 상속, 부착량 실측은 `실측·P0102` 배지로 상속) → 각인 CSV |
| 5 | CCT 8주 | `TR-CCT-26001` 생성(템플릿 `CCT_STD`) → 쿠폰 스캔 탑승 → 매주 사진 폴더 드래그(`_W01`…) → 그리드에서 적청률 입력 |
| 6 | `C0102` 부식 단면 채취 | [분기] `S0102` → `TR-SEM-26002` → 단면 사진 업로드 |
| 7 | 확인 | `S0102` 상세에서 계보 `POS-26-8891 → PR-26-0137 → P0102 → C0102 → S0102`, 목표·실측 조건, CCT 8주 사진이 한 화면에 보임. 검색에서 "부착량 50~55 g/m²(대표값)"로 찾으면 `C0102`가 나옴 |

### 11.3 확인 필요 사항

| 항목 | 확인할 내용 |
| :--- | :--- |
| 서버 포트 | 웹 VS Code(10553) 외에 LIMS용 포트를 외부에 열 수 있는지 (IT) |
| PostgreSQL | 컨테이너 안 설치·상시 구동 가능 여부 (Kadi4Mat 시험 설치 환경 재사용 가능성) |
| 백업 위치 | 컨테이너 밖 사내 NAS·백업 서버 경로 |
| 저장 용량 | 사진 1장 약 4 MB 가정 시 1만 장당 40 GB(썸네일 별도 약 5%). 연간 사진 수를 팀별로 추정해 500 GB 내 운영 기간 산정 |
| 장비 파일 경로 | SEM·XRD·GDS PC와 서버 간 공유 폴더 가능 여부(2단계 폴더 감시 전제) |
| 태블릿 카메라 스캔 | 브라우저 카메라 QR 스캔은 HTTPS가 필요. 사내 인증서 발급이 어려우면 USB·블루투스 바코드 스캐너 사용 |
| 각인·라벨 장비 | 레이저 각인기 CSV 입력 형식, 라벨프린터 모델 |
| 코드표 | 부록 A~D 값을 연구실 실제 조건으로 확정(특히 M계 조성, 소둔 코드의 이슬점 기준) |
| 실측 항목 | 실제로 재는 항목과 방법(판온 열전대 부착 여부, 이슬점계 위치, 부착량 중량법·XRF, 측정점 수), 키별 허용편차 초안 |
| 욕 분석 | 욕 시료 채취 주기, 분석 방법(ICP 등), 분석 의뢰·결과 회신 형식 |

---

## 부록: 마스터 코드 약호표 (초안 — 0단계에서 확정)

### A. 도금 계열 (`COATING_SYS`)

| 코드 | 계열 | HMI 프리셋 |
| :---: | :--- | :--- |
| `M` | M계 Al-Zn-Si(-Mg) (연구실 자체 개발) | `M1`, `M2` |
| `Z` | Zn-Al-Mg계 | `ZAM` |
| `G` | GI | `GI` |
| `A` | GA | `GA` |
| `Y` | Al-Zn계 (55%Al, AZ) | `AZ` |
| `L` | Al-Si계 | `AS` |
| `E` | EG | - |
| `B` | 비도금 소지 | - |

### B. 도금욕 조성 (`BATH`, 계열 글자 + 숫자 1자)

| 코드 | 조성 (wt%) | 비고 |
| :---: | :--- | :--- |
| `M1` | Al-26Zn-3Si | 조성 확인 필요 |
| `M2` | Al-26Zn-3Si-0.5Mg | 조성 확인 필요 |
| `Z1` | Zn-6Al-3Mg | 기존 HMI `ZAM` 프리셋 |
| `Z2` | Zn-1.5Al-1.5Mg | |
| `Z3` | Zn-2.5Al-3Mg | |
| `Z4` | Zn-11Al-3Mg-0.2Si | |
| `G1` | Zn-0.20Al | GI 표준욕 |
| `G2` | Zn-0.35Al | |
| `A1` | Zn-0.13Al | GA 표준욕 |
| `A2` | Zn-0.10Al | |
| `Y1` | 55Al-Zn-1.6Si | 기존 HMI `AZ` 프리셋 |
| `L1` | Al-9Si | 기존 HMI `AS` 프리셋 |
| `?X` | 위 허용오차 밖 | 자동 부여, 실제 조성은 공정런 참조 |

각 코드는 `master_codes.spec`에 원소별 허용오차를 가집니다(초안: 주원소 ±1.0 wt%, 미량원소 ±0.05 wt%).

### C. 단면 부착량 (`round_half_up(g/m² ÷ 10)`)

| 코드 | 목표 범위 (단면 g/m²) | 예 |
| :---: | :--- | :--- |
| `03` | 25 ~ 34 | 30 |
| `05` | 45 ~ 54 | 45, 50 |
| `06` | 55 ~ 64 | 60 |
| `09` | 85 ~ 94 | 90 |
| `12` | 115 ~ 124 | 120 |
| `14` | 135 ~ 144 | 140 |

### D. 소둔 조건 (`ANNEALING`)

| 코드 | 명칭 | 기준 (허용오차 초안: 판온 ±10 °C, DP ±5 °C, 균열 ±10 s) |
| :---: | :--- | :--- |
| `K` | 표준 환원소둔 | 800 °C, 60 s, DP −30 °C, 5% H₂-N₂ |
| `L` | 고이슬점 소둔 | 800 °C, 60 s, DP −10 °C |
| `M` | 극저이슬점 소둔 | 800 °C, 60 s, DP −50 °C |
| `N` | 고온 소둔 | 850 °C, 90 s, DP −30 °C |
| `P` | 저온 회복소둔 | 720 °C, 40 s, DP −30 °C |
| `Z` | 무소둔·기소둔재 | RTH OFF 또는 판온 < 600 °C |
| `X` | 비표준 | 위 어느 것과도 일치하지 않음 |

기존 HMI 기본값(800 °C, 60 s, DP −40 °C)은 위 어느 코드와도 맞지 않아 `X`가 됩니다. 연구실 표준 이슬점을 확정한 뒤 `K` 기준 또는 HMI 기본값 중 하나를 맞춥니다.

---

## 12. 설계 결정 이력 (Decision Log)

> 같은 실수를 반복하지 않기 위해, 구조를 정하거나 바꾼 이유와 **검토했지만 채택하지 않은 안**을 함께 기록합니다. 새 결정은 표 아래에 번호를 이어 추가합니다.

### 12.1 문서 버전 이력

| 버전 | 일자 (KST) | 주요 변경 |
| :--- | :--- | :--- |
| v2.0 | - | 시편번호 체계, 시험런 분리, JSONB 템플릿, 대시보드·DDL 초안 |
| v2.1 | 2026-10-21 | 독립 검토 반영: 기본키 재설계, 공정런·탑승·템플릿·사용자·첨부·감사 테이블 추가, CGL HMI 기반 공정조건 입력과 프리셋, 누락 최소화 방식 재정의, 자체 개발·화면 기술 확정, 코드표 정정, 구현 파이프라인 추가, 문서 구조를 "본문=구조·구현 / 끝=결정 이력"으로 재편 |
| v2.2 | 2026-10-21 | 목표값–실측값 이중 기록 모델 추가(실측 테이블·욕 분석·대표값 캐시), 실측 입력 화면과 4개 입력 경로, 시리즈 실험(원판별 목표), 조건부를 원판 단위·목표 기준으로 확정, `coating_weight_measured` 컬럼 폐지 |

### 12.2 결정 목록

| # | 버전 | 결정 | 이유 | 검토 후 기각한 안 |
| :---: | :---: | :--- | :--- | :--- |
| D-01 | v2.0 | 시편번호에서 시험 정보 제외, 시험런으로 연결 | 정보를 다 넣은 번호(예: 38자)는 ① 각인 불가 ② 오타 시 검색·조인 파괴 ③ 계획 변경 시 실물 표기와 데이터 불일치 | 번호에 시험·반복 번호 포함 |
| D-02 | v2.0 | 자를 때마다 새 번호, 길이 고정(16/10자), 부모는 DB | SEM 조각은 수 mm인데 접미사를 붙이면 30자를 넘음 | 부모 번호 + 접미사(`-01-A-1`) |
| D-03 | v2.0 | 약식번호 전사 유일 | 몰드·장비 파일명에 10자만 써도 시편 특정 | 조건부 포함 16자 유일 |
| D-04 | v2.0 | 일련번호 숫자 4자, 연구원 자율 | "100번대=A실험" 같은 연구원 관리 습관 존중. 부식 시 O/0, I/1, S/5, B/8 혼동 방지, 어디서나 정렬 동일 | 시스템 강제 자동 발번, 영숫자 혼용 |
| D-05 | v2.0 | 각인(영구) / 실링 테이프(임시) 이원화 | 35~60 °C, 염수, 고습 챔버에서 스티커·잉크 표기는 박리·녹으로 판독 불가 | 종이 라벨, 유성 마킹 |
| D-06 | v2.0 | 부착량은 단면 기준 | 연구실 관행 | 양면 기준 |
| D-07 | v2.0 | 소둔 조건을 조건부에 포함 | 고장력강 도금에서 이슬점이 젖음성·억제층을 좌우하는 핵심 변수 | - |
| D-08 | v2.0 | 사내 과제번호를 4자로 압축 | 9자 과제번호를 넣으면 번호가 길어짐 | 과제번호 전체 사용 |
| D-09 | v2.0 | 공통 컬럼 + JSONB | 시험마다 테이블을 만들면 스키마 변경이 끝없이 필요 | 시험별 테이블 |
| D-10 | v2.1 | 기본키를 정식번호 → 내부키 + 약식번호로, 조건부는 표시용 라벨 | 계획 조건과 실측이 자주 다름(예: 목표 60, 실측 45). 정식번호가 기본키·외래키이면 정정이 모든 테이블 수정이 됨. 약식번호만으로 유일하므로 조건부는 식별에 기여하지 않음 | 정식번호 기본키 유지(v2.0) |
| D-11 | v2.1 | 조건부를 공정런 데이터에서 자동 생성, 비표준은 `X` | 연구원 수기 코드 입력은 오기 위험. 코드는 근사 라벨이고 원본은 recipe JSON | 연구원이 조건부 직접 입력 |
| D-12 | v2.1 | 욕 조성 코드를 계열 글자 + 숫자로 (`ZA` → `Z1`) | v2.0의 `GA`(GI 표준욕)가 제품명 GA와 같아 혼동 | 영문 2자 유지 |
| D-13 | v2.1 | 부착량 코드를 반올림 규칙으로 명시, 부록 정정 | v2.0 부록에서 45 g/m²가 `04`(공식상 4.5)로 표기된 불일치 발견 | 코드표 개별 지정 |
| D-14 | v2.1 | 코드표에 연구실 실제 성분계(M계)와 HMI 프리셋 계열(AZ, AS) 추가 | v2.0 부록은 가상값이며 Zn-Al-Mg 위주라 실제 주력 성분계가 없었음 | - |
| D-15 | v2.1 | 공정조건 입력에 CGL 모사장치 HMI 화면 재사용 + 프리셋·복제 | 연구원이 실제 설비 흐름 그대로 보며 입력하는 UI가 가장 쉬움. 파라미터 사전을 HMI와 LIMS가 공유해 이중 정의 방지 | 별도 입력 폼(욕온·에어나이프 칸 나열) |
| D-16 | v2.1 | 누락 최소화 = 입력 비용 최소화 + 본인 화면의 빈칸 표시만 | 누락 방지와 사용 편의성은 상충. 예정일 강제·알림은 연구원 자율성을 침해하고 참여도를 떨어뜨림 | (V1.0 검토보고서 제안) 평가 예정일 자동 생성, 당일 메일·메신저 알림, 지연 시 팀 리더 통보, 종료 시 사유 입력 강제, 팀별 입력률 대시보드 |
| D-17 | v2.1 | 자체 개발 (FastAPI) | Kadi4Mat를 시험 설치해 직접 써보니 도입 담당자도 복잡하다고 느낌. 관심 없는 연구원은 시도조차 하지 않을 것 | Kadi4Mat 위에 구성, Kadi4Mat 저장소 + 자체 화면 |
| D-18 | v2.1 | 화면은 Jinja2 + HTMX + Alpine.js (React·Vue 미사용) | 1인 개발·유지에 빌드 체인이 부담. 기존 HMI가 Vanilla JS라 그대로 재사용 가능. 담당자가 바뀌어도 Python만 알면 유지 | React/Vue SPA (v2.0) |
| D-19 | v2.1 | 원소재·공정런·탑승표·템플릿·사용자·첨부·감사 테이블 추가 | v2.0 DDL에는 도금 조건, 시험런-시편 관계(슬롯·투입·회수), 사용자, 수정 이력을 저장할 곳이 없어 이력이 끊김 | - |
| D-20 | v2.1 | `ON DELETE CASCADE` 폐지, 논리 삭제 | 시편·시험런 하나 삭제로 축적 결과가 함께 사라지는 위험 | CASCADE 유지 |
| D-21 | v2.1 | 시험런 번호 `TR-{종류}-{YY}{순번3}` 단일 형식, 자동 발번 | v2.0 본문에 `TR-CCT-01`, `TR-CCT-26-01`, `TR-CCT-2026-01`이 혼재 | 연구원 자유 명명 |
| D-22 | v2.1 | 공통 과제코드 `26X0`, `26X1`, `26X9` | 과제 미연계 업무(공통 실험, 탐색, 클레임)를 등록할 곳이 없으면 시스템 밖에서 관리하게 됨 | - |
| D-23 | v2.1 | 원소재 블랭크는 단계 번호 대신 `materials` 로트로 관리 | 단계 `M` 추가를 검토했으나 블랭크는 도금 전 개체라 원판(P)과 이중 관리가 됨. 코일 로트로 충분 | 단계 `M`(원소재) 추가 |
| D-24 | v2.1 | 1단계는 템플릿 JSON 시드, 편집 화면은 2단계 | "1분 만에 폼 생성" 편집기는 개발량이 큼. 초기 템플릿 수가 적어 시드로 충분 | 1단계에 노코드 편집기 포함 |
| D-25 | v2.1 | 동기화 뷰어·PPT 자동 생성은 3단계 | 데이터가 쌓여야 가치가 생기는 기능. 먼저 입력·조회를 완성 | 1단계 포함 (v2.0) |
| D-26 | v2.1 | 관리자 보고용 기능(KPI·입력률)은 현 단계 제외 | 지금은 정확하고 좋은 시스템을 만드는 것이 우선 | - |
| D-27 | v2.1 | 결과 필드는 모두 선택 입력, 템플릿 외 키는 저장 거부 | 필수 항목은 입력 부담을 키움. 반면 키 난립(`red_rust_pct`/`redrust`)은 축적 데이터 비교를 깨뜨림 | 필수 항목 지정, 자유 키 허용 |
| D-28 | v2.1 | 문서 구성: 본문은 구조·구현만, 결정 이유는 문서 끝 이력에 | 설계 배경을 구조 설명과 섞으면 구조 파악이 어려움 | 각 절에 "설계 배경" 병기 (v2.0) |
| D-29 | v2.2 | 모든 공정 파라미터를 목표(레시피)와 실측(`param_actuals`, 1측정 1행)으로 분리 기록, 같은 키로 연결 | 도금 실험은 목표와 실측이 다른 경우가 많음(예: 목표 100 g/m², 실측 87). 측정은 나중에, 여러 번, 여러 방법으로 들어오므로 레시피와 같은 곳에 둘 수 없음 | 시편에 실측 컬럼 1개(v2.1 `coating_weight_measured`: 윗면·아랫면, 방법, 반복 측정 불가), 파라미터마다 실측 컬럼 추가(스키마 계속 변경), recipe JSON 안에 실측 병기(출처·시각 구분 불가) |
| D-30 | v2.2 | 실측 수준을 세션·원판·쿠폰 3단으로 나누고 자손이 상속 | 욕 조성·분위기는 세션 공통, 판온·부착량은 원판마다 다름(모사장치는 원판을 1매씩 처리). 쿠폰은 대개 따로 재지 않으므로 원판 값을 물려받아야 함 | 모든 실측을 공정런에만 기록 |
| D-31 | v2.2 | 각인·라벨 조건부는 목표 기준, 실측 기준 조건부는 화면 표시만 | 각인은 측정 전에 하고, 시편 신원은 바뀌면 안 됨(D-10). 그래도 실제 조건을 한눈에 보려면 실측 기준 코드가 필요 | 실측 후 정식번호 변경, 실측 기준 코드만 사용 |
| D-32 | v2.2 | 시리즈 실험은 원판별 `target_overrides`, 조건부를 원판 단위로 이동 | 의도한 목표 변화(나이프 압력 시리즈)를 실측 편차와 섞으면 해석이 틀어짐. 목표 부착량이 원판마다 다를 수 있음 | 시리즈마다 공정런을 따로 등록(입력 반복), 공정런 단위 조건부(v2.1) |
| D-33 | v2.2 | 실측 입력 경로 4개(수기·욕 분석·시험 결과·PV), 시험 결과는 `maps_to`로 자동 연동 | 부착량을 시험 결과와 시편 컬럼에 두 번 넣던 v2.1 구조의 이중 입력 제거 | 실측은 수기 입력만 |
| D-34 | v2.2 | 검색·비교 기본값 = 대표값(실측 우선, 없으면 목표) + 출처 배지, 기준 토글 제공 | 목표만으로 찾으면 실제 조건을 잘못 읽고, 실측만으로 찾으면 미측정 시편이 빠짐 | 목표 기준만, 실측 기준만 |
| D-35 | v2.2 | 욕 분석은 별도 테이블에 1번 등록하고 여러 공정런에 적용 | 욕 시료 1회 분석이 여러 공정런에 걸치고, 욕 조성은 드로스·소모로 시간에 따라 변함 | 공정런마다 욕 조성 수기 입력 |
| D-36 | v2.2 | 허용편차 밖 실측은 화면 색 표시만, 알림 없음 | D-16(자율성 존중)의 연장. 편차 판단은 연구원 몫 | 편차 알림, 편차 시 저장 차단 |
