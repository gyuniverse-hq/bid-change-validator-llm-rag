# -*- coding: utf-8 -*-
"""골든셋 생성 — Sol(GPT-5.6 Sol, 개발 단계 1회성) 사용. 런타임 호출 금지.

생성 규칙 — Sol을 신뢰하지 않는다:
1. 핵심 사실 변경(수치·문언)은 **코드가 직접 조항 줄을 치환**한다.
   Sol에게는 "변경된 조항이 자연스럽게 읽히도록 앞뒤 문장만 다듬어달라"는 좁은 역할만.
2. 생성 후 정규식 체커로 자동 검증 — 의도한 숫자·키워드가 실제로 남아있는지 확인.
   통과 못 하면 골든셋에서 자동 제외 후 재생성(코드 치환 원본으로 폴백).
3. 정상 문서를 동수로 섞는다 — 변형본만 넣으면 "전부 확인 필요"라고 우겨도
   재현율 100%가 나온다. 정상 문서는 정밀도를 잰다.
4. 결함 유형마다 **표현 4종(p0 기본 + p1~p3 held-out)** 을 생성한다.
   p0만 맞히면 규칙이 문장을 외운 것이므로, 평가에서 분리 보고한다.
"""
import json
import re
from pathlib import Path

from llm import get_client

from .templates import (
    CLEAN_TEMPLATES,
    DEFECT_PHRASINGS,
    EXPECTED_LABELS,
    PROJECTS,
    clean_doc,
    inject_defect,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = ROOT / "data" / "goldenset"


def _smooth_with_sol(text, use_llm):
    """Sol의 좁은 역할: 치환된 조항 주변 문장 다듬기. 실패/미사용 시 원본 유지."""
    if not use_llm:
        return text, "code_only"
    client = get_client("sol")
    if not client.available:
        return text, "code_only(키 없음)"
    try:
        out = client.chat(
            "다음 제안요청서 문서에서 어색한 연결 문장이 있으면 자연스럽게만 다듬어라. "
            "숫자, 기간, 비율, 귀속 주체, 조항 번호는 절대 바꾸지 마라. "
            "문서 전체를 그대로 출력하라. 설명 금지.",
            text)
        return out, "sol_smoothed"
    except Exception:
        return text, "code_only(호출 실패)"


def _clear_old_cases():
    for f in GOLDEN_DIR.glob("*.json"):
        if f.name in ("index.json", "eval_result.json", "eval_slots_result.json"):
            continue
        f.unlink()


def build_goldenset(use_llm=False):
    """유형 × 표현 4종의 변형 문서 + 동수의 정상 문서 생성."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    _clear_old_cases()

    cases = []
    skipped = []
    combo = 0  # 결함 문서가 서로 다른 정상 문서 위에 얹히도록 순환

    for defect_id, spec in DEFECT_PHRASINGS.items():
        for phrasing in spec["phrasings"]:
            tpl_idx, proj_idx = combo % len(CLEAN_TEMPLATES), combo % len(PROJECTS)
            combo += 1
            tpl_name, base = clean_doc(tpl_idx, proj_idx)

            mutated = inject_defect(base, defect_id, phrasing)  # 코드가 직접 치환
            if mutated is None:
                skipped.append(f"{defect_id}/{phrasing['id']}: 주입 대상 조항 없음")
                continue

            mutated, method = _smooth_with_sol(mutated, use_llm)
            # 정규식 체커 — 주입한 결함이 결과물에 실제로 남아있는가
            if not re.search(phrasing["checker"], mutated):
                mutated = inject_defect(base, defect_id, phrasing)  # 코드 치환본 폴백
                method = "code_only(체커 실패로 폴백)"
                if not re.search(phrasing["checker"], mutated):
                    skipped.append(f"{defect_id}/{phrasing['id']}: 체커 불통과 — 제외")
                    continue

            case = {
                "case_id": f"defect_{defect_id}_{phrasing['id']}",
                "kind": "defect",
                "defect_type": defect_id,
                "phrasing": phrasing["id"],
                "phrasing_note": phrasing["note"],
                "held_out": phrasing["id"] != "p0",
                "expected_clause_label": EXPECTED_LABELS[defect_id],
                "base_template": tpl_name,
                "generation_method": method,
                "project": PROJECTS[proj_idx][0],
                "text": mutated,
            }
            (GOLDEN_DIR / f"{case['case_id']}.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
            cases.append(case)

    # 정상 문서 — 결함 문서와 동수. 두 표기(base/paraphrase)를 모두 포함한다.
    n_clean = len(cases)
    for i in range(n_clean):
        tpl_idx = i % len(CLEAN_TEMPLATES)
        proj_idx = i // len(CLEAN_TEMPLATES)
        tpl_name, text = clean_doc(tpl_idx, proj_idx)
        case = {
            "case_id": f"clean_{tpl_name}_{proj_idx}",
            "kind": "clean",
            "defect_type": None,
            "phrasing": tpl_name,
            "held_out": tpl_name != "base",
            "expected_clause_label": None,
            "base_template": tpl_name,
            "generation_method": "template",
            "project": PROJECTS[proj_idx % len(PROJECTS)][0],
            "text": text,
        }
        (GOLDEN_DIR / f"{case['case_id']}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        cases.append(case)

    index = {
        "total": len(cases),
        "defect": sum(1 for c in cases if c["kind"] == "defect"),
        "clean": sum(1 for c in cases if c["kind"] == "clean"),
        "held_out": sum(1 for c in cases if c["held_out"]),
        "skipped": skipped,
        "case_ids": [c["case_id"] for c in cases],
    }
    (GOLDEN_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return cases
