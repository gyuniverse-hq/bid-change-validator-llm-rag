# -*- coding: utf-8 -*-
"""Luna 슬롯추출 채점 — 6-2단계(RFP 본문 자격요건 정형화)의 품질 측정.

경로 A/B(탐지)는 순수 코드라 결정적이지만, 슬롯추출은 LLM이 개입하므로
모델·프롬프트가 바뀌면 흔들린다. 그래서 별도 채점 루프가 필요하다.

채점 항목 (goldenset/slot_cases.py의 라벨 기준):
  재현율        기대 요건 중 뽑아낸 비율
  정밀도        뽑은 슬롯 중 실제 요건인 비율 — **과잉 추출(환각) 검출**
  근거조항 정확도  LLM이 붙인 조항 번호가 실제 조항과 맞는 비율
  유형 정확도     실적/인력/인증/면허/지역 분류 정확도
  원문 보존 준수   금액·기간을 숫자로 바꾸지 않고 원문 문자열로 남겼는지
                 (스펙: 숫자 변환은 LLM이 아니라 normalize 모듈이 한다)

여러 번 돌리면 LLM 변동성이 보이므로 --repeat로 반복 측정할 수 있다.
Sol은 채점에 관여하지 않는다.
"""
import json
import re
from pathlib import Path

from eligibility.slots import extract_slots
from detect import chunk_rfp

from .slot_cases import CASES

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "goldenset"


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def _matches(expected, slot):
    """기대 요건이 이 슬롯에 담겼는가 — 핵심 문구 포함 여부로 판정."""
    return _squash(expected["key"]) in _squash(slot.get("raw", ""))


def _raw_preserved(slot):
    """금액·기간이 원문 문자열로 남았는가 (숫자만 들어있으면 LLM이 변환한 것)."""
    problems = []
    for field in ("금액_raw", "기간_raw"):
        val = slot.get(field)
        if not val:
            continue
        if re.fullmatch(r"[\d,\.\s]+", str(val)):
            problems.append(f"{field}='{val}' — 단위 없는 숫자만 (LLM이 변환함)")
    return problems


def evaluate_slots(repeat=1, verbose=True):
    total_expected = total_extracted = matched = 0
    ref_ok = ref_total = 0
    type_ok = type_total = 0
    raw_violations = []
    over_extractions = []
    misses = []
    per_case = []
    llm_status = None

    for _run in range(repeat):
        for case in CASES:
            chunks = chunk_rfp(case["text"])
            out = extract_slots(chunks)
            llm_status = out["status"]
            if out["status"] != "ok":
                return {"status": out["status"], "notes": out["notes"]}

            slots = out["slots"]
            expected = case["expected"]
            total_expected += len(expected)
            total_extracted += len(slots)

            used = set()
            case_missed = []
            for exp in expected:
                hit = None
                for i, slot in enumerate(slots):
                    if i in used:
                        continue
                    if _matches(exp, slot):
                        hit = (i, slot)
                        break
                if hit is None:
                    case_missed.append(exp["key"])
                    misses.append(f"{case['case_id']}: 놓침 — '{exp['key']}'")
                    continue
                i, slot = hit
                used.add(i)
                matched += 1

                ref_total += 1
                got_ref = re.sub(r"^(?:조항|제)\s*", "", (slot.get("근거조항") or "")).rstrip(".)조항 ")
                if got_ref == exp["근거조항"]:
                    ref_ok += 1
                else:
                    misses.append(
                        f"{case['case_id']}: '{exp['key']}' 근거조항 오류 "
                        f"(기대 {exp['근거조항']} / 실제 {slot.get('근거조항')})")

                type_total += 1
                if slot.get("유형") == exp["유형"]:
                    type_ok += 1
                else:
                    misses.append(
                        f"{case['case_id']}: '{exp['key']}' 유형 오류 "
                        f"(기대 {exp['유형']} / 실제 {slot.get('유형')})")

                for field in ("금액_raw_contains", "기간_raw_contains"):
                    if field not in exp:
                        continue
                    target = "금액_raw" if field.startswith("금액") else "기간_raw"
                    if _squash(exp[field]) not in _squash(slot.get(target) or ""):
                        misses.append(
                            f"{case['case_id']}: '{exp['key']}' {target} 누락 "
                            f"(기대 '{exp[field]}' 포함 / 실제 '{slot.get(target)}')")

            for i, slot in enumerate(slots):
                if i not in used:
                    over_extractions.append(
                        f"{case['case_id']}: 과잉추출 — \"{(slot.get('raw') or '')[:50]}\"")
                for p in _raw_preserved(slot):
                    raw_violations.append(f"{case['case_id']}: {p}")

            per_case.append({
                "case_id": case["case_id"],
                "expected": len(expected),
                "extracted": len(slots),
                "matched": len(expected) - len(case_missed),
                "missed": case_missed,
            })

    recall = matched / total_expected if total_expected else 0.0
    precision = matched / total_extracted if total_extracted else (1.0 if not total_expected else 0.0)
    ref_acc = ref_ok / ref_total if ref_total else 0.0
    type_acc = type_ok / type_total if type_total else 0.0

    result = {
        "status": "ok",
        "runs": repeat,
        "expected": total_expected, "extracted": total_extracted, "matched": matched,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "reference_accuracy": round(ref_acc, 4),
        "type_accuracy": round(type_acc, 4),
        "over_extractions": over_extractions,
        "raw_preservation_violations": raw_violations,
        "misses": misses,
        "per_case": per_case,
    }
    (GOLDEN_DIR / "eval_slots_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if verbose:
        print(f"Luna 슬롯추출 평가 — 케이스 {len(CASES)}종 × {repeat}회 "
              f"(status={llm_status})")
        print(f"  재현율        {recall:>6.1%}  (기대 {total_expected}건 중 {matched}건 추출)")
        print(f"  정밀도        {precision:>6.1%}  (추출 {total_extracted}건 중 {matched}건이 실제 요건)")
        print(f"  근거조항 정확도 {ref_acc:>6.1%}")
        print(f"  유형 정확도    {type_acc:>6.1%}")
        print(f"  과잉추출      {len(over_extractions)}건  ← 없는 요건을 지어냈는가")
        print(f"  원문보존 위반  {len(raw_violations)}건  ← 숫자 변환을 LLM이 했는가")
        print("\n  케이스별:")
        for c in per_case:
            flag = "" if c["matched"] == c["expected"] else "  ⚠"
            print(f"    {c['case_id']:<18} 기대 {c['expected']} / 추출 {c['extracted']} "
                  f"/ 일치 {c['matched']}{flag}")
        if over_extractions:
            print("\n  과잉추출 상세:")
            for o in over_extractions[:15]:
                print(f"    {o}")
        if misses:
            print("\n  기타 실패:")
            for m in misses[:15]:
                print(f"    {m}")
        if raw_violations:
            print("\n  원문보존 위반:")
            for v in raw_violations[:10]:
                print(f"    {v}")
    return result
