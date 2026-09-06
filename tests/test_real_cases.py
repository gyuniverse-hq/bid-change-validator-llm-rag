# -*- coding: utf-8 -*-
"""실제 공고 라벨·평가 테스트.

원본 첨부(data/attachments/)는 .gitignore 대상이라 다른 사람 환경에는 없다.
그때 평가가 **조용히 통과하지 않고** "평가 불가"로 보고하는지가 핵심이다 —
안 돌린 평가가 통과로 보이면 성능 수치를 믿을 수 없게 된다.
"""
import json

import pytest

from goldenset.real_cases import (
    _eval_open_ended,
    _eval_standard_rules,
    _locate_rfp,
    evaluate_real,
    load_real_labels,
)


@pytest.fixture(scope="module")
def labels():
    return load_real_labels()


def test_라벨_파일이_있고_구조가_갖춰져_있다(labels):
    assert labels, "data/goldenset/real/ 에 라벨이 없습니다"
    for label in labels:
        assert label["kind"] == "real"
        src = label["source"]
        assert src["bid_ntce_no"] and src["rfp_file_name"]
        assert len(src["rfp_sha256"]) == 64, "문서 동일성 확인용 sha256이 필요하다"
        assert label["standard_rules"], "확인 필요 조항 라벨이 비어 있음"
        assert label["open_ended_scope"]["must"], "포괄조항 라벨이 비어 있음"


def test_라벨은_원본_없이도_검토할_수_있게_근거_원문을_담는다(labels):
    """원본이 .gitignore 대상이므로, 라벨만 보고도 판단 근거를 알 수 있어야 한다."""
    for label in labels:
        for rule in label["standard_rules"]:
            if rule["expected_verdict"] == "없음":
                assert rule["rationale"], "'없음' 판정도 이유가 적혀 있어야 한다"
                continue
            assert rule["evidence"], f"{rule['rule_id']}: 근거 원문이 비어 있음"
            for q in rule["evidence"]:
                assert len(q) > 10
        for item in label["open_ended_scope"]["must"]:
            assert item["quote"] and item["why"]


def test_원본이_없으면_통과가_아니라_평가불가로_보고한다(tmp_path, labels):
    fake = json.loads(json.dumps(labels[0]))
    fake["source"]["bid_ntce_no"] = "NO_SUCH_BID_20991231"
    path, status, note = _locate_rfp(fake)
    assert status == "missing"
    assert path is None
    assert "analyze --bid-no" in note, "다음에 뭘 해야 하는지 알려줘야 한다"


def test_문서가_바뀌면_해시_불일치로_잡아낸다(labels, monkeypatch):
    """정정공고로 첨부가 바뀌면 옛 라벨로 채점하면 안 된다."""
    import goldenset.real_cases as rc

    label = json.loads(json.dumps(labels[0]))
    monkeypatch.setattr(rc.Path, "exists", lambda self: True)
    monkeypatch.setattr(rc, "_sha256", lambda p: "0" * 64)
    path, status, note = rc._locate_rfp(label)
    assert status == "hash_mismatch"
    assert "정정" in note


def test_값이_우연히_맞아도_근거가_틀리면_오귀속으로_센다(labels):
    """검수 14일과 착수보고서 14일처럼 값이 같은 함정을 걸러내는지 본다."""
    label = [l for l in labels if l["case_id"] == "R26BK01705963_v1"][0]
    trap = [r for r in label["standard_rules"]
            if r["rule_id"] == "inspection_period"][0]["traps"][0]["quote"]

    findings = [{
        "rule_id": "inspection_period", "verdict": "적합",
        "rfp_excerpt": trap, "matched_text": None, "rfp_value": {"raw": "14일 이내"},
    }]
    rows = _eval_standard_rules(label, findings)
    row = [r for r in rows if r["rule_id"] == "inspection_period"][0]
    assert row["verdict_ok"] is True, "판정 자체는 기대와 같다"
    assert row["location"] == "오귀속", "근거가 틀렸으면 위치 오답이어야 한다"


def test_라벨한_근거를_집으면_위치_정답이다(labels):
    label = [l for l in labels if l["case_id"] == "R26BK01705963_v1"][0]
    ev = [r for r in label["standard_rules"]
          if r["rule_id"] == "inspection_period"][0]["evidence"][0]
    findings = [{"rule_id": "inspection_period", "verdict": "적합",
                 "rfp_excerpt": ev, "matched_text": None, "rfp_value": None}]
    row = [r for r in _eval_standard_rules(label, findings)
           if r["rule_id"] == "inspection_period"][0]
    assert row["location"] == "정답"


def test_없는_조항을_확인필요로_보고하면_오탐으로_센다(labels):
    label = [l for l in labels if l["case_id"] == "R26BK01705963_v1"][0]
    findings = [{"rule_id": "penalty_cap", "verdict": "확인 필요",
                 "rfp_excerpt": "아무 문장", "matched_text": None, "rfp_value": None}]
    row = [r for r in _eval_standard_rules(label, findings)
           if r["rule_id"] == "penalty_cap"][0]
    assert row["verdict_ok"] is False
    assert "오탐" in row["notes"][0]


def test_포괄조항_함정_문장을_잡으면_오탐으로_분류된다(labels):
    label = [l for l in labels if l["case_id"] == "R26BK01705963_v1"][0]
    trap = label["open_ended_scope"]["traps"][0]["quote"]
    findings = [{"matched_text": trap[:40], "rfp_clause_label": "9",
                 "rfp_excerpt": trap}]
    out = _eval_open_ended(label, findings)
    assert len(out["trap_false_positives"]) == 1
    assert out["must_hit"] == 0


def test_라벨한_포괄조항을_잡으면_재현율에_반영된다(labels):
    label = [l for l in labels if l["case_id"] == "R26BK01705963_v1"][0]
    must = label["open_ended_scope"]["must"]
    findings = [{"matched_text": m["quote"][:40], "rfp_clause_label": None,
                 "rfp_excerpt": m["quote"]} for m in must]
    out = _eval_open_ended(label, findings)
    assert out["must_hit"] == out["must_total"]
    assert out["recall"] == 1.0
    assert not out["trap_false_positives"]
    assert not out["unlabeled_detections"]


def test_evaluate_real은_원본이_없어도_예외를_던지지_않는다(monkeypatch, tmp_path):
    import goldenset.real_cases as rc

    monkeypatch.setattr(rc, "_locate_rfp",
                        lambda label: (None, "missing", "원본 없음(테스트)"))
    # 실제 평가 결과 파일을 덮어쓰지 않도록 임시 경로로 저장한다
    out = evaluate_real(verbose=False, out_path=tmp_path / "eval_result.json")
    assert out["cases"] >= 1
    assert all(r["source_status"] == "missing" for r in out["results"])
    assert all("standard_rules" not in r for r in out["results"]), \
        "평가하지 않았는데 점수가 있으면 안 된다"
