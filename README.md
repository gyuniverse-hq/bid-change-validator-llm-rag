# bid-change-validator-llm-rag

LLM, RAG, evaluation, and document intelligence workspace for the Bid Change Validator project.

## Owners

- 김재현
- 이홍규

<<<<<<< Updated upstream
## Scope
=======
- "이 조항이 확인 대상인가", "자격이 충족되는가"의 **최종 판정은 반드시 코드**가 한다. LLM에게 판정을 묻지 않는다.
- LLM은 (1) 코드가 확정한 결과를 문장으로 풀어쓰거나 (2) 산문을 정형 필드로 변환하는 역할만 한다.
- **숫자·단위 변환도 LLM에게 맡기지 않는다.** LLM은 `"5억원 이상"` 원문 문자열만 뽑고, 변환은 `normalize/`가 한다.
- **비교 기준값도 코드에 적지 않는다.** 하자보수 1년, 지체상금 상한 100분의 30 같은 표준 수치는
  `standards/values.py`가 예규 원문에서 매번 추출한다. 원문에서 못 뽑으면 낡은 상수로 판정하지 않고 "확인 불가"다.
- 모든 출력에 **원문 근거**(출처 문서 + 조항 번호 + 원문 텍스트)를 동반한다.
- 근거가 없거나 파싱에 실패하면 임의 판정하지 않고 `"확인 불가 — 담당자 확인 필요"`로 표기한다.
>>>>>>> Stashed changes

- 공고문 문서 분석 및 구조화
- RAG 검색 및 근거 회수
- 참가 자격 판정 로직
- 근거 인용 및 Evidence 구성
- Guardrail 설계
- Evaluation / 평가 기준 및 테스트

## Out of Scope

- Frontend UI / UX 구현
- Backend API 및 DB 소유권
- 나라장터 원천 데이터 수집 파이프라인 소유권

## Weekend Parallel Work

이 저장소는 메인 통합 저장소에 반영하기 전 주말 병렬 작업을 위한 LLM / RAG workspace입니다.
빠른 실험과 평가를 우선하되, Backend로 전달하는 입력·출력 형식은 메인 저장소의 공통 계약 문서를 기준으로 정리합니다.

## Branches

- `main`: 현재 LLM / RAG 기준선
- `develop`: 병렬 개발 통합 브랜치
- 작업 브랜치: `feat/SKN34-XX-summary`, `fix/SKN34-XX-summary`

## Main Repository

<<<<<<< Updated upstream
- https://github.com/gyuniverse-hq/bid-change-validator
=======
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
python main.py goldenset-eval-real                      # 실제 공고 라벨 평가 (탐지만, LLM 미사용)
python main.py goldenset-eval-real --slots              # 실제 공고 라벨 평가 + 슬롯추출(Luna)
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
│                  values.py = 판정 기준 수치를 예규 원문에서 추출 (코드에 숫자 없음)
├── collectors/    3단계 조달청 API 수집 (raw JSON 보존, 첨부 sha256 기록)
├── normalize/     4단계 수치 정규화 (LLM 미개입, 순수 코드)
├── detect/        5단계 탐지 — lexicon.py(어휘 부품) + standard_diff(경로 A) + pattern_match(경로 B)
├── eligibility/   6단계 참가자격 (api_fields=코드, slots=Luna 추출, judge=코드 판정)
├── chat/          되묻기 대화 REPL — answer_parser(Luna 정형화+코드 검증) + session
├── server/        브라우저 데모 — api.py(FastAPI) + static/index.html (실제 백엔드 연결)
├── monitor/       7단계 변경 감지 + 임베딩 조항 정렬 + 확인필요조항·참가자격 3/4-상태 재판정
│                  watchlist.py(감시 목록) · notify.py(알림 기록) · runner.py(공유 실행 흐름)
├── goldenset/     8단계 골든셋 생성(Sol) 및 평가(Luna)
│                  real_cases.py = 실제 공고 사람 라벨 평가 (data/goldenset/real/)
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
> **아래 실제 공고 평가가 이 수치의 한계를 그대로 보여줍니다.**

**실제 공고 라벨** — `python main.py goldenset-eval-real [--slots]`

합성 골든셋은 우리가 쓴 문장입니다. 규칙이 그 문장에 맞춰졌는지 알 수 없어서, **우리가 쓰지 않은
실제 나라장터 공고**를 사람이 읽고 라벨링했습니다 (`data/goldenset/real/`).
대상은 주택도시보증공사 「법무정보 통합플랫폼 기반 구축 사업」(R26BK01705963) 제안요청서입니다.

| 항목 | 합성 골든셋 | 실제 공고 |
|---|---|---|
| 확인 필요 조항 6종 — 판정 | 100% | **6/6** |
| 확인 필요 조항 — 근거 위치 | 100% | **2/3** (오귀속 1건) |
| 과업범위 포괄조항 — 재현율 | 100% | **0/5 (0%)** |
| 참가자격 슬롯 — 재현율 | 100% | **3/3 (100%)** |
| 참가자격 슬롯 — 과잉추출 | 0건 | **0건** |

읽는 법:

- **포괄조항 탐지는 실제 문서에서 하나도 못 잡습니다.** 합성 골든셋 100%는
  우리가 쓴 `"기타 발주기관이 필요하다고 인정하여 요구하는 사항"` 형식만 맞힌 것입니다.
  실제 공고의 `"본 제안요청서에 기술되지 않았어도 ... 필요하다고 판단되는 사항은 협의를 통해
  제안 범위에 포함할 수 있음"` 같은 문장은 `detect/lexicon.py`의 부품 조합에 걸리지 않습니다.
  **이 프로젝트에서 가장 큰 실제 성능 격차이며 아직 고치지 않았습니다.**
- **검수기간은 판정이 맞았지만 근거가 틀렸습니다.** 탐지기는 `"착수보고서는 계약 후 14일 이내"`를
  근거로 삼았는데, 실제 검사 조항은 `"검수는 최종보고서 접수일로부터 14일 이내에 실시한다"`입니다.
  값이 우연히 둘 다 14일이라 판정만 보면 정답으로 보입니다. 근거 위치를 따로 채점하지 않았다면
  놓쳤을 오류입니다.
- **슬롯추출은 실제 문서에서도 버텼습니다.** 이 공고는 "최근 3년간 수행실적", "부산시에 소재한 업체",
  "ISO/IEC 20000" 같은 표현이 본문에 있지만 전부 **평가 배점·가산점 기준이지 참가자격이 아닙니다.**
  Luna는 이것들을 참가자격으로 뽑지 않았습니다(과잉추출 0건).

라벨 파일은 근거 원문을 인라인으로 담아, 원본 첨부(`.gitignore` 대상)가 없는 환경에서도 검토할 수
있습니다. 원본이 없으면 평가는 **통과가 아니라 "평가 불가"** 로 보고합니다. `sha256`이 다르면
문서가 바뀐 것이므로 라벨을 다시 검토하라고 알립니다.

**Luna 슬롯추출** — `python main.py goldenset-eval-slots --repeat 3`

재현율 100% / 정밀도 100% / 근거조항 100% / 유형 100% / **과잉추출 0건** / 원문보존 위반 0건.
자격요건이 하나도 없는 문서를 케이스에 포함해 "없는 요건을 지어내지 않는지"를 반드시 함께 잽니다.

## 알려진 한계

- **탐지 1층(조항 식별)이 여전히 정규식**입니다. `similarity_matrix`는 정규식 생존자 사이에서 순위만 매기므로,
  정규식이 못 잡으면 임베딩은 기회조차 없습니다. 검색을 임베딩+Luna 슬롯추출로 옮기는 개선이 남아 있습니다.
- ~~표준값이 `detect/standard_diff.py`의 `RULES`에 직접 입력~~ → **해결됨.** 6종 전부
  `standards/values.py`가 예규 원문에서 추출합니다. 예규가 개정되면 `clauses.json`만 다시 만들면
  기준이 따라 바뀌고, 값이 달라지면 테스트가 깨져 사람이 알아차립니다
  (`tests/test_standard_values.py`). 코드에 남은 것은 "원문의 어디를 보는가"(anchor)뿐입니다.
- **포괄조항(경로 B) 탐지가 실제 공고에서 재현율 0%입니다.** 위 실제 공고 평가 참조.
  `detect/lexicon.py`의 부품 사전이 우리가 만든 표현에만 맞춰져 있습니다. 가장 시급한 과제입니다.
- **검수기간 조항 식별이 착수보고서 제출기한과 섞입니다.** `INSPECTION_RE`가 "검사/검수" 어휘만
  보고 그 문장이 *누가 무엇을 검사하는가*를 구분하지 못합니다.
- **지체상금율 수치 판정 규칙이 아직 없습니다.** 상한(100분의 30)만 판정하고 요율은 "확인 불가"로
  표기합니다. 다만 위임 대상인 **국가계약법 시행규칙 제75조 원문은 `data/standards/`에 확보·인덱싱됐습니다**
  (`clauses.json`의 `국가계약법 시행규칙 75조`). "원문 미확보"라는 이전 제약은 해소됐고 남은 것은 규칙 추가뿐입니다.
- `monitor`의 조항 정렬·재판정(확인 필요 조항 + 참가자격 요건)은 합성 데이터 시뮬레이션으로만
  검증했습니다 (실제 정정공고 미발생). `watch`도 실시간 폴링 스케줄러(작업 스케줄러 등)로는
  아직 연결하지 않았고 수동 실행만 확인했습니다.
- 변경 알림은 `data/notifications.json` 파일과 CLI 출력뿐입니다. 이메일/Slack 같은 실제
  푸시 채널이나 웹 UI 배지는 없습니다.
- LibreOffice 미설치 환경이라 OLE 바이너리 HWP는 pyhwp 단일 경로입니다.
- **실제 공고 라벨이 아직 1건뿐입니다.** 발주기관·사업유형이 다양해져야 수치를 신뢰할 수 있습니다.
  라벨 추가 방법은 `data/goldenset/real/R26BK01705963_v1.json`을 본떠 같은 디렉터리에 넣으면 됩니다.

## 참고

`data/standards/`의 표준 문서 3건(계약예규 2건 + 국가계약법 시행규칙 제75조)은 확장자가 `.hwp`지만
실제로는 **HWPML(XML)** 입니다. 시행규칙은 조문 단위로 받은 파일이라 제75조만 들어 있습니다.
표준 문서를 추가하거나 교체한 뒤에는 `python -m standards.indexer --force`로 인덱스를 다시 만들어야
합니다 — `clauses.json`이 캐시되기 때문입니다.
`parsers/router.py`가 매직바이트로 실제 형식을 판별하므로 확장자를 신뢰하지 않습니다.
원본 HWP, 조달청 raw JSON, 정규화 전 원문 문자열은 감사 대비용으로 모두 보존합니다.
>>>>>>> Stashed changes
