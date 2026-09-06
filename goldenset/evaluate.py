# -*- coding: utf-8 -*-
"""골든셋 검증 — 파이프라인 전체를 태워 재현율·정밀도 측정.

- 채점 기준: "확인 필요 있음/없음"만이 아니라 **근거 위치**까지.
  시스템이 짚은 조항 라벨이 결함을 심은 바로 그 조항이어야 정탐(TP)이다.
- **기본 표현(p0)과 held-out 표현(p1~p3)을 분리 보고**한다.
  p0만 높고 held-out이 낮으면 규칙이 형식이 아니라 문장을 외운 것이다.
- Sol은 채점에 관여하지 않는다.
"""
import json
from pathlib import Path

from detect import chunk_rfp, detect_patterns, detect_standard_diff
from standards import build_clauses

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "goldenset"
_NON_CASE_FILES = ("index.json", "eval_result.json", "eval_slots_result.json")


def _load_cases():
    cases = []
    for f in sorted(GOLDEN_DIR.glob("*.json")):
        if f.name in _NON_CASE_FILES:
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if "text" in data:  # 케이스 파일만 (평가 산출물 등 배제)
            cases.append(data)
    return cases


def _predict(text, clauses):
    chunks = chunk_rfp(text)
    findings = detect_standard_diff(chunks, clauses) + detect_patterns(chunks)
    return [f for f in findings if f["verdict"] == "확인 필요"]


def _label_match(predicted_label, expected_label):
    if predicted_label is None or expected_label is None:
        return False
    return predicted_label.strip() == expected_label.strip()


class _Bucket:
    def __init__(self):
        self.tp = self.fp = self.fn = self.tp_loc = 0

    def metrics(self):
        rec = self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0
        pre = self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0
        loc = self.tp_loc / (self.tp + self.fn) if (self.tp + self.fn) else 0.0
        return rec, pre, loc


def evaluate_goldenset(verbose=True):
    clauses = build_clauses()
    cases = _load_cases()
    if not cases:
        raise RuntimeError("골든셋 없음 — 먼저 `python main.py goldenset-build` 실행")

    overall = _Bucket()
    base_b = _Bucket()      # p0 — 규칙 작성에 참고한 표현
    held_b = _Bucket()      # p1~p3 — held-out 표현
    per_type = {}
    misses = []

    for case in cases:
        preds = _predict(case["text"], clauses)
        held = case.get("held_out", False)
        bucket = held_b if held else base_b

        if case["kind"] == "defect":
            dt = case["defect_type"]
            ph = case.get("phrasing", "p0")
            per_type.setdefault(dt, {})
            hit = [p for p in preds if p["rule_id"] == dt]
            if hit:
                overall.tp += 1
                bucket.tp += 1
                loc_ok = any(_label_match(p.get("rfp_clause_label"),
                                          case["expected_clause_label"]) for p in hit)
                if loc_ok:
                    overall.tp_loc += 1
                    bucket.tp_loc += 1
                per_type[dt][ph] = "O" if loc_ok else "O(위치X)"
            else:
                overall.fn += 1
                bucket.fn += 1
                per_type[dt][ph] = "X"
                misses.append((case["case_id"],
                               f"FN — 놓침 [{case.get('phrasing_note', '')}]"))
            extra = [p for p in preds if p["rule_id"] != dt]
            overall.fp += len(extra)
            bucket.fp += len(extra)
            for p in extra:
                misses.append((case["case_id"], f"FP — {p['rule_id']} (심지 않은 결함)"))
        else:  # clean — 없는 결함을 지어내지 않는가
            overall.fp += len(preds)
            bucket.fp += len(preds)
            for p in preds:
                misses.append((case["case_id"], f"FP — {p['rule_id']} (정상 문서)"))

    rec, pre, loc = overall.metrics()
    brec, bpre, bloc = base_b.metrics()
    hrec, hpre, hloc = held_b.metrics()

    result = {
        "cases": len(cases),
        "overall": {"tp": overall.tp, "fp": overall.fp, "fn": overall.fn,
                    "recall": round(rec, 4), "precision": round(pre, 4),
                    "recall_with_location": round(loc, 4)},
        "base_phrasing": {"tp": base_b.tp, "fp": base_b.fp, "fn": base_b.fn,
                          "recall": round(brec, 4), "precision": round(bpre, 4)},
        "held_out_phrasing": {"tp": held_b.tp, "fp": held_b.fp, "fn": held_b.fn,
                              "recall": round(hrec, 4), "precision": round(hpre, 4)},
        "per_type": per_type,
        "misses": misses,
    }
    (GOLDEN_DIR / "eval_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if verbose:
        print(f"골든셋 평가 — {len(cases)}건")
        print(f"  [전체]        재현율 {rec:>6.1%} | 정밀도 {pre:>6.1%} | "
              f"근거위치까지 {loc:>6.1%}  (TP {overall.tp} / FP {overall.fp} / FN {overall.fn})")
        print(f"  [기본 p0]     재현율 {brec:>6.1%} | 정밀도 {bpre:>6.1%}  "
              f"← 규칙 작성에 참고한 표현")
        print(f"  [held-out]    재현율 {hrec:>6.1%} | 정밀도 {hpre:>6.1%}  "
              f"← 처음 보는 표현 (일반화 성능)")
        print("\n  유형별 표현 대응 (O=탐지, X=놓침):")
        phrasing_ids = ["p0", "p1", "p2", "p3"]
        print(f"    {'유형':<24}" + "".join(f"{p:>10}" for p in phrasing_ids))
        for dt, m in per_type.items():
            print(f"    {dt:<24}" + "".join(f"{m.get(p, '-'):>10}" for p in phrasing_ids))
        if misses:
            print(f"\n  실패 {len(misses)}건:")
            for cid, msg in misses[:25]:
                print(f"    {cid}: {msg}")
    return result
