# -*- coding: utf-8 -*-
"""경로 A 2·3차 — 정규식(lexicon.py)이 놓친 조항을 임베딩 검색 + Luna 추출로 보강.

1차(정규식)가 "확인 필요" 또는 "적합"에 **도달하지 못했을 때만** 실행한다.
문서마다 규칙 6개 × 청크 전체를 매번 LLM에 태우면 비용·지연이 크므로,
싼 경로가 이미 확신을 가진 규칙은 건드리지 않는다 — 이게 이 파일이 별도
모듈로 분리된 이유다: standard_diff.py의 빠른 경로와 여기의 보강 경로가
같은 자리에 있으면 "언제 호출되는지"가 흐려진다.

역할 분담은 eligibility/slots.py와 동일하다(같은 계약을 재사용한다):
  - Luna는 원문 인용(quote)과 수치 원문 문자열(value_raw)만 뽑는다.
    숫자로 바꾸거나 충족/미충족을 판단하지 않는다.
  - 코드가 quote가 실제로 원문에 있는지 검증한다(환각 차단).
  - 코드가 normalize로 수치화하고, standard_diff.py와 동일한 임계값 비교로
    판정한다 — 판정 로직 자체는 정규식 경로와 완전히 같다, 근거를 찾는
    방법만 다르다.
"""
import re

from llm import get_client
from llm.embeddings import similarity_matrix
from normalize import extract_values

# 1차보다 엄격한 문턱 — LLM 호출 전에 후보를 최대한 좁힌다 (비용 억제)
_SIM_THRESHOLD = 0.22
_TOP_K = 3

_EVIDENCE_SCHEMA = {
    "name": "clause_evidence",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "on_topic": {
                "type": "boolean",
                "description": "이 텍스트가 실제로 [조항 설명]과 같은 주제를 다루는가",
            },
            "quote": {
                "type": ["string", "null"],
                "description": "판단 근거가 되는 원문 문장 그대로 옮긴 것. 요약·의역 금지. on_topic=false면 null",
            },
            "value_raw": {
                "type": ["string", "null"],
                "description": ("수치형 규칙일 때만: 기간/비율 표현을 원문 그대로 담는다 "
                                "(예: '3년간', '100분의 50'). 숫자로 계산·변환하지 마라. "
                                "문언형 규칙이거나 해당 값이 없으면 null"),
            },
            "ownership": {
                "type": ["string", "null"],
                "description": ("문언형(권리 귀속) 규칙일 때만: "
                                "'발주기관단독' | '공동' | '계약상대자단독' | '불명확' 중 하나. "
                                "수치형 규칙이면 null"),
            },
        },
        "required": ["on_topic", "quote", "value_raw", "ownership"],
    },
}

_SYSTEM = """너는 RFP 조항 텍스트에서 특정 주제의 근거를 찾아 옮겨 적는 도구다. 규칙:
1. [조항 설명]과 실제로 같은 주제를 다루는 문장이 있을 때만 on_topic=true로 하라.
   비슷해 보여도 다른 주제(예: 다른 종류의 보증금, 다른 기간)면 false로 하라.
2. quote는 원문 문장을 그대로 옮긴다. 요약하거나 표현을 바꾸지 마라.
3. value_raw(수치 표현)는 원문 그대로 담는다. 계산하거나 숫자로 바꾸지 마라.
4. 판단(적절한지, 기준을 초과하는지 등)은 절대 하지 마라. 사실을 찾아 옮기기만 하라."""


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def _quote_verified(quote, chunk_text):
    """LLM이 인용한 문장이 실제로 원문에 있는지 대조 — 환각 차단."""
    if not quote:
        return False
    return _squash(quote)[:80] in _squash(chunk_text)


def _extract_evidence(rule, std, chunk):
    """청크 하나에서 Luna로 근거를 추출.

    표준 조항 원문을 함께 주는 게 중요하다 — "하자보수 기간 과다"라는 짧은
    이름만으로는 "품질을 보장하며 자비로 해결한다"처럼 하자보수 관련 어휘를
    전혀 안 쓴 표현이 같은 주제인지 LLM이 매번 다르게(들쭉날쭉) 판단한다.
    표준 조항 원문 전체를 주면 무엇과 비교해야 하는지가 분명해져 안정된다.
    """
    client = get_client("luna")
    if not client.available:
        return None
    std_clause = std.get("clause")
    topic = f"{rule['name']} — {std['desc']}"
    if std_clause and std_clause.get("text"):
        topic += f"\n\n표준 조항 원문({std_clause.get('title', '')}):\n{std_clause['text'][:500]}"
    user = f"[조항 설명]\n{topic}\n\n[검토할 텍스트]\n{chunk['text'][:2000]}"
    try:
        out = client.chat(_SYSTEM, user, json_schema=_EVIDENCE_SCHEMA)
    except Exception:
        return None
    if not out.get("on_topic") or not out.get("quote"):
        return None
    if not _quote_verified(out["quote"], chunk["text"]):
        return None  # 인용이 원문에 없음 — 환각으로 간주하고 폐기
    return out


def find_via_embedding(rule, std, chunks, exclude_ids):
    """정규식이 놓친 청크 중 임베딩 유사도 상위 후보를 Luna로 확인한다.

    반환: (verdict, reason, value_or_None, quote_or_None, chunk_or_None).
    표준 조항 원문이 없거나, 후보가 없거나, 확신 있는 결론이 안 나오면
    (None, "", None, None, None) — 이 규칙에 대해 아무것도 찾지 못했다는 뜻.
    """
    std_clause = std.get("clause") if std else None
    if not std_clause or std.get("status") != "ok":
        return None, "", None, None, None
    pool = [c for c in chunks if c["chunk_id"] not in exclude_ids and c["text"].strip()]
    if not pool:
        return None, "", None, None, None

    query = f"{rule['name']} — {std['desc']}. {std_clause['text'][:300]}"
    try:
        matrix, _method = similarity_matrix([c["text"] for c in pool], [query])
    except Exception:
        return None, "", None, None, None

    scored = sorted(zip(pool, (row[0] for row in matrix)), key=lambda x: -x[1])
    top = [c for c, s in scored[:_TOP_K] if s >= _SIM_THRESHOLD]
    if not top:
        return None, "", None, None, None

    for chunk in top:
        evidence = _extract_evidence(rule, std, chunk)
        if evidence is None:
            continue

        if rule["direction"] == "text":
            ownership = evidence.get("ownership")
            if ownership == "발주기관단독":
                return ("확인 필요",
                        f"표준({std['desc']})과 다른 단독 귀속 문언(AI 보강 탐지)",
                        None, evidence["quote"], chunk)
            if ownership == "공동":
                return ("적합", "표준과 같은 공동소유 문언 확인(AI 보강 탐지)",
                        None, evidence["quote"], chunk)
            continue  # 불명확/계약상대자단독 등 — 이 청크로는 결론 못 냄, 다음 후보

        value_raw = evidence.get("value_raw")
        if not value_raw:
            continue
        values = [v for v in extract_values(value_raw) if v["unit"] == std["unit"]]
        if not values or values[0]["value"] is None:
            continue
        val = values[0]
        minf = rule.get("min_value_filter")
        if minf is not None and val["value"] < minf:
            continue
        if val["value"] > std["value"] + 1e-4:
            return ("확인 필요", f"RFP 값이 표준({std['desc']})을 초과(AI 보강 탐지)",
                    val, evidence["quote"], chunk)
        return ("적합", f"표준({std['desc']}) 이내(AI 보강 탐지)",
                val, evidence["quote"], chunk)

    return None, "", None, None, None
