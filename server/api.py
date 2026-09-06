# -*- coding: utf-8 -*-
"""데모 서버 API — 실제 파이프라인을 그대로 호출한다.

절대 원칙은 여기서도 그대로 지킨다: 판정은 코드(eligibility/judge.py,
detect/*)가 하고, 이 파일은 그 함수들을 HTTP로 노출만 한다. 프론트엔드는
판정 로직을 재구현하지 않는다 — 그러면 두 곳에 같은 로직이 생겨 나중에
어긋난다. 브라우저는 순수 클라이언트고, 진짜 계산은 전부 여기서 일어난다.

엔드포인트:
  GET    /                    브라우저용 정적 페이지
  GET    /api/demo             데모 RFP 파싱·탐지·슬롯추출 결과 (컨텍스트 id "demo")
  POST   /api/bid              실제 나라장터 공고번호로 전환 — 열 때마다 실제 API로 최신 여부 확인
  POST   /api/judge            프로필 + context_id -> 참가자격 판정 (코드, LLM 미개입)
  POST   /api/answer           되묻기 자연어 답변 -> 정형 갱신안 (Luna)
  POST   /api/apply            갱신안을 프로필에 병합 (코드)
  POST   /api/assist           막연한 질문 응대 (Luna, 서술만)
  GET    /api/watchlist        즐겨찾기(감시 목록) 조회
  POST   /api/watchlist        즐겨찾기 추가
  DELETE /api/watchlist/{no}   즐겨찾기 제거

여러 공고를 오갈 수 있도록 RFP 컨텍스트를 "demo" | 공고번호 키로 메모리에도
캐싱한다(_contexts) — /api/judge가 매 입력마다 디스크·API를 다시 안 뒤지게
하기 위한 것일 뿐, **진짜 최신인지 확인하는 주체는 아니다.** 그건 /api/bid가
호출될 때마다 monitor.check_and_rejudge()로 실제 조달청 API를 다시 확인한다 —
CLI(main.py watch)가 감시 목록을 확인할 때와 완전히 같은 함수를 쓴다. 즉
사용자가 즐겨찾기한 공고 화면을 다시 열면, 그 순간 진짜로 최신 여부를 재확인하고
바뀐 부분만 재판정한다. "다시 열었더니 예전 캐시를 보여주더라"가 나오면 안 된다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request                      # noqa: E402
from fastapi.middleware.cors import CORSMiddleware         # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse   # noqa: E402

from chat import apply_updates, parse_answer               # noqa: E402
from demo.run_demo import DEMO_ITEM, RFP_PATH               # noqa: E402
from detect import chunk_rfp, detect_patterns, detect_standard_diff  # noqa: E402
from eligibility import extract_slots, judge_api_fields, judge_slots  # noqa: E402
from llm import get_client                                  # noqa: E402
from parsers import parse_document                          # noqa: E402
from report import PENALTY_RATE_EXCLUSION                   # noqa: E402
from standards import build_clauses                         # noqa: E402

app = FastAPI(title="RFP 검토 프로토타입 — 로컬 데모 서버")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 로컬 데모 전용. 배포 시 이 서버를 그대로 쓰지 말 것.
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
_contexts = {}  # context_id ("demo" | 공고번호) -> ctx dict


def _build_context(parsed, title, item, context_id, source, extra=None):
    """파싱 결과에서 findings/slots까지 계산해 컨텍스트로 캐싱한다.

    데모든 실제 공고든 같은 함수를 쓴다 — 파이프라인이 소스에 따라 달라지면
    안 되기 때문이다(데모에서만 통과하고 실제 공고에서 깨지는 것을 막는다).
    """
    base = {
        "context_id": context_id,
        "source": source,   # "demo" | "real" — 프론트가 배너를 구분하는 데만 씀
        "title": title,
        "item": item,
        "penalty_rate_note": PENALTY_RATE_EXCLUSION,
        "parse_status": parsed["parse_status"],
        "parse_notes": parsed["parse_notes"],
    }
    if extra:
        base.update(extra)

    if parsed["parse_status"] == "failed":
        base.update(findings=[], slots=[], slot_status="parse_failed",
                    slot_notes=parsed["parse_notes"])
        _contexts[context_id] = base
        return base

    clauses = build_clauses()
    chunks = chunk_rfp(parsed["full_text"])
    findings = detect_standard_diff(chunks, clauses) + detect_patterns(chunks)
    slot_out = extract_slots(chunks)
    base.update(
        findings=findings,
        slots=slot_out.get("slots", []),
        slot_status=slot_out["status"],
        slot_notes=slot_out.get("notes", ""),
        rfp_summary=_get_or_build_summary(context_id, chunks, title),
    )
    _contexts[context_id] = base
    return base


_SUMMARY_SYSTEM = """너는 나라장터 입찰공고 제안요청서(RFP) 본문을 담당자에게 구두로 설명하듯 풀어 말하는 도구다. 규칙:
1. 아래 원문에 실제로 적힌 내용만 담아라. 없는 사실(금액, 기간, 요건 등)을 지어내지 마라.
2. 충족 여부나 리스크를 판단하지 마라 — 판정이 아니라 내용 설명이다.
3. 목록·불릿·번호 매기기·소제목을 쓰지 마라. 사업개요, 사업기간, 사업예산, 주요 과업내용이
   자연스럽게 이어지는 하나의 글로, 4~6문장 정도로 풀어써라.
4. 문장 끝은 "~입니다", "~합니다" 같은 정중한 구어체 종결로 통일하고, 앞 문장과
   뒤 문장이 "이 사업은 ~입니다. 기간은 ~이며, ~을 목표로 합니다." 처럼 자연스럽게
   이어지게 하라. 개조식(명사로 끝맺는 딱딱한 문체)을 쓰지 마라."""


def _summarize_rfp(chunks, title):
    """RFP 원문 요약 — 판정 아님, 순수 서술(절대 원칙: LLM은 서술만).

    확인 필요 조항·참가자격처럼 코드가 판정하는 게 아니라 "이 공고가 뭘 요구하는
    공고인지" 훑어보게 해주는 용도라, 근거 원문 대조 같은 엄격한 환각 차단은
    안 걸었다 — 다만 시스템 프롬프트로 원문에 없는 사실을 만들지 말라고 명시한다.
    """
    client = get_client("luna")
    if not client.available:
        return None
    text = "\n".join(c.get("text", "") for c in chunks)[:10000]
    if not text.strip():
        return None
    try:
        summary = client.chat(_SUMMARY_SYSTEM, f"[공고명]\n{title}\n\n[RFP 본문]\n{text}")
    except Exception as e:
        return f"(요약 생성 실패: {e})"
    return (summary or "").strip() or None


def _get_or_build_summary(context_id, chunks, title, force=False):
    """컨텍스트당 1회만 계산해 캐싱한다 — 문서 내용이 안 바뀌었으면 재호출 안 함."""
    cached = _contexts.get(context_id, {}).get("rfp_summary")
    if cached and not force:
        return cached
    return _summarize_rfp(chunks, title)


def _demo_context():
    """데모 RFP 컨텍스트. 서버 프로세스 생존 중 1회만 계산한다."""
    if "demo" in _contexts:
        return _contexts["demo"]
    parsed = parse_document(RFP_PATH)
    return _build_context(parsed, DEMO_ITEM["bidNtceNm"], DEMO_ITEM, "demo", "demo")


def _get_context(context_id):
    return _contexts.get(context_id) or _demo_context()


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/demo")
def get_demo():
    return JSONResponse(_demo_context())


@app.post("/api/bid")
async def load_bid(request: Request):
    """실제 나라장터 공고번호로 전환 — 호출될 때마다 실제 API로 최신 여부를 확인한다.

    monitor.check_and_rejudge()를 그대로 쓴다. 이 함수가 하는 일:
      1. 조달청 API를 실제로 다시 호출해 차수(bidNtceOrd)를 확인
      2. 차수가 그대로면 재파싱·재탐지·재추출 없이 마지막 저장본을 반환 (빠름·무료)
      3. 차수가 올랐으면 첨부 재다운로드 → 해시 비교 → 실제로 문서가 바뀐 경우에만
         재파싱 + 탐지(경로 A/B) + Luna 슬롯추출을 다시 실행하고 결과를 저장
    즉 "즐겨찾기 화면을 다시 열 때마다 최신 공고를 불러와 재비교"가 이 한 호출로 된다.
    """
    body = await request.json()
    bid_no = (body.get("bid_no") or "").strip()
    if not bid_no:
        return JSONResponse({"error": "공고번호를 입력해 주세요."}, status_code=400)

    from monitor import check_and_rejudge

    try:
        r = check_and_rejudge(bid_no, build_clauses())
    except Exception as e:
        return JSONResponse({"error": f"조달청 API 조회 실패: {e}"}, status_code=502)

    if r["status"] in ("no_rfp", "parse_failed"):
        return JSONResponse({"error": r["message"], "item": r["item"]}, status_code=422)

    print(f"[공고 로드] {bid_no} ({r['status']}) — {r['title']}")

    ctx = {
        "context_id": bid_no,
        "source": "real",
        "title": r["title"],
        "item": r["item"],
        "rfp_file": r["rfp_file"],
        "findings": r["findings"],
        "slots": r["slots"],
        "rfp_summary": _get_or_build_summary(bid_no, r["chunks"], r["title"],
                                             force=(r["status"] in ("initial", "updated"))),
        "slot_status": "ok",
        "slot_notes": "",
        "penalty_rate_note": PENALTY_RATE_EXCLUSION,
        "parse_status": "success",
        "parse_notes": "",
        "refresh_status": r["status"],  # no_change|meta_only|initial|updated
        "change_notice": None,  # 마지막으로 이 공고를 본 뒤 실제로 바뀐 게 있으면 채워짐
    }
    if r["status"] == "updated":
        real_findings = [s for s in r["finding_states"] if s["state"] != "유지"]
        real_slots = [s for s in r["slot_states"] if s["state"] != "유지"]
        if real_findings or real_slots:
            ctx["change_notice"] = {
                "finding_changes": [
                    {"state": s["state"], "clause_label": s["finding"].get("rfp_clause_label"),
                     "risk_type": s["finding"]["risk_type"]}
                    for s in real_findings
                ],
                "slot_changes": [
                    {"state": s["state"], "raw": (s["new"] or s["old"]).get("raw")}
                    for s in real_slots
                ],
            }
    _contexts[bid_no] = ctx
    return JSONResponse(ctx)


@app.get("/api/watchlist")
def get_watchlist():
    from monitor import list_watched
    return JSONResponse({"items": list_watched()})


@app.post("/api/watchlist")
async def post_watchlist(request: Request):
    from monitor import add_bid
    body = await request.json()
    bid_no = (body.get("bid_no") or "").strip()
    if not bid_no:
        return JSONResponse({"error": "공고번호를 입력해 주세요."}, status_code=400)
    items = add_bid(bid_no, label=body.get("label"))
    return JSONResponse({"items": items})


@app.delete("/api/watchlist/{bid_no}")
def delete_watchlist(bid_no: str):
    from monitor import remove_bid
    return JSONResponse({"items": remove_bid(bid_no)})


@app.post("/api/judge")
async def judge(request: Request):
    body = await request.json()
    profile = body.get("profile") or {}
    ctx = _get_context(body.get("context_id") or "demo")
    api_results = judge_api_fields(ctx["item"], profile)
    slot_results = judge_slots(ctx["slots"], profile) if ctx["slots"] else []
    return JSONResponse({"api_results": api_results, "slot_results": slot_results})


@app.post("/api/answer")
async def answer(request: Request):
    """되묻기 답변 해석 — 실제 Luna를 호출한다. 프로필 병합은 하지 않는다.

    병합은 /api/apply가 코드로 한다 — 여기서 갱신안만 만들고, 채택 여부는
    프론트엔드가 사용자 확인 없이 자동으로 넘길지 결정한다.
    """
    body = await request.json()
    slot = body.get("slot") or {}
    question = body.get("question", "")
    answer_text = body.get("answer", "")
    if not answer_text.strip():
        return JSONResponse({"answer_type": "empty", "updates": {}, "rejected": [],
                             "notes": "답변이 비어 있습니다"})
    result = parse_answer(slot, question, answer_text)
    return JSONResponse(result)


@app.post("/api/apply")
async def apply(request: Request):
    body = await request.json()
    profile = body.get("profile") or {}
    updates = body.get("updates") or {}
    merged = apply_updates(profile, updates)
    return JSONResponse({"profile": merged})


_ASSIST_SYSTEM = """너는 나라장터 입찰 참가자격 검토를 돕는 도우미다. 이 화면에서 진행 중인
공고 검토를 돕는 게 주 업무지만, 그와 무관한 일반적인 질문(용어 설명, 절차 안내, 잡담,
이 도구 사용법 등)을 해도 자연스럽게 답한다 — 이런 질문까지 판정 정보가 없다는 이유로
답을 피하지 마라.

아래 [현재 상태]는 담당자가 지금까지 입력한 프로필 원문과, 코드가 그걸로 이미 확정한
판정 결과다. 규칙:
1. 이번 공고·프로필에 대한 충족/미충족/판정불가는 절대 새로 내리지 마라 — 이미 코드가
   정했다. [현재 상태]에 있는 그 결과를 있는 그대로 전달·설명만 하라.
2. [현재 상태]에 없는 이번 건의 구체적 사실(정확한 금액·날짜·인증 보유 여부 등)은
   지어내지 마라. 모르면 모른다고 하거나 프로필에 입력해 달라고 안내하라.
3. 반면 일반적인 지식(예: "하자보수가 뭐야?", "지체상금은 왜 있어?" 같은 용어·개념
   설명이나 잡담)은 이번 건 데이터와 무관해도 네가 아는 대로 자유롭게 답해도 된다.
4. 담당자가 "그래서 어떻게 해야 해?"처럼 막연하게 물으면 [현재 상태]를 근거로 다음
   행동을 구체적으로 안내하라.
5. 간결하고 대화하듯 자연스럽게 답하라. 질문 성격에 맞게 길이를 조절하라."""


def _summarize_profile(profile):
    """폼에 실제로 입력된 원문 값 — 판정 결과가 아니라 담당자가 지금까지 채운 내용 그 자체.

    이걸 빼고 판정 결과(verdict/근거)만 넘기면, 담당자가 방금 뭘 입력했는지를
    도우미가 직접 참조하지 못해 막연한 질문에 구체적으로 답하지 못한다.
    """
    if not profile:
        return "(아직 입력된 항목 없음)"
    lines = []
    if profile.get("회사명"):
        lines.append(f"회사명: {profile['회사명']}")
    if profile.get("소재지역"):
        lines.append(f"소재지역: {profile['소재지역']}")
    if profile.get("보유면허"):
        lines.append(f"보유면허: {', '.join(profile['보유면허'])}")
    if profile.get("보유인증"):
        lines.append(f"보유인증: {', '.join(profile['보유인증'])}")
    if profile.get("직접생산증명"):
        lines.append(f"직접생산증명: {', '.join(profile['직접생산증명'])}")
    staff = profile.get("기술인력") or {}
    staff_parts = [f"{k} {v}인" for k, v in staff.items() if v]
    if staff_parts:
        lines.append("기술인력: " + ", ".join(staff_parts))
    perf = profile.get("실적") or []
    if perf:
        total = sum(p.get("계약금액", 0) or 0 for p in perf)
        lines.append(f"사업실적: {len(perf)}건, 합계 {total:,}원")
    return "\n".join(lines) if lines else "(아직 입력된 항목 없음)"


def _summarize_context(ctx):
    lines = ["[담당자가 입력한 프로필]", _summarize_profile(ctx.get("profile") or {}), "", "[판정 결과]"]
    for r in ctx.get("api_results", []):
        lines.append(f"- [{r.get('verdict')}] {r.get('항목')}: {r.get('근거')}")
    for r in ctx.get("slot_results", []):
        slot = r.get("slot") or {}
        line = f"- [{r.get('verdict')}] {(slot.get('raw') or '')[:60]}: {r.get('근거', '')}"
        if r.get("되묻기"):
            line += f" (되묻기 대기 중: \"{r['되묻기']}\")"
        lines.append(line)
    findings = [f for f in ctx.get("findings", []) if f.get("verdict") == "확인 필요"]
    if findings:
        lines.append("")
        lines.append("[확인 필요 조항]")
        for f in findings:
            lines.append(f"- {f.get('rfp_clause_label', '')}항 {f.get('risk_type')}: {f.get('reason')}")
    return "\n".join(lines)


@app.post("/api/assist")
async def assist(request: Request):
    """막연한 질문 응대 — 코드가 확정한 현재 상태를 문장으로 풀어쓰기만 한다.

    "그래서 어떻게 해야 해?" 같은 질문에 답하되, 이 엔드포인트가 새로운 충족/미충족을
    판정하지는 않는다 — 프론트엔드가 보낸 profile(입력 원문)과 api_results/slot_results/
    findings(전부 코드 판정 결과)를 근거로 다음 행동을 안내할 뿐이다.

    함수 전체를 try/except로 감싼다 — 여기서 처리 못 한 예외가 그대로 500으로
    올라가면 프론트엔드가 원인 없이 "(응답 없음)"만 보여주게 된다.
    """
    try:
        body = await request.json()
        question = (body.get("question") or "").strip()
        ctx = body.get("context") or {}
        if not question:
            return JSONResponse({"answer": "질문을 입력해 주세요."})

        client = get_client("luna")
        if not client.available:
            return JSONResponse({"answer": "OPENAI_API_KEY가 설정되지 않아 안내 도우미를 쓸 수 없습니다."})

        summary = _summarize_context(ctx)
        answer = client.chat(
            _ASSIST_SYSTEM,
            f"[현재 상태]\n{summary}\n\n[담당자 질문]\n{question}",
        )
        if not answer or not answer.strip():
            return JSONResponse({
                "answer": "도우미가 빈 응답을 반환했습니다(모델 응답 없음) — 다시 시도해 주세요."
            })
        return JSONResponse({"answer": answer.strip()})
    except Exception as e:
        import traceback
        traceback.print_exc()  # 로컬 데모 서버 콘솔에 원인이 남게 한다
        return JSONResponse({"answer": f"응답 생성 중 오류가 발생했습니다: {e}"})
