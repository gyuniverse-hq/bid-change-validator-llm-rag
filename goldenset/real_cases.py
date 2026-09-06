# -*- coding: utf-8 -*-
"""실제 공고 라벨 평가 — 합성 골든셋이 못 재는 것을 잰다.

`data/goldenset/*.json`(합성)은 우리가 쓴 문장이다. 규칙을 그 문장에 맞춰 넓히면
재현율이 100%가 되지만, 그건 "형식을 이해했다"가 아니라 "우리가 쓴 표현을 외웠다"
일 수 있다. held-out(p1~p3)도 결국 같은 사람이 같은 날 만든 변형이라 시간이
지나면 in-distribution이 된다.

이 모듈은 **우리가 쓰지 않은 실제 나라장터 공고**를 사람이 라벨링한 파일
(`data/goldenset/real/*.json`)로 같은 지표를 다시 잰다. 두 숫자가 벌어지면
합성 골든셋이 실제 성능을 대변하지 못한다는 뜻이다.

평가 항목:
  1. 확인 필요 조항 6종 — 판정(적합/확인 필요/없음)이 맞는가
  2. 근거 위치        — 맞는 문장을 근거로 삼았는가 (값이 우연히 맞는 경우를 걸러낸다)
  3. 오귀속(trap)     — 같은 어휘를 쓰지만 다른 주제인 문장을 근거로 삼지 않았는가
  4. 포괄조항         — 실제 문서의 포괄조항을 잡는가 / 법률 상용구를 오탐하지 않는가
  5. 참가자격 슬롯    — (--slots) 없는 요건을 지어내지 않는가

원본 첨부는 .gitignore 대상이라 저장소에 없다. 없으면 조용히 통과시키지 않고
"평가 불가"로 명확히 보고한다 — 안 돌린 평가를 통과한 것처럼 보이면 안 된다.
"""
import hashlib
import json
import re
from pathlib import Path

from detect import chunk_rfp, detect_patterns, detect_standard_diff
from parsers import parse_document
from standards import build_clauses

ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = ROOT / "data" / "goldenset" / "real"
ATTACH_DIR = ROOT / "data" / "attachments"


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def _contains(haystack, needle, head=60):
    """공백 차이를 무시한 부분 문자열 대조. 긴 인용은 앞부분만 본다
    (파서가 줄바꿈·공백을 다르게 넣어도 같은 문장으로 인식해야 한다)."""
    h, n = _squash(haystack), _squash(needle)[:head]
    return bool(n) and n in h


def load_real_labels():
    if not REAL_DIR.exists():
        return []
    out = []
    for p in sorted(REAL_DIR.glob("*.json")):
        if p.name.startswith("eval_"):
            continue
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _locate_rfp(label):
    """라벨이 가리키는 실제 첨부를 찾고 sha256으로 동일 문서인지 확인한다.

    반환 (path, status, note). status: "ok" | "missing" | "hash_mismatch"
    """
    src = label["source"]
    vdir = ATTACH_DIR / src["bid_ntce_no"] / src["version"]
    path = vdir / src["rfp_file_name"]
    if not path.exists():
        return None, "missing", (
            "원본 첨부 없음: {}\n"
            "      -> `python main.py analyze --bid-no {}` 로 먼저 내려받으세요."
        ).format(path, src["bid_ntce_no"])
    actual = _sha256(path)
    if actual != src["rfp_sha256"]:
        return path, "hash_mismatch", (
            "sha256 불일치 — 라벨을 만든 문서와 다른 파일입니다.\n"
            "      라벨: {}...  실제: {}...\n"
            "      -> 공고가 정정됐을 수 있습니다. 라벨을 다시 검토하세요."
        ).format(src["rfp_sha256"][:16], actual[:16])
    return path, "ok", ""


def _eval_standard_rules(label, findings):
    """확인 필요 조항 6종 채점."""
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f["rule_id"], []).append(f)

    rows = []
    for spec in label["standard_rules"]:
        rid = spec["rule_id"]
        expected = spec["expected_verdict"]
        got = by_rule.get(rid, [])
        row = {"rule_id": rid, "expected": expected, "got": None,
               "verdict_ok": False, "location": "n/a", "notes": []}

        if expected == "없음":
            if not got:
                row.update(got="(미보고)", verdict_ok=True)
            elif got[0]["verdict"] == "확인 필요":
                row["got"] = got[0]["verdict"]
                row["notes"].append("문서에 없는 조항을 확인 필요로 보고 — 오탐")
            else:
                # 적합/확인 불가 보고는 판정을 틀린 게 아니지만, 없는 조항에 대한
                # 보고이므로 잡음으로 따로 기록한다
                row.update(got=got[0]["verdict"], verdict_ok=True)
                row["notes"].append(
                    "문서에 없는 조항을 '{}'로 보고 — 잡음".format(got[0]["verdict"]))
            rows.append(row)
            continue

        if not got:
            row["got"] = "(미보고)"
            row["notes"].append("판정했어야 할 조항을 아예 보고하지 않음 — 미탐")
            rows.append(row)
            continue

        f = got[0]
        row["got"] = f["verdict"]
        row["verdict_ok"] = (f["verdict"] == expected)
        if not row["verdict_ok"]:
            row["notes"].append(
                "판정 불일치 (기대 {} / 실제 {})".format(expected, f["verdict"]))

        # 근거 위치 — 어떤 문장을 근거로 삼았는가
        blob = " ".join(str(f.get(k) or "") for k in ("rfp_excerpt", "matched_text"))
        if f.get("rfp_value"):
            blob += " " + str(f["rfp_value"].get("raw", ""))
        hit_ev = any(_contains(blob, q) for q in spec["evidence"])
        hit_trap = [t for t in spec.get("traps", []) if _contains(blob, t["quote"])]
        if hit_ev:
            row["location"] = "정답"
        elif hit_trap:
            row["location"] = "오귀속"
            row["notes"].append("근거 오귀속 — " + hit_trap[0]["why"])
        else:
            row["location"] = "불명"
            row["notes"].append(
                "라벨한 근거 문장이 보고된 근거에 없음 (보고된 근거: {}...)".format(
                    (f.get("rfp_excerpt") or "")[:70]))
        rows.append(row)
    return rows


def _eval_open_ended(label, pattern_findings):
    """포괄조항 채점 — matched_text가 라벨한 문장 안에 들어가는지로 본다.

    청크 단위로 보면 큰 청크에 라벨 문장이 우연히 같이 들어 있는 것만으로
    '잡았다'가 되어버린다. 실제로 그 문장을 집었는지 확인해야 한다.
    """
    spec = label["open_ended_scope"]
    must = spec["must"]
    optional = spec.get("optional", [])
    traps = spec.get("traps", [])

    def matched_in(quote):
        return [f for f in pattern_findings
                if _contains(quote, f.get("matched_text", ""), head=200)]

    hits = [{"quote": m["quote"], "hit": bool(matched_in(m["quote"]))} for m in must]
    opt_hits = [{"quote": m["quote"], "hit": bool(matched_in(m["quote"]))} for m in optional]

    labeled_quotes = [m["quote"] for m in must] + [m["quote"] for m in optional]
    trap_quotes = [t["quote"] for t in traps]

    trap_fp = []
    unlabeled = []
    for f in pattern_findings:
        mt = f.get("matched_text", "")
        if any(_contains(q, mt, head=200) for q in labeled_quotes):
            continue
        if any(_contains(q, mt, head=200) for q in trap_quotes):
            trap_fp.append(f)
            continue
        # 라벨에 없는 탐지 — 진짜 포괄조항일 수도, 오탐일 수도 있다.
        # 자동으로 오탐 처리하지 않고 사람 검토 대상으로 따로 뺀다.
        unlabeled.append(f)

    n_hit = sum(1 for h in hits if h["hit"])
    return {
        "must_total": len(must),
        "must_hit": n_hit,
        "recall": (n_hit / len(must)) if must else None,
        "must_detail": hits,
        "optional_hit": sum(1 for h in opt_hits if h["hit"]),
        "optional_total": len(optional),
        "trap_false_positives": [
            {"matched_text": f.get("matched_text"),
             "clause_label": f.get("rfp_clause_label")} for f in trap_fp],
        "unlabeled_detections": [
            {"matched_text": f.get("matched_text"),
             "clause_label": f.get("rfp_clause_label"),
             "excerpt": (f.get("rfp_excerpt") or "")[:100]} for f in unlabeled],
        "total_detections": len(pattern_findings),
    }


def _eval_slots(label, chunks):
    """참가자격 슬롯 채점 (Luna 호출)."""
    from eligibility import extract_slots

    out = extract_slots(chunks)
    if out["status"] != "ok":
        return {"status": out["status"], "notes": out.get("notes", "")}

    slots = out["slots"]
    spec = label["eligibility_slots"]
    found, missed = [], []
    for exp in spec["expected"]:
        hit = [s for s in slots if _squash(exp["key"]) in _squash(s.get("raw", ""))]
        (found if hit else missed).append(exp["key"])

    over = []
    for rule in spec.get("must_not_extract", []):
        for s in slots:
            if s.get("유형") != rule["유형"]:
                continue
            if rule.get("with_amount") and not s.get("금액_raw"):
                continue
            over.append({"유형": s.get("유형"),
                         "raw": (s.get("raw") or "")[:80],
                         "why": rule["why"]})

    accept_keys = [a["key"] for a in spec.get("acceptable_extra", [])] + \
                  [e["key"] for e in spec["expected"]]
    unlabeled = [(s.get("raw") or "")[:80] for s in slots
                 if not any(_squash(k) in _squash(s.get("raw", "")) for k in accept_keys)]

    return {
        "status": "ok",
        "extracted": len(slots),
        "expected_total": len(spec["expected"]),
        "expected_found": len(found),
        "recall": len(found) / len(spec["expected"]) if spec["expected"] else None,
        "missed": missed,
        "over_extraction": over,
        "unlabeled_slots": unlabeled,
    }


def evaluate_real(verbose=True, with_slots=False, out_path=None):
    """실제 공고 라벨 전체 평가. 결과 dict 반환 + eval_result.json 저장.

    out_path를 주면 그 경로에 저장한다 — 테스트가 실제 평가 결과를 덮어쓰지
    않게 하기 위한 것이다(안 돌린 평가 결과가 저장돼 있으면 안 된다).
    """
    labels = load_real_labels()
    if not labels:
        if verbose:
            print("실제 공고 라벨이 없습니다 (data/goldenset/real/).")
        return {"cases": 0, "results": []}

    clauses = build_clauses()
    results = []

    for label in labels:
        path, status, note = _locate_rfp(label)
        entry = {"case_id": label["case_id"], "source_status": status}
        if status != "ok":
            entry["note"] = note
            results.append(entry)
            if verbose:
                print("\n[{}] 평가 불가 — {}\n      {}".format(
                    label["case_id"], status, note))
            continue

        parsed = parse_document(path)
        if parsed["parse_status"] == "failed":
            entry["source_status"] = "parse_failed"
            entry["note"] = parsed["parse_notes"]
            results.append(entry)
            continue

        chunks = chunk_rfp(parsed["full_text"])
        std_findings = detect_standard_diff(chunks, clauses)
        pat_findings = detect_patterns(chunks)

        entry["standard_rules"] = _eval_standard_rules(label, std_findings)
        entry["open_ended_scope"] = _eval_open_ended(label, pat_findings)
        if with_slots:
            entry["eligibility_slots"] = _eval_slots(label, chunks)
        results.append(entry)

    out = {"cases": len(labels), "results": results}
    dest = Path(out_path) if out_path else (REAL_DIR / "eval_result.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if verbose:
        _print_report(out)
    return out


def _print_report(out):
    for entry in out["results"]:
        if entry["source_status"] != "ok":
            continue
        print("\n실제 공고 평가 — {}".format(entry["case_id"]))
        print("=" * 66)

        rows = entry["standard_rules"]
        ok = sum(1 for r in rows if r["verdict_ok"])
        judged = [r for r in rows if r["expected"] != "없음"]
        loc_ok = sum(1 for r in judged if r["location"] == "정답")
        print("\n■ 확인 필요 조항 6종 — 판정 정답 {}/{}, 근거 위치 정답 {}/{}".format(
            ok, len(rows), loc_ok, len(judged)))
        for r in rows:
            mark = "O" if r["verdict_ok"] else "X"
            print("  {} {:<24}기대={:<8} 실제={:<10} 근거위치={}".format(
                mark, r["rule_id"], r["expected"], str(r["got"]), r["location"]))
            for n in r["notes"]:
                print("      - " + n)

        oe = entry["open_ended_scope"]
        if oe["recall"] is None:
            print("\n■ 과업범위 포괄조항 — 라벨 없음")
        else:
            print("\n■ 과업범위 포괄조항 — 재현율 {:.1%} ({}/{})".format(
                oe["recall"], oe["must_hit"], oe["must_total"]))
        print("  경계 사례(optional) 탐지 {}/{} · 문서 전체 탐지 {}건".format(
            oe["optional_hit"], oe["optional_total"], oe["total_detections"]))
        for d in oe["must_detail"]:
            print("  {} {}...".format("O" if d["hit"] else "X", d["quote"][:60]))
        if oe["trap_false_positives"]:
            print("  [오탐] 함정 문장 {}건:".format(len(oe["trap_false_positives"])))
            for t in oe["trap_false_positives"]:
                print("      " + str(t["matched_text"]))
        if oe["unlabeled_detections"]:
            print("  [검토] 라벨에 없는 탐지 {}건:".format(len(oe["unlabeled_detections"])))
            for u in oe["unlabeled_detections"][:5]:
                print("      " + str(u["matched_text"]))

        slots = entry.get("eligibility_slots")
        if not slots:
            continue
        if slots["status"] != "ok":
            print("\n■ 참가자격 슬롯 — 평가 불가 ({}) {}".format(
                slots["status"], slots.get("notes", "")))
            continue
        print("\n■ 참가자격 슬롯 — 재현율 {:.1%} ({}/{}), 총 추출 {}건".format(
            slots["recall"], slots["expected_found"],
            slots["expected_total"], slots["extracted"]))
        if slots["missed"]:
            print("  놓친 요건: {}".format(slots["missed"]))
        if slots["over_extraction"]:
            print("  [과잉추출] {}건:".format(len(slots["over_extraction"])))
            for o in slots["over_extraction"]:
                print("      [{}] {}".format(o["유형"], o["raw"]))
                print("        - " + o["why"])
        else:
            print("  과잉추출 0건 — 없는 요건을 지어내지 않음")
        if slots["unlabeled_slots"]:
            print("  [검토] 라벨에 없는 슬롯 {}건:".format(len(slots["unlabeled_slots"])))
            for u in slots["unlabeled_slots"][:5]:
                print("      " + u)
