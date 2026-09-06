# -*- coding: utf-8 -*-
"""표준값 도출 — 계약예규 **원문에서** 판정 기준 수치를 뽑는다.

이 모듈이 존재하는 이유:
  이전에는 `detect/standard_diff.py`의 RULES에 하자보수 12개월, 지체상금 상한 30%
  같은 숫자가 **직접 적혀** 있었다. 같은 숫자가 clauses.json(예규 원문)에도 있으니
  한 값이 두 곳에 살았고, 예규가 개정되면 사람이 코드를 고쳐야 했다. 고치는 걸
  잊으면 코드는 옛 기준으로 조용히 판정을 계속한다 — 틀린 답을 확신 있게 내놓는
  가장 나쁜 실패다.

그래서 숫자는 여기서 **매번 예규 원문에서 추출**한다. 코드에 남는 것은 숫자가
아니라 "원문의 어디를 봐야 하는가"(anchor)뿐이다. 예규가 1년→2년으로 개정되면
clauses.json만 다시 만들면 판정 기준이 따라 바뀐다.

절대 원칙을 그대로 따른다:
  - 값 추출은 정규식 앵커 + `normalize/`(순수 코드)다. LLM은 개입하지 않는다.
  - **추출에 실패하면 옛 숫자로 폴백하지 않는다.** 근거가 없으면 판정하지 않는
    것이 이 프로젝트의 원칙이므로, 해당 규칙은 "확인 불가"가 된다. 조용히 낡은
    상수를 쓰는 것보다 판정을 보류하는 쪽이 안전하다.
  - `recorded`(작성 시점의 예규 값)는 **판정에 절대 쓰지 않는다.** 추출값과
    달라졌을 때 "예규가 개정된 것 같다"고 알리는 감시선(tripwire)일 뿐이다.
"""
import re

from normalize import extract_values

from .indexer import find_clause

# ── 표준값 추출 명세 ─────────────────────────────────────────────────────
# anchor : 예규 원문에서 **수치가 들어 있는 짧은 구간**을 잡는 정규식.
#          그룹 1이 수치 구간이며, 이 구간만 normalize에 넘긴다.
#          청크 전체를 넘기면 같은 조문의 다른 숫자(제21조, 100분의 50 등)를
#          잘못 집어오므로 반드시 좁게 잡는다.
# unit   : 이 규칙이 비교할 단위. 이 단위로 정규화된 값만 채택한다.
# recorded: 이 명세를 쓴 시점(2026-04-30 예규 제149호)의 값. 감시선 전용.
# note   : 원문에서 그 수치가 어떤 문장에 있는지 — 앵커가 깨졌을 때 사람이
#          어디를 봐야 하는지 알려주는 힌트.
SPECS = {
    "warranty_period": {
        "source": "용역계약일반조건",
        "clause_no": "58조",
        "ref": "용역계약일반조건 제58조제1항",
        "desc_template": "인수 확인 후 {value}",
        "anchor": r"종료를\s*확인한\s*후\s*([^(]{1,12}?)간",
        "unit": "MONTH",
        "recorded": 12,
        "note": "제58조제1항 '사업의 종료를 확인한 후 1년간 ... 보수책임'",
    },
    "warranty_bond_rate": {
        "source": "용역계약일반조건",
        "clause_no": "59조",
        "ref": "용역계약일반조건 제59조제1항",
        "desc_template": "계약금액의 {value}",
        "anchor": r"하자보수보증금율\s*\(\s*([^,)]{1,20})",
        "unit": "PERCENT",
        "recorded": 2,
        "note": "제59조제1항 '하자보수보증금율(100분의 2, ...)'",
    },
    "penalty_cap": {
        "source": "용역계약일반조건",
        "clause_no": "18조",
        "ref": "용역계약일반조건 제18조제1항",
        "desc_template": "지체상금 총액은 계약금액의 {value} 이내",
        "anchor": r"초과하는\s*경우에는\s*([^으]{1,15}?)으로\s*한다",
        "unit": "PERCENT",
        "recorded": 30,
        "note": "제18조제1항 단서 '100분의 30을 초과하는 경우에는 100분의 30으로 한다'",
    },
    "inspection_period": {
        "source": "용역계약일반조건",
        "clause_no": "20조",
        "ref": "용역계약일반조건 제20조제2항",
        "desc_template": "통지받은 날부터 {value} 이내 검사",
        "anchor": r"통지를\s*받은\s*날부터\s*([^,]{1,12}?)\s*이내",
        "unit": "MONTH",
        "recorded": 14 / 30,
        "note": "제20조제2항 '통지를 받은 날부터 14일 이내에 ... 검사'",
    },
    "termination_threshold": {
        "source": "용역계약일반조건",
        "clause_no": "31조",
        "ref": "용역계약일반조건 제31조제1항",
        "desc_template": "계약금액 {value} 이상 감소 시 해제·해지 가능",
        "anchor": r"계약금액이\s*(.{1,15}?)\s*이상\s*감소",
        "unit": "PERCENT",
        "recorded": 40,
        "note": "제31조제1항제1호 '계약금액이 100분의 40이상 감소되었을 때'",
    },
    # 문언형 규칙 — 비교할 수치가 없다. 표준 문언이 예규 원문에 실제로
    # 남아 있는지만 확인한다(개정으로 공동소유 원칙이 사라지면 알아야 한다).
    "ip_ownership": {
        "source": "용역계약일반조건",
        "clause_no": "56조",
        "ref": "용역계약일반조건 제56조제1항",
        "desc_template": "발주기관·계약상대자 공동소유, 지분 균등",
        "anchor": r"(공동으로\s*소유하며[^.]{0,40}지분은\s*균등)",
        "unit": None,
        "recorded": None,
        "note": "제56조제1항 '발주기관과 계약상대자가 공동으로 소유하며 ... 지분은 균등'",
    },
}

# 표시용 단위 포맷 — 리포트 문구(std_desc)를 원문 값으로 만들 때 쓴다
def _fmt(value, unit):
    if unit == "MONTH":
        if abs(value - round(value)) < 1e-6:
            months = int(round(value))
            return f"{months // 12}년" if months % 12 == 0 and months >= 12 else f"{months}개월"
        return f"{round(value * 30)}일"
    if unit == "PERCENT":
        return f"100분의 {value:g}"
    return str(value)


def resolve_standard_value(rule_id, clauses):
    """규칙 하나의 표준값을 예규 원문에서 추출한다.

    반환:
    {
      "rule_id", "status": "ok"|"clause_missing"|"anchor_failed"|"normalize_failed",
      "value": float|None,      # 판정에 쓸 값. status!="ok"면 None
      "unit": str|None,
      "ref": str,               # 조항 출처 표기
      "desc": str,              # 리포트용 표준 설명 (원문 값으로 생성)
      "raw": str|None,          # 원문에서 잘라낸 수치 구간 그대로
      "clause": dict|None,      # 표준 조항 전체 (근거 표시용)
      "drift": None|{"recorded","extracted"},   # 예규 개정 의심 신호
      "notes": str,
    }
    """
    spec = SPECS[rule_id]
    clause = find_clause(clauses, spec["source"], spec["clause_no"])
    base = {
        "rule_id": rule_id, "value": None, "unit": spec["unit"],
        "ref": spec["ref"], "desc": spec["desc_template"].replace("{value}", "?"),
        "raw": None, "clause": clause, "drift": None, "notes": "",
    }
    if clause is None:
        base.update(status="clause_missing",
                    notes=f"{spec['source']} {spec['clause_no']}를 clauses.json에서 찾지 못함 "
                          f"— data/standards/ 원본과 인덱스를 확인하세요")
        return base

    m = re.search(spec["anchor"], clause["text"])
    if not m:
        base.update(status="anchor_failed",
                    notes=f"예규 원문에서 표준값 위치를 찾지 못함(문언 개정 의심) — {spec['note']}")
        return base

    raw = m.group(1).strip()
    base["raw"] = raw

    # 문언형 — 수치가 없다. 표준 문언이 원문에 남아 있음을 확인한 것으로 충분.
    if spec["unit"] is None:
        base.update(status="ok", desc=spec["desc_template"].replace("{value}", ""),
                    notes="")
        base["desc"] = spec["desc_template"]
        return base

    values = [v for v in extract_values(raw) if v["unit"] == spec["unit"]]
    values = [v for v in values if v.get("value") is not None]
    if not values:
        base.update(status="normalize_failed",
                    notes=f"표준값 구간 '{raw}'을 {spec['unit']} 단위로 정규화하지 못함")
        return base

    value = values[0]["value"]
    base.update(status="ok", value=value,
                desc=spec["desc_template"].format(value=_fmt(value, spec["unit"])))

    recorded = spec.get("recorded")
    if recorded is not None and abs(value - recorded) > 1e-4:
        base["drift"] = {"recorded": recorded, "extracted": value}
        base["notes"] = (
            f"예규 원문 값({_fmt(value, spec['unit'])})이 코드에 기록된 값"
            f"({_fmt(recorded, spec['unit'])})과 다릅니다 — 예규 개정으로 보입니다. "
            f"원문 값으로 판정했습니다. standards/values.py의 recorded를 갱신하세요.")
    return base


def resolve_all(clauses):
    """모든 규칙의 표준값을 한 번에 도출. {rule_id: 결과} 반환."""
    return {rid: resolve_standard_value(rid, clauses) for rid in SPECS}
