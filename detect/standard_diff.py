# -*- coding: utf-8 -*-
"""경로 A — 표준 대조형 탐지.

RFP 조항 ↔ 표준 조항을 (형식 매칭 + 임베딩 유사도)로 매칭한 뒤,
normalize 모듈로 정규화한 수치를 **코드가 비교**한다. LLM에게 판정을 묻지 않는다.

판정 결과: "확인 필요" | "적합" | "확인 불가"
- 수치 파싱 실패 → 임의 판정하지 않고 "확인 불가 — 담당자 확인 필요"

조항 식별은 고정 문자열이 아니라 **어휘 부품 조합 정규식**(lexicon.py)으로 한다.
"하자보수" 한 단어가 아니라 [하자|결함|불량] + [보수|담보|책임] 형식을 보므로
"하자담보책임기간", "결함을 보수하여야" 같은 다른 표기도 같은 조항으로 인식한다.

주의: 지체상금'율' 수치 판정은 프로토타입 범위에서 제외.
용역계약일반조건 제55조가 시행규칙 제75조로 위임만 하고 있고 시행규칙 원문이
미확보 상태이므로, 상한(계약금액의 100분의 30, 제18조제1항)만 판정한다.
이 제외 사실은 리포트의 "확인 불가" 섹션에 항상 표기된다.
"""
import re

from llm.embeddings import similarity_matrix
from normalize import extract_values
from standards.indexer import find_clause

from .embedding_fallback import find_via_embedding
from .lexicon import (
    AUTHORITY_RE,
    DECREASE_RE,
    DEFECT_NOUN,
    DELAY_PENALTY_RE,
    INSPECTION_RE,
    IP_NOUN_RE,
    JOINT_OWNERSHIP_RE,
    PRODUCT_RE,
    SOLE_VERB_RE,
    TERMINATION_RE,
)

_GAP = r"[^.\n]{0,30}?"
_SGAP = r"[^.\n]{0,15}?"

# 표준 대조 규칙 — 스펙의 "실제로 쓸 조항" 표와 1:1 대응. 유형을 임의로 늘리지 않는다.
# match: 이 조항인지 식별하는 형식 정규식 (부품 조합)
# sentence_exclude: 같은 문장에 있으면 이 규칙의 대상이 아님 (수치 오귀속 차단)
RULES = [
    {
        "id": "warranty_period",
        "name": "하자보수 기간 과다",
        "std_source": "용역계약일반조건",
        "std_clause_no": "58조",
        "std_ref": "용역계약일반조건 제58조제1항",
        "std_desc": "인수 확인 후 1년",
        "std_value": 12, "unit": "MONTH", "direction": "gt",  # RFP > 표준 → 확인 필요
        # [하자|결함|불량] + [보수|담보|책임|수정] 또는 무상 유지보수 형식
        "match": rf"{DEFECT_NOUN}{_SGAP}(?:보수|담보|책임|수정)"
                 rf"|무상\s*(?:유지\s*)?(?:보수|관리)"
                 rf"|무상으?로?{_SGAP}(?:보수|수정)",
        # 하자보수'보증금'(율)은 별도 규칙이 담당 — 같은 문장이면 제외
        "sentence_exclude": r"보증금|이행보증",
    },
    {
        "id": "warranty_bond_rate",
        "name": "하자보수보증금율 과다",
        "std_source": "용역계약일반조건",
        "std_clause_no": "59조",
        "std_ref": "용역계약일반조건 제59조제1항",
        "std_desc": "계약금액의 100분의 2",
        "std_value": 2, "unit": "PERCENT", "direction": "gt",
        # [하자|결함] + (수식어) + [보증금|이행보증] — "하자담보책임 보증금"까지 포함
        "match": rf"{DEFECT_NOUN}[^.\n]{{0,12}}?(?:보증금|이행보증)",
    },
    {
        "id": "ip_ownership",
        "name": "저작권(지식재산권) 귀속",
        "std_source": "용역계약일반조건",
        "std_clause_no": "56조",
        "std_ref": "용역계약일반조건 제56조제1항",
        "std_desc": "발주기관·계약상대자 공동소유, 지분 균등",
        "std_value": None, "unit": None, "direction": "text",
        "match": rf"(?:{IP_NOUN_RE}|{PRODUCT_RE})",
        # 단독 귀속 형식: [권리|산출물] … [발주자측 주체] … [귀속|소유|보유|이전|양도]
        "text_forms": [
            rf"(?:{IP_NOUN_RE}|{PRODUCT_RE}){_GAP}{AUTHORITY_RE}{_SGAP}{SOLE_VERB_RE}",
            rf"{AUTHORITY_RE}{_GAP}(?:{IP_NOUN_RE}|{PRODUCT_RE}){_SGAP}{SOLE_VERB_RE}",
        ],
        # 표준 부합 문언 — 같은 문장에 있으면 단독 귀속이 아니다
        "text_ok": JOINT_OWNERSHIP_RE,
    },
    {
        "id": "penalty_cap",
        "name": "지체상금 상한 초과",
        "std_source": "용역계약일반조건",
        "std_clause_no": "18조",
        "std_ref": "용역계약일반조건 제18조제1항",
        "std_desc": "지체상금 총액은 계약금액의 100분의 30 이내",
        "std_value": 30, "unit": "PERCENT", "direction": "gt",
        "match": DELAY_PENALTY_RE,
        # 지체상금'율'(일할 요율)은 판정 제외 — 0.5% 안팎의 작은 값은 상한 비교 대상 아님
        "min_value_filter": 5,
    },
    {
        "id": "inspection_period",
        "name": "검수 기간 과다",
        "std_source": "용역계약일반조건",
        "std_clause_no": "20조",
        "std_ref": "용역계약일반조건 제20조제2항",
        "std_desc": "통지받은 날부터 14일 이내 검사",
        "std_value": 14 / 30, "unit": "MONTH", "direction": "gt",
        "match": INSPECTION_RE,
        # "하자담보책임기간은 검수완료일로부터 36개월" 같은 문장의 수치 오귀속 차단
        "sentence_exclude": r"하자|결함|무상|담보|유지\s*(?:보수|관리)",
    },
    {
        "id": "termination_threshold",
        "name": "계약금액 감소로 인한 해지 요건 강화",
        "std_source": "용역계약일반조건",
        "std_clause_no": "31조",
        "std_ref": "용역계약일반조건 제31조제1항",
        "std_desc": "계약금액 100분의 40 이상 감소 시 해제·해지 가능",
        "std_value": 40, "unit": "PERCENT", "direction": "gt",
        "match": TERMINATION_RE,
        # 감소·축소·삭감·줄어듦 등 감액 표현이 같이 있어야 이 조항이다
        "require": DECREASE_RE,
    },
]

for _r in RULES:
    _r["_match_re"] = re.compile(_r["match"])
    _r["_require_re"] = re.compile(_r["require"]) if _r.get("require") else None
    _r["_excl_re"] = re.compile(_r["sentence_exclude"]) if _r.get("sentence_exclude") else None
    _r["_ok_re"] = re.compile(_r["text_ok"]) if _r.get("text_ok") else None
    _r["_form_res"] = [re.compile(p) for p in _r.get("text_forms", [])]

# 임베딩 유사도 최소 문턱 (형식 매칭 후 확인용)
_SIM_THRESHOLD = 0.15

# 문장 분리 — 종결어미 뒤, 줄바꿈, 항목 구분자
_SENT_SPLIT_RE = re.compile(r"(?<=다\.)\s*|(?<=함\.)\s*|(?<=음\.)\s*|\n")


def _sentence_ok(rule, s):
    if not rule["_match_re"].search(s):
        return False
    if rule["_require_re"] and not rule["_require_re"].search(s):
        return False
    if rule["_excl_re"] and rule["_excl_re"].search(s):
        return False
    return True


def _relevant_sentences(rule, text):
    """규칙 형식에 부합하는 문장만 추출 — 같은 청크의 무관한 수치 오귀속 방지."""
    return [s for s in _SENT_SPLIT_RE.split(text) if s and _sentence_ok(rule, s)]


def _candidate_chunks(rule, chunks):
    """규칙에 해당하는 문장을 하나라도 가진 청크."""
    return [ch for ch in chunks if _relevant_sentences(rule, ch["text"])]


def _excerpt(text, limit=200):
    t = " ".join(text.split())
    return t[:limit] + ("…" if len(t) > limit else "")


def _make_finding(rule, std_clause, chunk, verdict, reason, rfp_value=None,
                  matched_text=None, matched_via="regex"):
    return {
        "risk_type": rule["name"],
        "rule_id": rule["id"],
        "detection_method": "standard_diff",
        # regex: 1차 정규식/lexicon.py가 찾음. embedding_llm: 정규식이 못 찾아
        # 임베딩 검색 + Luna 추출로 보강한 결과(detect/embedding_fallback.py).
        "matched_via": matched_via,
        "verdict": verdict,  # "확인 필요" | "적합" | "확인 불가"
        "reason": reason,
        "matched_text": matched_text,
        "rfp_clause_label": chunk.get("clause_label") if chunk else None,
        "rfp_chunk_id": chunk.get("chunk_id") if chunk else None,
        "rfp_excerpt": _excerpt(chunk["text"]) if chunk else None,
        "rfp_value": rfp_value,
        "standard": {
            "source": rule["std_source"],
            "clause_ref": rule["std_ref"],
            "std_desc": rule["std_desc"],
            "text_excerpt": _excerpt(std_clause["text"], 250) if std_clause else None,
            "chapter": std_clause.get("chapter") if std_clause else None,
        },
    }


def _judge_numeric(rule, chunk):
    """관련 문장에서 해당 단위의 수치를 뽑아 표준값과 비교.

    반환 (verdict, reason, value). 관련 문장이 없으면 verdict=None —
    이 청크는 해당 규칙의 판정 대상이 아니다.
    """
    sentences = _relevant_sentences(rule, chunk["text"])
    if not sentences:
        return (None, "규칙 형식에 맞는 문장 없음 — 판정 대상 아님", None)
    scope = " ".join(sentences)
    values = [v for v in extract_values(scope) if v["unit"] == rule["unit"]]
    minf = rule.get("min_value_filter")
    if minf is not None:
        values = [v for v in values if v["value"] is None or v["value"] >= minf]
    if not values:
        return ("확인 불가",
                "관련 조항은 있으나 수치 정규화 실패 — 담당자 확인 필요", None)
    worst = max(values, key=lambda v: v["value"] if v["value"] is not None else -1)
    if worst["value"] is None:
        return ("확인 불가", "수치 정규화 실패 — 담당자 확인 필요", None)
    # 부동소수점 오차 방어 (예: 14일 -> 0.4667개월 vs 표준 14/30개월)
    if worst["value"] > rule["std_value"] + 1e-4:
        return ("확인 필요", f"RFP 값이 표준({rule['std_desc']})을 초과", worst)
    return ("적합", f"표준({rule['std_desc']}) 이내", worst)


def _judge_text(rule, chunk):
    """문언 규칙(저작권 귀속) 판정 — **문장 단위**로 본다.

    같은 청크에 표준 부합 문장과 단독 귀속 문장이 섞여 있을 수 있으므로,
    청크 전체가 아니라 문장별로 공동소유 문언 여부를 먼저 확인한다.
    """
    sentences = _relevant_sentences(rule, chunk["text"])
    if not sentences:
        return (None, "규칙 형식에 맞는 문장 없음 — 판정 대상 아님", None, None)
    saw_joint = False
    for s in sentences:
        if rule["_ok_re"] and rule["_ok_re"].search(s):
            saw_joint = True
            continue  # 이 문장은 표준 부합 — 단독 귀속 판정 대상 아님
        for pat in rule["_form_res"]:
            m = pat.search(s)
            if m:
                return ("확인 필요",
                        f"표준({rule['std_desc']})과 다른 단독 귀속 문언",
                        None, m.group(0).strip())
    if saw_joint:
        return ("적합", "표준과 같은 공동소유·지분균등 문언 확인", None, None)
    return ("확인 불가",
            "관련 조항은 있으나 귀속 방식 문언을 확정하지 못함 — 담당자 확인 필요",
            None, None)


_ORDER = {"확인 필요": 0, "적합": 1, "확인 불가": 2}


def detect_standard_diff(chunks, clauses):
    """경로 A 실행. findings 목록 반환 (적합 판정 포함 — 리포트에서 필터).

    2단 구성:
      1차 — 정규식/lexicon.py (즉시, 무료). 알려진 표현은 여기서 끝난다.
      2·3차 — 1차가 "확인 필요"/"적합"에 이르지 못했을 때만(=아무것도 못 찾았거나
              "확인 불가"에 그쳤을 때만), 정규식이 안 본 청크 중에서 임베딩 유사도로
              후보를 찾고 Luna로 원문 근거를 뽑아 같은 임계값 비교를 한 번 더 시도한다
              (detect/embedding_fallback.py). 판정 로직 자체는 동일하고, 근거를
              찾는 방법만 다르다 — 정규식 사전에 없는 표현("품질을 보장하며 자비로
              해결")도 이 경로로 잡힌다.

    비용 통제: 1차가 이미 확신 있는 결론(확인 필요/적합)을 낸 규칙은 2·3차를
    아예 실행하지 않는다. 문서 하나에 대해 최악의 경우도 "1차가 확인 불가이거나
    아무것도 못 찾은 규칙 수" 만큼만 LLM 호출이 늘어난다.
    """
    findings = []
    for rule in RULES:
        std_clause = find_clause(clauses, rule["std_source"], rule["std_clause_no"])
        candidates = _candidate_chunks(rule, chunks)
        checked_ids = {c["chunk_id"] for c in candidates}

        rule_findings = []
        if candidates:
            # 임베딩 유사도로 정규식 후보 중 표준 조항과 가장 관련 깊은 청크를 선별
            best = candidates
            if std_clause and len(candidates) > 1:
                try:
                    matrix, _method = similarity_matrix(
                        [c["text"] for c in candidates], [std_clause["text"]])
                    scored = sorted(zip(candidates, (row[0] for row in matrix)),
                                    key=lambda x: -x[1])
                    best = [c for c, s in scored if s >= _SIM_THRESHOLD] or [scored[0][0]]
                except Exception:
                    best = candidates  # 임베딩 실패 시 형식 매칭 후보 전체 검사

            for chunk in best:
                matched = None
                if rule["direction"] == "text":
                    verdict, reason, value, matched = _judge_text(rule, chunk)
                else:
                    verdict, reason, value = _judge_numeric(rule, chunk)
                if verdict is None:
                    continue  # 이 청크는 해당 규칙의 판정 대상 아님
                rule_findings.append(
                    _make_finding(rule, std_clause, chunk, verdict, reason, value, matched))

        rule_findings.sort(key=lambda f: _ORDER[f["verdict"]])
        best_finding = rule_findings[0] if rule_findings else None

        if best_finding is None or best_finding["verdict"] == "확인 불가":
            ev_verdict, ev_reason, ev_value, ev_quote, ev_chunk = find_via_embedding(
                rule, std_clause, chunks, checked_ids)
            if ev_verdict is not None:
                ev_finding = _make_finding(rule, std_clause, ev_chunk, ev_verdict, ev_reason,
                                           ev_value, ev_quote, matched_via="embedding_llm")
                if best_finding is None or _ORDER[ev_verdict] < _ORDER[best_finding["verdict"]]:
                    best_finding = ev_finding
                # 둘 다 "확인 불가"면 정규식 쪽 사유를 그대로 유지 (표준 원문과
                # 더 가까운 근거이므로) — best_finding은 바꾸지 않는다.

        if best_finding is not None:
            findings.append(best_finding)
    return findings
