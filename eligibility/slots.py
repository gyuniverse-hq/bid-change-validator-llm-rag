# -*- coding: utf-8 -*-
"""6-2. RFP 본문 슬롯 추출 — Luna 호출 (런타임 전용 모델).

역할 경계:
- LLM은 산문 -> 정형 필드 변환만 한다. "5억원 이상" 같은 **원문 문자열만** 뽑는다.
- 숫자 변환은 normalize 모듈(코드)이 담당한다.
- structured output(JSON schema strict)으로 스키마 이탈을 디코딩 단계에서 차단.
- LLM이 붙인 근거조항 번호는 실제 청크의 조항 라벨과 코드로 대조 — 불일치 시 폐기 후 재추출.
"""
import re

from llm import get_client
from normalize import normalize_value

# 자격요건 관련 청크 선별 키워드
_ELIG_KEYWORDS = ("참가자격", "입찰참가", "자격요건", "실적", "참가 자격", "제한사항", "신청자격")

_SLOT_SCHEMA = {
    "name": "eligibility_slots",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "유형": {
                            "type": "string",
                            "enum": ["실적요건", "인력요건", "인증요건",
                                     "면허요건", "지역요건", "기타요건"],
                        },
                        "raw": {"type": "string",
                                "description": "요건 원문 그대로. 요약·변형 금지"},
                        "기간_raw": {"type": ["string", "null"],
                                    "description": "기간 표현 원문 (예: '최근 3년'). 없으면 null"},
                        "금액_raw": {"type": ["string", "null"],
                                    "description": "금액 표현 원문 (예: '5억원 이상'). 없으면 null"},
                        "근거조항": {"type": ["string", "null"],
                                    "description": "해당 요건이 적힌 조항 번호/라벨. 본문에 없으면 null"},
                    },
                    "required": ["유형", "raw", "기간_raw", "금액_raw", "근거조항"],
                },
            }
        },
        "required": ["requirements"],
    },
}

_SYSTEM = """너는 입찰공고 RFP에서 참가자격 요건을 추출하는 도구다. 규칙:
1. 본문에 **명시된 요건만** 추출한다. 없는 요건을 만들어내지 마라. 없으면 빈 배열.
2. raw에는 원문 문장을 그대로 담는다. 요약하거나 수치를 변환하지 마라.
3. 기간_raw/금액_raw에는 원문 표현 문자열만 담는다. 숫자로 바꾸지 마라.
4. 근거조항에는 그 요건이 적힌 조항 번호(예: "3.2", "제4조")를 담되, 제공된 텍스트에서 확인되는 것만 적는다."""


_TOP_LEVEL_LABEL_RE = re.compile(r"^(?:\d+|[가-힣]|[IVXivx]+|제\d+조(?:의\d+)?|제\d+장)$")


def _is_top_level(chunk):
    """장·절 수준의 상위 헤딩인가 (하위 항목 2.1, 3.2 등은 아님)."""
    label = chunk.get("clause_label")
    return bool(label) and bool(_TOP_LEVEL_LABEL_RE.match(label.strip()))


def _eligibility_chunks(chunks):
    """자격요건 절 전체를 모은다 — 헤딩 청크만 잡으면 안 된다.

    청커는 "2.1", "2.2"를 각각 독립 청크로 자르는데 "참가자격" 키워드는
    상위 헤딩("2. 입찰 참가자격")에만 있다. 키워드 청크만 넘기면 정작 요건이
    적힌 하위 조항이 LLM에 전달되지 않아 재현율이 무너진다.

    그래서 키워드가 걸린 청크를 앵커로 삼고, 그 뒤로 이어지는 하위 항목
    청크를 **다음 상위 헤딩이 나올 때까지** 함께 포함한다. 번호 체계가
    "2 → 2.1"이든 "나 → 3.1"이든 동작하도록 접두어가 아닌 계층 수준으로 판단한다.
    """
    selected = {}
    for i, chunk in enumerate(chunks):
        if not any(kw in chunk["text"] for kw in _ELIG_KEYWORDS):
            continue
        selected[i] = chunk
        if not _is_top_level(chunk):
            continue
        for j in range(i + 1, len(chunks)):
            nxt = chunks[j]
            if _is_top_level(nxt) and \
                    not any(kw in nxt["text"] for kw in _ELIG_KEYWORDS):
                break  # 다음 상위 절로 넘어감
            selected[j] = nxt
    if selected:
        return [selected[i] for i in sorted(selected)]
    return chunks[:8]  # 키워드 실패 시 문서 앞부분(자격은 보통 앞에 있음)


def _validate_slot(slot, chunks):
    """LLM이 붙인 근거조항이 실제 청크 라벨/본문과 일치하는지 코드로 검증.

    또한 raw가 실제 본문에 존재하는지(과잉 추출 방지) 확인한다.
    """
    raw = (slot.get("raw") or "").strip()
    if not raw:
        return False, "raw 비어 있음"
    # 원문 존재 검증 — 공백 차이를 무시하고 부분 일치 확인
    def squash(s):
        return re.sub(r"\s+", "", s)
    all_text = squash("\n".join(c["text"] for c in chunks))
    probe = squash(raw)[:40]
    if probe and probe not in all_text:
        return False, "raw가 본문에 존재하지 않음(과잉 추출 의심)"

    ref = slot.get("근거조항")
    if ref:
        labels = {c["clause_label"] for c in chunks if c["clause_label"]}
        # "조항 3", "제3조", "3." 같은 표기 차이를 흡수해 라벨과 대조
        norm_ref = re.sub(r"^(?:조항|제)\s*", "", ref.strip()).rstrip(".)조항 ")
        if labels and norm_ref not in labels and \
                not any(norm_ref in (c["text"][:120]) for c in chunks):
            return False, f"근거조항 '{ref}'가 실제 조항 라벨과 불일치"
    return True, ""


def extract_slots(chunks, max_retry=1):
    """자격요건 슬롯 추출 + 코드 검증 + 정규화.

    반환: {"slots": [...], "status": "ok"|"llm_unavailable"|"failed", "notes": str}
    각 슬롯에는 normalize 결과(금액_norm, 기간_norm)가 붙는다 — 변환은 코드가 한다.
    """
    client = get_client("luna")
    if not client.available:
        return {"slots": [], "status": "llm_unavailable",
                "notes": "OPENAI_API_KEY 미설정 — 슬롯 추출 생략(확인 불가 처리)"}

    target = _eligibility_chunks(chunks)
    body = "\n\n".join(
        f"[조항 {c['clause_label'] or '(라벨없음)'}]\n{c['text']}" for c in target)[:24000]

    last_notes = ""
    for attempt in range(max_retry + 1):
        try:
            result = client.chat(_SYSTEM, body, json_schema=_SLOT_SCHEMA)
        except Exception as e:
            return {"slots": [], "status": "failed", "notes": f"LLM 호출 실패: {e}"}
        slots = []
        rejected = []
        for slot in result.get("requirements", []):
            ok, why = _validate_slot(slot, target)
            if not ok:
                rejected.append(f"{slot.get('raw', '')[:30]}: {why}")
                continue
            # 숫자 변환은 코드(normalize)가 담당
            if slot.get("금액_raw"):
                slot["금액_norm"] = normalize_value(slot["금액_raw"])
            if slot.get("기간_raw"):
                slot["기간_norm"] = normalize_value(slot["기간_raw"])
            slots.append(slot)
        if slots or not result.get("requirements"):
            notes = f"검증 탈락 {len(rejected)}건: {rejected}" if rejected else ""
            return {"slots": slots, "status": "ok", "notes": notes}
        last_notes = f"전 슬롯 검증 탈락(시도 {attempt + 1}): {rejected}"
        # 전부 탈락 → 재추출
    return {"slots": [], "status": "failed", "notes": last_notes}
