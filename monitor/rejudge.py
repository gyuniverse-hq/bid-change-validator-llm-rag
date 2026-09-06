# -*- coding: utf-8 -*-
"""변경된 조항만 재판정하고 3-상태(신규발생 | 유지 | 해소됨)를 산출.

전체 재분석 금지 — 변경(changed=True) 또는 신설된 청크에 대해서만 탐지를 다시 돌리고,
변경 없는 청크의 기존 finding은 그대로 유지로 넘긴다.

확인 필요 조항(경로 A/B)뿐 아니라 **참가자격 요건(6단계)도 재비교**한다.
정정공고에서 "실적 5억원 이상"이 "실적 8억원 이상"으로 바뀌는 것처럼, 확인 필요
조항 규칙 6종에 안 걸리는 변경도 참가자격 판정에는 영향을 준다.
"""
import re

from detect import detect_patterns, detect_standard_diff


def _finding_key(f):
    return (f.get("rule_id"), f.get("rfp_chunk_id"))


def rejudge_changed(old_chunks, new_chunks, alignment, old_findings, clauses):
    """변경/신설 청크만 재탐지. (new_findings_on_changed, changed_new_ids) 반환."""
    changed_new_ids = {p["new_id"] for p in alignment["pairs"] if p["changed"]}
    changed_new_ids |= set(alignment["added_new_ids"])
    target = [c for c in new_chunks if c["chunk_id"] in changed_new_ids]
    if not target:
        return [], changed_new_ids
    findings = detect_standard_diff(target, clauses) + detect_patterns(target)
    return findings, changed_new_ids


def diff_findings(old_findings, new_findings, alignment, changed_new_ids):
    """3-상태 산출.

    반환: [{"state": "신규발생"|"유지"|"해소됨", "finding": {...}}]
    """
    old_to_new = {p["old_id"]: p["new_id"] for p in alignment["pairs"]}
    new_by_key = {}
    for f in new_findings:
        new_by_key.setdefault((f["rule_id"], f.get("rfp_chunk_id")), f)

    results = []
    consumed_new = set()

    for of in old_findings:
        if of.get("verdict") == "적합":
            continue
        oid = of.get("rfp_chunk_id")
        nid = old_to_new.get(oid)
        if nid is None:
            results.append({"state": "해소됨", "finding": of,
                            "note": "해당 조항이 v2에서 삭제됨"})
            continue
        if nid not in changed_new_ids:
            # 조항 내용 불변 — 기존 판정 유지 (재분석 금지)
            results.append({"state": "유지", "finding": of})
            continue
        nf = new_by_key.get((of["rule_id"], nid))
        if nf and nf["verdict"] != "적합":
            consumed_new.add((nf["rule_id"], nf.get("rfp_chunk_id")))
            results.append({"state": "유지", "finding": nf,
                            "note": "조항 문언 변경됐으나 확인 필요 상태 지속"})
        else:
            results.append({"state": "해소됨", "finding": of,
                            "note": "v2에서 표준 부합으로 수정됨"})

    for nf in new_findings:
        if nf.get("verdict") == "적합":
            continue
        key = (nf["rule_id"], nf.get("rfp_chunk_id"))
        if key in consumed_new:
            continue
        # 기존에 같은 rule이 다른(정렬된) 청크에 있었는지 확인
        already = any(r["state"] == "유지" and r["finding"].get("rule_id") == nf["rule_id"]
                      and r["finding"].get("rfp_chunk_id") == nf.get("rfp_chunk_id")
                      for r in results)
        if not already:
            results.append({"state": "신규발생", "finding": nf})
    return results


def _squash(s):
    return re.sub(r"\s+", "", s or "")


# align_chunks와 같은 문턱(0.60) — 같은 요건을 같은 요건으로 인식하는 데
# 그쪽에서 이미 검증된 값이라 여기서도 그대로 쓴다.
_SLOT_MATCH_THRESHOLD = 0.60


def diff_eligibility_slots(old_slots, new_slots):
    """참가자격 슬롯(6단계) v1↔v2 비교. align_chunks와 같은 이유로 **조항 번호가
    아니라 원문 임베딩 유사도**로 대응시킨다 — 정정으로 조항 순서가 밀려도
    같은 요건은 같은 요건으로 인식해야 한다.

    반환: [{"state": "신규발생"|"유지"|"변경됨"|"해소됨", "old": slot|None, "new": slot|None}]
    유형(실적요건/인증요건/...)이 다르면 애초에 같은 요건으로 보지 않는다.
    """
    if not old_slots and not new_slots:
        return []
    if not old_slots:
        return [{"state": "신규발생", "old": None, "new": s} for s in new_slots]
    if not new_slots:
        return [{"state": "해소됨", "old": s, "new": None} for s in old_slots]

    from llm.embeddings import similarity_matrix

    try:
        matrix, _method = similarity_matrix(
            [s.get("raw", "") for s in old_slots],
            [s.get("raw", "") for s in new_slots])
    except Exception:
        matrix = None

    used_new = set()
    results = []
    for i, old in enumerate(old_slots):
        best_j, best_sim = None, -1.0
        if matrix:
            for j, new in enumerate(new_slots):
                if j in used_new or new.get("유형") != old.get("유형"):
                    continue
                sim = matrix[i][j]
                if sim > best_sim:
                    best_sim, best_j = sim, j
        if best_j is not None and best_sim >= _SLOT_MATCH_THRESHOLD:
            used_new.add(best_j)
            new = new_slots[best_j]
            if _squash(old.get("raw")) == _squash(new.get("raw")):
                results.append({"state": "유지", "old": old, "new": new})
            else:
                results.append({"state": "변경됨", "old": old, "new": new})
        else:
            results.append({"state": "해소됨", "old": old, "new": None})

    for j, new in enumerate(new_slots):
        if j not in used_new:
            results.append({"state": "신규발생", "old": None, "new": new})
    return results
