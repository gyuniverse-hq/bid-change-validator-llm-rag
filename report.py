# -*- coding: utf-8 -*-
"""결과 리포트 포맷터.

모든 항목에 원문 근거(출처 문서 + 조항 번호 + 원문 텍스트)를 동반한다.
LLM(Luna)은 코드가 확정한 판정을 문장으로 풀어쓰는 역할만 한다 (--narrative).
"""
from llm import get_client

# 지체상금율 제외 사유 — 항상 "확인 불가" 섹션에 표기 (스펙 고정)
PENALTY_RATE_EXCLUSION = (
    "지체상금율 — 판정 규칙 미구현으로 제외 "
    "(용역계약일반조건 제55조가 시행규칙 제75조로 위임하는 구조. 위임 대상인 "
    "시행규칙 제75조 원문은 data/standards/에 확보·인덱싱되어 있으므로, "
    "규칙만 추가하면 판정 가능한 상태다)"
)


def _fmt_value(v):
    if not v:
        return ""
    unit = v.get("unit")
    val = v.get("value")
    if val is None:
        return v.get("raw", "")
    if unit == "KRW":
        return f"{val:,.0f}원"
    if unit == "MONTH":
        return f"{val:g}개월"
    if unit == "PERCENT":
        return f"{val:g}%"
    return str(val)


DEMO_BANNER = (
    "╔═══════════════════════════════════════════════════════════════════╗\n"
    "║  ⚠  데모 실행 — 실제 공고도, 실제 업체도 아닙니다                 ║\n"
    "║     가상 공고와 가상 회사 프로필로 판정·되묻기 흐름을 시연합니다   ║\n"
    "║     데모 자산 위치: demo/  (파일명 접두어 DEMO_)                   ║\n"
    "╚═══════════════════════════════════════════════════════════════════╝"
)


def render_report(title, api_results=None, slot_results=None, findings=None,
                  unresolvable_extra=None, narrative=False, demo=False,
                  demo_banner=True):
    """스펙 출력 형식으로 리포트 문자열 생성.

    demo=True면 데모 데이터임을 리포트 앞뒤에 명시한다. 데모 산출물이
    실제 검토 결과로 오인되는 일이 없어야 한다.
    demo_banner=False면 상단 배너만 생략한다 (실행기가 이미 한 번 출력한 경우).
    """
    lines = []
    if demo and demo_banner:
        lines += [DEMO_BANNER, ""]
    lines += [f"[공고] {title}", ""]

    # ■ 참가자격
    lines.append("■ 참가자격")
    any_elig = False
    for r in (api_results or []):
        any_elig = True
        mark = {"충족": "✓", "미충족": "✗", "확인 불가": "?", "정보": "·"}.get(r["verdict"], "?")
        lines.append(f"  {mark} {r['항목']} — {r['verdict']}")
        lines.append(f"     └ 근거: {r['근거']}")
    for r in (slot_results or []):
        any_elig = True
        mark = {"충족": "✓", "미충족": "✗"}.get(r["verdict"], "?")
        slot = r["slot"]
        label = slot.get("근거조항")
        head = f"{slot.get('raw', '')[:60]}"
        lines.append(f"  {mark} {head} — {r['verdict']}")
        if label:
            lines.append(f"     └ 근거조항: {label}")
        if r.get("근거"):
            lines.append(f"     └ 판정근거: {r['근거']}")
        if r.get("되묻기"):
            lines.append(f"     └ 되묻기: \"{r['되묻기']}\"")
    if not any_elig:
        lines.append("  (판정 대상 정보 없음)")
    lines.append("")

    # ■ 확인 필요 조항
    flagged = [f for f in (findings or []) if f["verdict"] == "확인 필요"]
    unresolvable = [f for f in (findings or []) if f["verdict"] == "확인 불가"]
    lines.append(f"■ 확인 필요 조항 ({len(flagged)}건)")
    for i, f in enumerate(flagged, 1):
        method = "표준 대조" if f["detection_method"] == "standard_diff" else "패턴 탐지"
        label = f.get("rfp_clause_label") or "(조항 라벨 없음)"
        lines.append(f"  {i}. [{method}] {label}항 {f['risk_type']}")
        if f.get("standard"):
            std = f["standard"]
            lines.append(f"     표준: {std['clause_ref']} — {std['std_desc']}")
            if std.get("std_value_raw"):
                # 판정 기준값을 예규 원문의 어느 문자열에서 뽑았는지 — 숫자의 출처를
                # 리포트에서 바로 확인할 수 있어야 한다(코드 상수가 아님을 보이는 것)
                lines.append(f"     표준값 근거: 예규 원문 \"{std['std_value_raw']}\"")
            if std.get("std_note"):
                lines.append(f"     ⚠ {std['std_note']}")
            if std.get("text_excerpt"):
                lines.append(f"     표준 원문: \"{std['text_excerpt'][:120]}\"")
        if f.get("rfp_value"):
            lines.append(f"     RFP 값: {_fmt_value(f['rfp_value'])} (원문: \"{f['rfp_value'].get('raw', '')}\")")
        lines.append(f"     사유: {f['reason']}")
        lines.append(f"     RFP 원문: \"{f.get('rfp_excerpt', '')}\"")
    if not flagged:
        lines.append("  (없음)")
    lines.append("")

    # ■ 확인 불가
    unres_lines = []
    for f in unresolvable:
        label = f.get("rfp_clause_label") or "(조항 라벨 없음)"
        unres_lines.append(f"  - {label}항 {f['risk_type']} — {f['reason']}")
        unres_lines.append(f"    RFP 원문: \"{f.get('rfp_excerpt', '')}\"")
    unres_lines.append(f"  - {PENALTY_RATE_EXCLUSION}")
    for extra in (unresolvable_extra or []):
        unres_lines.append(f"  - {extra}")
    lines.append(f"■ 확인 불가 ({len(unresolvable) + 1 + len(unresolvable_extra or [])}건)")
    lines.extend(unres_lines)

    if demo:
        lines += ["", "※ 위 결과는 데모 데이터 기준입니다. 실제 입찰 판단에 사용하지 마십시오."]

    text = "\n".join(lines)

    if narrative:
        text = text + "\n\n" + _narrative_summary(text)
    return text


def _narrative_summary(report_text):
    """Luna가 코드 판정 결과를 요약 서술. 판정 변경 금지 — 서술만."""
    client = get_client("luna")
    if not client.available:
        return "(요약 서술 생략 — OPENAI_API_KEY 미설정)"
    try:
        out = client.chat(
            "아래는 코드가 확정한 입찰공고 분석 리포트다. 판정을 바꾸거나 새 판정을 추가하지 마라. "
            "담당자에게 구두로 브리핑하듯, 목록·불릿·번호 매기기 없이 하나의 글로 이어지는 "
            "3~5문장으로 풀어써라. 문장 끝은 '~입니다', '~합니다' 같은 정중한 구어체로 통일하고, "
            "'참가자격은 ~이며, 확인이 필요한 조항은 ~입니다' 처럼 앞뒤 문장이 자연스럽게 이어지게 "
            "하라. 모든 수치는 리포트에 있는 그대로 사용하라.",
            report_text)
        return "■ 요약 (LLM 서술 — 판정은 위 코드 결과가 기준)\n" + out.strip()
    except Exception as e:
        return f"(요약 서술 실패: {e})"
