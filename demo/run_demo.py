# -*- coding: utf-8 -*-
"""데모 실행기 — 가상 공고 × 가상 회사 프로필로 판정·되묻기 흐름을 시연한다.

목적은 탐지 성능 측정이 아니라 **유저와의 상호작용 확인**이다:
  - 프로필에 정보가 있으면 → 충족 / 미충족을 코드가 판정하는가
  - 프로필에 정보가 없으면 → 단정하지 않고 되묻기 질문을 만드는가
  - 되묻기에 답을 주면 → 판정이 실제로 갱신되는가

여기 쓰이는 공고·업체·실적은 전부 가상이다. 실제 입찰 판단에 쓰면 안 된다.
"""
import json
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
ROOT = DEMO_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chat import apply_updates, parse_answer                              # noqa: E402
from detect import chunk_rfp, detect_patterns, detect_standard_diff       # noqa: E402
from eligibility import extract_slots, judge_api_fields, judge_slots      # noqa: E402
from parsers import parse_document                                        # noqa: E402
from report import DEMO_BANNER, render_report                             # noqa: E402
from standards import build_clauses                                       # noqa: E402

RFP_PATH = DEMO_DIR / "DEMO_공고_스마트도시플랫폼.txt"
PROFILE_DIR = DEMO_DIR / "profiles"

# 조달청 API 응답을 흉내 낸 가상 공고 필드 (6-1단계 코드 판정 경로 시연용)
DEMO_ITEM = {
    "bidNtceNo": "DEMO-2026-0001",
    "bidNtceOrd": "000",
    "bidNtceNm": "[데모] 가상시 스마트도시 통합플랫폼 구축 용역",
    "ntceInsttNm": "[데모] 가상시청",
    "prtcptPsblRgnNm": "서울특별시",
    "lcnsLmtNm": "소프트웨어사업자",
    "presmptPrce": "1350000000",
}

# 담당자가 되묻기에 이렇게 답했다고 가정한 **자연어 문장**.
# 값을 직접 넣지 않고 실제 답변 해석 경로(Luna → 코드 검증·정규화)를 그대로 태운다.
# 하드코딩된 것은 "담당자가 무슨 말을 했는가"뿐이고, 해석은 전부 실제 코드가 한다.
DEMO_ANSWERS = {
    "실적요건": "네, 작년 8월에 가상E시 도시정보 플랫폼 구축 사업을 6억 1천만원에 수주해서 완료했습니다.",
    "인증요건": "ISO 27001 인증은 보유하고 있습니다.",
    "인력요건": "특급기술자는 현재 1명뿐입니다.",
    "면허요건": "소프트웨어사업자 신고는 되어 있습니다.",
    "지역요건": "본사가 서울에 있습니다.",
}
# 답변을 일부러 섞어 놓았다: 실적·인증은 충족으로 뒤집히고,
# 인력은 요건(2인 이상)에 못 미쳐 미충족으로 확정된다.
# "답하면 무조건 충족"이 아니라 답변 내용대로 코드가 판정하는지 보기 위한 구성이다.


def _load_profiles(profile_name=None):
    profiles = []
    for path in sorted(PROFILE_DIR.glob("DEMO_*.json")):
        if profile_name and profile_name not in path.stem:
            continue
        profiles.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    return profiles


def _verdict_line(r):
    mark = {"충족": "✓", "미충족": "✗"}.get(r["verdict"], "?")
    return f"  {mark} [{r['verdict']}] {(r['slot'].get('raw') or '')[:52]}"


def run_demo(profile_name=None, no_llm=False, followup=True):
    print(DEMO_BANNER)
    print()

    parsed = parse_document(RFP_PATH)
    if parsed["parse_status"] == "failed":
        print(f"데모 공고 파싱 실패: {parsed['parse_notes']}")
        return

    clauses = build_clauses()
    chunks = chunk_rfp(parsed["full_text"])
    findings = detect_standard_diff(chunks, clauses) + detect_patterns(chunks)

    # 슬롯은 문서의 성질이라 프로필과 무관하다 — 한 번만 뽑아 모든 프로필에 재사용
    slots, extra_notes = [], []
    if no_llm:
        extra_notes.append("RFP 본문 자격요건 — LLM 미사용 모드로 추출 생략")
    else:
        out = extract_slots(chunks)
        if out["status"] == "ok":
            slots = out["slots"]
            if out["notes"]:
                extra_notes.append(f"슬롯 추출 참고 — {out['notes']}")
        else:
            extra_notes.append(
                f"RFP 본문 자격요건 — 슬롯 추출 불가({out['notes']}) — 담당자 확인 필요")
        print(f"[슬롯추출] RFP 본문에서 자격요건 {len(slots)}건 추출 (Luna)\n")

    profiles = _load_profiles(profile_name)
    if not profiles:
        print(f"데모 프로필 없음 (요청: {profile_name})")
        return

    for name, profile in profiles:
        print("=" * 72)
        print(f"■ 데모 프로필: {name}  —  {profile.get('회사명')}")
        print(f"   시나리오: {profile.get('_시나리오', '')}")
        print("=" * 72)
        api_results = judge_api_fields(DEMO_ITEM, profile)
        slot_results = judge_slots(slots, profile) if slots else []
        # 배너는 실행기 상단에 이미 출력했으므로 리포트에서는 생략
        print(render_report(DEMO_ITEM["bidNtceNm"], api_results, slot_results,
                            findings, extra_notes, demo=True, demo_banner=False))
        print()

    if followup and slots and not no_llm:
        _demo_followup_loop(slots)


def _demo_followup_loop(slots):
    """되묻기 → 담당자 자연어 답변 → LLM 정형화 → 코드 재판정 루프 시연.

    `main.py chat`이 사람 입력으로 하는 일을, 미리 정한 답변 문장으로 자동 재생한다.
    답변 해석 경로는 실제 코드(chat/answer_parser.py)를 그대로 쓴다.
    """
    path = PROFILE_DIR / "DEMO_정보부족업체.json"
    profile = json.loads(path.read_text(encoding="utf-8"))

    print("=" * 72)
    print("■ 되묻기 상호작용 시연 — DEMO_정보부족업체")
    print("   (실제 대화는 `python main.py chat` — 여기서는 답변을 자동 재생합니다)")
    print("=" * 72)

    before = judge_slots(slots, profile)
    asked = [r for r in before if r.get("되묻기")]
    print(f"\n[1단계] 프로필에 정보가 없어 판정을 보류한 항목 {len(asked)}건 — "
          f"단정하지 않고 되묻는다:")
    for r in asked:
        print(f"  ? {(r['slot'].get('raw') or '')[:56]}")
        print(f"     └ 되묻기: \"{r['되묻기']}\"")

    print("\n[2단계] 담당자가 자연어로 답변 → Luna가 정형화 → 코드가 검증·정규화:")
    for r in asked:
        slot = r["slot"]
        answer = DEMO_ANSWERS.get(slot.get("유형"))
        if not answer:
            continue
        print(f"\n  요건: {(slot.get('raw') or '')[:56]}")
        print(f"  담당자 답변: \"{answer}\"")
        parsed = parse_answer(slot, r["되묻기"], answer)
        for rej in parsed["rejected"]:
            print(f"    ⚠ 폐기: {rej}")
        if not parsed["updates"]:
            print(f"    → 반영할 값 없음 (answer_type={parsed['answer_type']})")
            continue
        print(f"    → 정형화 결과: {parsed['updates']}")
        profile = apply_updates(profile, parsed["updates"])

    after = judge_slots(slots, profile)

    print("\n[3단계] 답변 반영 후 재판정 — 판정이 바뀐 항목:")
    changed = 0
    for b, a in zip(before, after):
        if b["verdict"] != a["verdict"]:
            changed += 1
            print(f"  {(a['slot'].get('raw') or '')[:56]}")
            print(f"     {b['verdict']} → {a['verdict']}  ({a['근거']})")
    if not changed:
        print("  (변화 없음)")

    still = [r for r in after if r.get("되묻기")]
    print(f"\n[4단계] 아직 남은 되묻기 {len(still)}건:")
    for r in still:
        print(f"  ? {(r['slot'].get('raw') or '')[:56]} — {r['근거']}")
    if not still:
        print("  (없음 — 모든 항목 판정 완료)")

    print("\n※ 데모 데이터 기준입니다. 실제 입찰 판단에 사용하지 마십시오.")


if __name__ == "__main__":
    run_demo()
