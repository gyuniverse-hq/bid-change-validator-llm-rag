# 나라장터 RFP 자동 검토 프로토타입

나라장터 입찰공고를 수집해 RFP를 파싱하고, 정부 계약예규 표준과 대조해 **확인 필요 조항**을 찾아내며,
회사 프로필 대비 **참가자격 충족 여부**를 판정한다. 공고가 정정되면 변경분을 감지해 판정을 갱신한다.

## 절대 원칙

> **근거는 검색이, 판정은 코드가, LLM은 서술만.**

- "이 조항이 확인 대상인가", "자격이 충족되는가"의 **최종 판정은 반드시 코드**가 한다. LLM에게 판정을 묻지 않는다.
- LLM은 (1) 코드가 확정한 결과를 문장으로 풀어쓰거나 (2) 산문을 정형 필드로 변환하는 역할만 한다.
- **숫자·단위 변환도 LLM에게 맡기지 않는다.** LLM은 `"5억원 이상"` 원문 문자열만 뽑고, 변환은 `normalize/`가 한다.
- 모든 출력에 **원문 근거**(출처 문서 + 조항 번호 + 원문 텍스트)를 동반한다.
- 근거가 없거나 파싱에 실패하면 임의 판정하지 않고 `"확인 불가 — 담당자 확인 필요"`로 표기한다.

---

## 🔎 데모 위치 — `demo/`

**시연용 가상 공고와 가상 회사 프로필은 전부 [`demo/`](demo/)에 있습니다.** 실제 데이터와 섞이지 않습니다.

```powershell
python main.py demo                          # 가상 업체 3종 × 가상 공고 + 되묻기 상호작용 루프
python main.py demo --profile-name 적격업체   # 특정 프로필만
```

| 경로 | 내용 |
|---|---|
| [`demo/DEMO_공고_스마트도시플랫폼.txt`](demo/DEMO_공고_스마트도시플랫폼.txt) | 가상 공고 (확인 필요 조항 4건 의도적 삽입) |
| [`demo/profiles/DEMO_적격업체.json`](demo/profiles/DEMO_적격업체.json) | 모든 요건 충족 시나리오 |
| [`demo/profiles/DEMO_실적부족업체.json`](demo/profiles/DEMO_실적부족업체.json) | 실적 부족 + 지역 불일치 → 미충족 |
| [`demo/profiles/DEMO_정보부족업체.json`](demo/profiles/DEMO_정보부족업체.json) | 정보 없음 → 판정 불가 + 되묻기 |
| [`demo/run_demo.py`](demo/run_demo.py) | 실행기 (가상 조달청 API 응답 포함) |
| [`demo/README.md`](demo/README.md) | 데모 상세 설명 |

데모는 **파일명 `DEMO_` 접두어**, **JSON의 `_demo: true`**, **`[데모]` 회사명 표기**, **리포트 배너** 네 겹으로 표시됩니다.
`_demo` 프로필을 쓰면 `main.py analyze`로 돌려도 배너가 자동으로 붙습니다.

---

## 환경 설정

```powershell
pip install -r requirements.txt
```

`.env`에 API 키를 둡니다 (커밋 금지 — `.gitignore`에 포함되어 있음).

```
PUBLIC_INFO_API_KEY = '...'      # 조달청 공공데이터포털 키 (URL 인코딩된 상태로 저장돼 있어도 됨)
OPENAI_API_KEY      = 'sk-...'
OPENAI_MODEL_DEFAULT= 'gpt-5.6-luna'   # 런타임 서술·슬롯추출
OPENAI_MODEL_HIGH   = 'gpt-5.6-sol'    # 골든셋 생성 전용 (런타임 호출 금지)
```

> PowerShell에서 한글 출력이 깨지면 `$env:PYTHONUTF8 = "1"` 을 먼저 실행하세요.
> PowerShell 5.1은 `&&`를 지원하지 않습니다 — `명령1; if ($?) { 명령2 }` 를 쓰세요.

## 사용법

```powershell
python main.py fetch --days 3 --keyword "시스템 구축"   # 최근 용역공고 목록
python main.py analyze --bid-no R26BK01705963           # 실제 공고 전체 분석
python main.py analyze --file demo/DEMO_공고_스마트도시플랫폼.txt --no-llm
python main.py analyze --bid-no <번호> --narrative      # Luna 요약 서술 추가
python main.py monitor --bid-no <번호>                  # 공고 1건 변경 감지 + 변경분만 재판정
python main.py watch-add --bid-no <번호> --label <이름>  # 감시 목록에 추가
python main.py watch-list                                # 감시 목록 조회
python main.py watch                                     # 감시 목록 전체 확인 + 변경분 재판정 + 알림 기록
python main.py chat --bid-no <번호> --profile <프로필>   # 되묻기 대화 (아래 참조)
python main.py demo                                     # 데모 (위 참조)
python main.py goldenset-build                          # 골든셋 생성
python main.py goldenset-eval                           # 탐지 규칙 평가 (코드 판정)
python main.py goldenset-eval-slots --repeat 3          # Luna 슬롯추출 평가
python -m pytest tests/ -q                              # 단위 테스트
```

## 브라우저 데모 (`main.py serve`)

로컬 서버로 실제 파이프라인을 브라우저에 연결한 데모입니다. 정적 화면이 아니라
`server/api.py`(FastAPI)가 `detect/`·`eligibility/judge.py`·Luna를 그대로 호출합니다.

```powershell
python main.py serve --port 8787
```

브라우저에서 `http://127.0.0.1:8787` 을 엽니다. 프로필 입력창에 값을 넣으면
그 자리에서 `/api/judge`를 호출해 실시간으로 충족/미충족/판정불가가 갱신되고,
되묻기 항목에 자연어로 답하면 `/api/answer`(실제 Luna) → `/api/apply`(코드 병합)
→ 재판정까지 이어집니다. 서버를 끄면 페이지 상단 연결 상태가 즉시 "연결 끊김"으로
바뀝니다 — 가짜로 연결된 척하지 않습니다.

**즐겨찾기(★)** — 실제 공고를 불러온 뒤 별표를 누르면 감시 목록(`data/watchlist.json`,
`watch-add`와 같은 저장소)에 추가됩니다. 즐겨찾기 칩을 눌러 그 공고를 **다시 열 때마다**
`/api/bid`가 조달청 API를 실제로 다시 호출해 최신 여부를 확인합니다 — 캐시를 그냥
보여주지 않습니다. 마지막으로 본 뒤 실제로 바뀐 조항·참가자격 요건이 있으면 화면에
주황색 배너로 바로 표시됩니다.

**공고문 요약** — 화면 맨 위에 Luna가 RFP 본문(사업개요·기간·예산·주요 과업)을 4~6문장으로
요약해 보여줍니다. 이건 판정이 아니라 순수 서술이라 절대 원칙과 충돌하지 않습니다 — 요약
내용으로 충족/미충족을 정하지 않고, 코드가 이미 계산한 확인 필요 조항·참가자격 결과와는
완전히 별개입니다. 컨텍스트(공고)당 1회만 생성해 캐싱하고, 내용이 실제로 바뀐 경우
(`refresh_status: "updated"`)에만 다시 생성합니다.


## 되묻기 대화 (`main.py chat`)

프로필에 정보가 없어 판정을 보류한 항목을 하나씩 묻고, 담당자가 **자연어로 답하면**
그 자리에서 재판정합니다. 터미널 REPL이며, 웹 UI는 아직 없습니다.

```powershell
python main.py chat --file demo/DEMO_공고_스마트도시플랫폼.txt `
                    --profile demo/profiles/DEMO_정보부족업체.json `
                    --save-profile my_profile.json
```

```
[1/3] 요건: 2.2 최근 3년 이내 공공기관 정보시스템 구축 용역 실적 5억원 이상을 보유한 업체
  Q. 최근 3년 이내 공공기관 정보시스템 구축 용역 실적이 5억 원 이상인지 확인 부탁드립니다.
  > 네, 재작년 11월에 가상F도 행정정보시스템 구축을 7억 3천만원에 완료했습니다.
  → 반영: 실적 1건 추가 (730,000,000원)
  → 재판정: 판정 불가 → 충족  (최근 36개월 최대 단건 실적 730,000,000원 ≥ 500,000,000원)
```

명령: `/skip` `/report` `/save [경로]` `/help` `/quit`

**역할 분담은 다른 곳과 동일합니다.** Luna는 답변을 정형 필드로 옮기기만 하고,
숫자·날짜 변환은 코드(`normalize/` + `chat/answer_parser.py`의 날짜 파서)가,
충족/미충족 판정은 `eligibility/judge.py`가 합니다.

**환각 차단**: 담당자가 `"네 있습니다"`처럼 수치 없이 답하면 LLM이 금액을 지어내지
못하도록, 숫자를 담은 필드는 **답변 원문에 실제로 등장하는지 코드가 대조**하고
없으면 폐기한 뒤 다시 묻습니다. `"모르겠다"`고 답하면 판정 보류를 그대로 유지합니다.

## 정정공고 감시 (`main.py watch`)

관심 공고를 감시 목록(`data/watchlist.json`)에 등록해두면, `watch`가 목록을 순회하며
차수(bidNtceOrd)·첨부 해시를 확인하고 실제로 문서가 바뀐 것만 재판정합니다.

```powershell
python main.py watch-add --bid-no R26BK01705963 --label "법무정보 플랫폼"
python main.py watch                          # 1회 실행
python main.py watch --interval-hours 5       # 5시간마다 반복 실행 (Ctrl+C로 종료)
```

`--interval-hours`는 프로세스가 켜져 있는 동안만 도는 간단한 반복 루프입니다. 재부팅 후에도
계속 돌게 하려면 `python main.py watch`(1회 실행 버전)를 Windows 작업 스케줄러 등에 등록하는
쪽이 더 견고합니다 — 이 프로젝트는 OS 스케줄러를 자동으로 건드리지 않습니다.

변경이 감지되면 두 갈래로 재비교합니다.

- **확인 필요 조항** — `monitor/align.py`(임베딩 기반 조항 정렬, 번호 매칭 아님) + `monitor/rejudge.py`
- **참가자격 요건** — 정정공고에서 "실적 5억원 이상"이 "8억원 이상"으로 바뀌는 것처럼,
  확인 필요 조항 규칙 6종엔 안 걸리지만 참가자격 판정에는 영향을 주는 변경. 이전 스냅샷에
  저장해둔 슬롯(`eligibility/slots.py`)과 새로 뽑은 슬롯을 **조항 번호가 아니라 원문 임베딩
  유사도**로 대응시켜 `신규발생`/`유지`/`변경됨`/`해소됨`으로 분류합니다.

실질적 변화가 있으면 `data/notifications.json`에 기록됩니다. 알림 배달(이메일/Slack)이나
웹 UI 배지는 아직 없습니다 — CLI 출력과 이 JSON 파일이 현재 유일한 확인 경로입니다.

## 구조

```
├── parsers/       1단계 문서 파서 (HWP·HWPX·HWPML·PDF·TXT, 확장자 아닌 매직바이트로 판별)
├── standards/     2단계 계약예규 조문 인덱싱 → data/standards/clauses.json
├── collectors/    3단계 조달청 API 수집 (raw JSON 보존, 첨부 sha256 기록)
├── normalize/     4단계 수치 정규화 (LLM 미개입, 순수 코드)
├── detect/        5단계 탐지 — lexicon.py(어휘 부품) + standard_diff(경로 A) + pattern_match(경로 B)
├── eligibility/   6단계 참가자격 (api_fields=코드, slots=Luna 추출, judge=코드 판정)
├── chat/          되묻기 대화 REPL — answer_parser(Luna 정형화+코드 검증) + session
├── server/        브라우저 데모 — api.py(FastAPI) + static/index.html (실제 백엔드 연결)
├── monitor/       7단계 변경 감지 + 임베딩 조항 정렬 + 확인필요조항·참가자격 3/4-상태 재판정
│                  watchlist.py(감시 목록) · notify.py(알림 기록) · runner.py(공유 실행 흐름)
├── goldenset/     8단계 골든셋 생성(Sol) 및 평가(Luna)
├── llm/           Sol/Luna provider 추상화 + 임베딩
├── demo/          ★ 시연용 가상 자산 (실제 데이터 아님)
└── tests/
```

## 평가

두 갈래를 따로 잽니다. 탐지는 순수 코드라 결정적이고, 슬롯추출은 LLM이 개입해 흔들리기 때문입니다.

**탐지 규칙** — `python main.py goldenset-eval`

골든셋은 결함 유형마다 표현을 **p0(규칙 작성에 참고) / p1~p3(held-out)** 으로 나눠 생성하고,
평가에서 분리 보고합니다. 두 숫자가 벌어지면 규칙이 형식이 아니라 문장을 외운 것입니다.

| | 재현율 | 정밀도 |
|---|---|---|
| 기본 표현 (p0) | 100% | 100% |
| held-out 표현 (p1~p3) | 100% | 100% |

> 처음 정규식 기반일 때 held-out 재현율은 **33.3%** 였습니다. 어휘 부품 조합(`detect/lexicon.py`)으로
> 재작성해 100%가 됐지만, 이 held-out 세트는 이제 in-distribution입니다.
> **일반화를 계속 검증하려면 새 표현을 주기적으로 추가해야 합니다.**

**Luna 슬롯추출** — `python main.py goldenset-eval-slots --repeat 3`

재현율 100% / 정밀도 100% / 근거조항 100% / 유형 100% / **과잉추출 0건** / 원문보존 위반 0건.
자격요건이 하나도 없는 문서를 케이스에 포함해 "없는 요건을 지어내지 않는지"를 반드시 함께 잽니다.

## 알려진 한계

- **탐지 1층(조항 식별)이 여전히 정규식**입니다. `similarity_matrix`는 정규식 생존자 사이에서 순위만 매기므로,
  정규식이 못 잡으면 임베딩은 기회조차 없습니다. 검색을 임베딩+Luna 슬롯추출로 옮기는 개선이 남아 있습니다.
- **표준값이 `detect/standard_diff.py`의 `RULES`에 직접 입력**돼 있습니다. `clauses.json`에 원문이 있는데도
  숫자를 중복 입력한 상태라, 예규가 개정되면 사람이 코드를 고쳐야 합니다.
- **지체상금율 수치 판정은 범위 밖**입니다. 용역계약일반조건 제55조가 시행규칙 제75조로 위임만 하고 있고
  시행규칙 원문이 미확보라, 상한(100분의 30)만 판정하고 요율은 항상 "확인 불가"로 표기합니다.
- `monitor`의 조항 정렬·재판정(확인 필요 조항 + 참가자격 요건)은 합성 데이터 시뮬레이션으로만
  검증했습니다 (실제 정정공고 미발생). `watch`도 실시간 폴링 스케줄러(작업 스케줄러 등)로는
  아직 연결하지 않았고 수동 실행만 확인했습니다.
- 변경 알림은 `data/notifications.json` 파일과 CLI 출력뿐입니다. 이메일/Slack 같은 실제
  푸시 채널이나 웹 UI 배지는 없습니다.
- LibreOffice 미설치 환경이라 OLE 바이너리 HWP는 pyhwp 단일 경로입니다.
- 골든셋·슬롯 케이스가 모두 합성 문서입니다. 실제 공고를 라벨링해 넣으면 검증 강도가 올라갑니다.

## 참고

`data/standards/`의 계약예규 2건은 확장자가 `.hwp`지만 실제로는 **HWPML(XML)** 입니다.
`parsers/router.py`가 매직바이트로 실제 형식을 판별하므로 확장자를 신뢰하지 않습니다.
원본 HWP, 조달청 raw JSON, 정규화 전 원문 문자열은 감사 대비용으로 모두 보존합니다.
