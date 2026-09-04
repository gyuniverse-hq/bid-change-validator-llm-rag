# bid-change-validator-llm-rag

LLM, RAG, evaluation, and document intelligence workspace for the Bid Change Validator project.

## Owners

- 김재현
- 이홍규

## Scope

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

- https://github.com/gyuniverse-hq/bid-change-validator
