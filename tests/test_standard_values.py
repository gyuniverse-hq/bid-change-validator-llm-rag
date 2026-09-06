# -*- coding: utf-8 -*-
"""표준값 도출 테스트.

핵심 계약 3가지를 지킨다:
1. 판정 기준 수치는 **예규 원문에서** 나온다 (코드 상수가 아니다).
2. 예규가 개정돼 값이 바뀌면 **조용히 넘어가지 않는다** (드리프트 감지).
3. 원문에서 값을 못 뽑으면 옛 숫자로 판정하지 않고 **"확인 불가"** 로 보류한다.
"""
import re

import pytest

from detect.standard_diff import RULES, detect_standard_diff
from standards import build_clauses
from standards.values import SPECS, resolve_all, resolve_standard_value


@pytest.fixture(scope="module")
def clauses():
    return build_clauses()


def test_모든_규칙이_예규_원문에서_표준값을_얻는다(clauses):
    resolved = resolve_all(clauses)
    assert set(resolved) == set(SPECS)
    for rule_id, std in resolved.items():
        assert std["status"] == "ok", f"{rule_id}: {std['notes']}"
        assert std["raw"], f"{rule_id}: 원문 근거 문자열이 비어 있음"


def test_추출값이_기록값과_일치한다_예규개정_감시선(clauses):
    """이 테스트가 깨지면 예규가 개정된 것이다.

    실패 시 할 일: 예규 원문을 확인하고 standards/values.py의 recorded를 새 값으로
    갱신한다. 코드가 판정에 쓰는 값은 이미 원문 값이므로 판정 자체는 옳지만,
    변경 사실을 사람이 인지해야 한다.
    """
    resolved = resolve_all(clauses)
    drifted = {rid: std["drift"] for rid, std in resolved.items() if std["drift"]}
    assert not drifted, f"예규 값이 바뀌었습니다: {drifted}"


def test_탐지규칙에_표준수치가_하드코딩되어_있지_않다():
    """RULES는 '어떤 조항인가'만 알아야 한다. '기준이 몇인가'는 예규가 정한다."""
    for rule in RULES:
        for banned in ("std_value", "std_desc", "std_ref", "std_source", "std_clause_no"):
            assert banned not in rule, f"{rule['id']}에 {banned}가 남아 있음"


def test_앵커가_깨지면_옛값으로_판정하지_않고_확인불가(clauses, monkeypatch):
    """예규 문언이 바뀌어 값 위치를 못 찾는 상황을 만든다."""
    monkeypatch.setitem(SPECS["warranty_period"], "anchor", r"(절대로_없는_문구_\d+)")
    std = resolve_standard_value("warranty_period", clauses)
    assert std["status"] == "anchor_failed"
    assert std["value"] is None, "표준값을 못 뽑았는데 값이 채워져 있으면 안 된다"

    # 하자보수 3년(표준 초과)이 적힌 문서라도, 기준을 모르면 판정하지 않는다
    chunks = [{"chunk_id": 0, "clause_label": "5.1",
               "text": "5.1 계약상대자는 인수 확인 후 3년간 무상으로 하자를 보수한다."}]
    findings = detect_standard_diff(chunks, clauses)
    wp = [f for f in findings if f["rule_id"] == "warranty_period"]
    assert len(wp) == 1
    assert wp[0]["verdict"] == "확인 불가"
    assert wp[0]["matched_via"] == "standard_unresolved"


def test_예규값이_바뀌면_원문값으로_판정하고_드리프트를_알린다(clauses):
    """개정된 예규(1년 -> 2년)를 흉내 낸 조문으로 판정 기준이 따라 움직이는지 본다."""
    fake = [c for c in clauses if not (c["source"] == "용역계약일반조건"
                                       and c["clause_no"] == "58조")]
    original = [c for c in clauses
                if c["source"] == "용역계약일반조건" and c["clause_no"] == "58조"][0]
    revised = dict(original)
    revised["text"] = re.sub(r"확인한 후 1년간", "확인한 후 2년간", original["text"])
    assert revised["text"] != original["text"]
    fake.append(revised)

    std = resolve_standard_value("warranty_period", fake)
    assert std["status"] == "ok"
    assert std["value"] == 24, "개정된 원문(2년)이 기준값이 되어야 한다"
    assert std["drift"] == {"recorded": 12, "extracted": 24}
    assert "개정" in std["notes"]

    # 하자보수 18개월은 옛 기준(12개월)이면 확인 필요, 새 기준(24개월)이면 적합
    chunks = [{"chunk_id": 0, "clause_label": "5.1",
               "text": "5.1 계약상대자는 인수 확인 후 18개월간 무상으로 하자를 보수한다."}]
    findings = detect_standard_diff(chunks, fake)
    wp = [f for f in findings if f["rule_id"] == "warranty_period"]
    assert wp and wp[0]["verdict"] == "적합", "판정 기준이 예규 원문을 따라가지 않았다"


def test_판정에_쓴_기준값의_원문_근거가_finding에_남는다(clauses):
    chunks = [{"chunk_id": 0, "clause_label": "5.1",
               "text": "5.1 계약상대자는 인수 확인 후 3년간 무상으로 하자를 보수한다."}]
    findings = detect_standard_diff(chunks, clauses)
    wp = [f for f in findings if f["rule_id"] == "warranty_period"][0]
    assert wp["verdict"] == "확인 필요"
    assert wp["standard"]["std_value"] == 12
    assert wp["standard"]["std_value_raw"] == "1년"
    assert wp["standard"]["clause_ref"] == "용역계약일반조건 제58조제1항"
