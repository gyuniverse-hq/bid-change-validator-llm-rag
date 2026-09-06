# -*- coding: utf-8 -*-
"""경로 B — 패턴 탐지형 (과업범위 모호).

과업범위 모호는 표준에 대응 수치가 없다. "표준에서 벗어난 값"이 아니라
범위를 무한정 열어두는 **문구 형식**의 문제이므로 정규식/키워드 규칙으로 탐지한다.
RAG 대조를 쓰지 않는다.

문장이 아니라 형식에 대응한다:
  포괄조항은 [잔여지시어][재량주체][재량동사][열린대상] 같은 부품 조합으로 나타난다.
  부품 사전(lexicon.py)에서 조합해 패턴을 생성하므로, 동의어 하나를 사전에
  추가하면 그 부품을 쓰는 모든 형식이 함께 넓어진다.
"""
import re

from .lexicon import (
    ANCILLARY_RE,
    AUTHORITY_RE,
    DEFERRAL_RE,
    DEFERRAL_VERB,
    DISCRETION_RE,
    OPEN_OBJECT_RE,
    RESIDUAL_RE,
    SCOPE_OBJECT_RE,
)

# 문장 내 부품 사이에 끼어들 수 있는 수식어구의 최대 폭
_GAP = r"[^.\n]{0,30}?"
_SGAP = r"[^.\n]{0,15}?"

# ── 포괄조항 형식 정의 ───────────────────────────────────────────────────
# 각 항목: (형식 이름, 정규식, 사유, 맥락 가드 필요 여부)
_FORMS = [
    (
        "잔여지시어+재량동사+열린대상",
        rf"{RESIDUAL_RE}{_GAP}{DISCRETION_RE}{_SGAP}{OPEN_OBJECT_RE}",
        "과업 범위를 무한정 확장하는 포괄조항",
        False,
    ),
    (
        "재량주체+필요인정",
        rf"{AUTHORITY_RE}{_SGAP}필요하다고\s*인정(?:하는|하여|되는|하면)",
        "발주기관 재량으로 범위가 열리는 포괄조항",
        False,
    ),
    (
        "부수·수반 표현",
        rf"{ANCILLARY_RE}(?:되는|하는|적인|된)\s*{_SGAP}(?:일체|모든|제반|전부)?\s*{OPEN_OBJECT_RE}",
        "'부수·수반되는 일체' 형식 — 범위를 닫지 않는 포괄 표현",
        True,
    ),
    (
        # 대상을 SCOPE_OBJECT로 좁힌다. "손해배상 등 일체의 민·형사상 책임" 같은
        # 법률 상용구는 과업범위 조항이 아니므로 잡으면 안 된다.
        "열거 뒤 확장",
        rf"등\s*(?:에\s*관한|의|을\s*포함(?:한|하여|하는)|과\s*관련된)?\s*"
        rf"(?:일체의?\s*|모든\s*|제반\s*)?{SCOPE_OBJECT_RE}",
        "열거 뒤 무한 확장 표현",
        True,
    ),
    (
        "미확정 위임",
        rf"{DEFERRAL_RE}{_SGAP}{DEFERRAL_VERB}",
        "범위 미확정 — 협의·추후 결정 위임 조항",
        True,
    ),
]

_COMPILED = [(name, re.compile(pat), reason, guarded)
             for name, pat, reason, guarded in _FORMS]

# 일부 형식은 법령·일반 문서에도 흔하므로 과업 맥락에서만 탐지한다
_SCOPE_CONTEXT_KEYWORDS = ("과업", "업무", "수행", "요구사항", "산출물", "용역", "사업")

# 별지서식·관리대장 등 양식 청크는 과업 조항이 아니므로 탐지 제외
_FORM_MARKER_RE = re.compile(
    r"별지\s*서식|관리대장|\(인\)\s*$|서명\s*\d|년\s*월\s*일\s*확인자", re.MULTILINE)


def _excerpt(text, limit=200):
    t = " ".join(text.split())
    return t[:limit] + ("…" if len(t) > limit else "")


def detect_patterns(chunks):
    """경로 B 실행. 청크당 형식별 최대 1건의 finding."""
    findings = []
    for chunk in chunks:
        text = chunk["text"]
        if _FORM_MARKER_RE.search(text):
            continue
        has_scope_ctx = any(kw in text for kw in _SCOPE_CONTEXT_KEYWORDS)
        seen_spans = []
        for name, pat, reason, guarded in _COMPILED:
            m = pat.search(text)
            if not m:
                continue
            if guarded and not has_scope_ctx:
                continue
            # 같은 자리를 다른 형식이 중복 보고하지 않도록 span 겹침 제거
            if any(not (m.end() <= s or m.start() >= e) for s, e in seen_spans):
                continue
            seen_spans.append((m.start(), m.end()))
            findings.append({
                "risk_type": "과업범위 모호(포괄조항)",
                "rule_id": "open_ended_scope",
                "detection_method": "pattern_match",
                "form": name,
                "verdict": "확인 필요",
                "reason": reason,
                "matched_text": m.group(0).strip(),
                "rfp_clause_label": chunk.get("clause_label"),
                "rfp_chunk_id": chunk.get("chunk_id"),
                "rfp_excerpt": _excerpt(text),
                "rfp_value": None,
                "standard": None,  # 표준 대응 수치가 존재하지 않는 유형
            })
    return findings
