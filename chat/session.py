# -*- coding: utf-8 -*-
"""되묻기 대화 세션 (터미널 REPL).

흐름: 분석 → 판정 보류 항목마다 질문 → 담당자가 자연어로 답변
      → Luna가 정형 필드로 변환 → 코드가 검증·정규화 → 코드가 재판정

LLM은 질문 생성과 답변 해석에만 개입한다. 충족/미충족 판정은 끝까지 코드가 한다.
"""
import json
import sys
from pathlib import Path

from detect import chunk_rfp, detect_patterns, detect_standard_diff
from eligibility import extract_slots, judge_api_fields, judge_slots, load_profile
from parsers import parse_document
from report import render_report
from standards import build_clauses

from .answer_parser import apply_updates, parse_answer

HELP = """
명령: /skip 이 질문 건너뛰기   /report 현재 판정 다시 보기
      /save [경로] 프로필 저장   /help 도움말   /quit 종료
그 외 입력은 답변으로 처리합니다. "모르겠다"고 답하면 판정 보류가 유지됩니다.
""".strip()


def _read(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "/quit"


def _save_profile(profile, path):
    clean = {k: v for k, v in profile.items() if not k.startswith("_")}
    Path(path).write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return path


def run_chat(bid_no=None, file=None, profile_path=None, title=None,
             save_profile=None):
    profile = load_profile(profile_path)
    if profile is None:
        print("회사 프로필을 찾을 수 없습니다. --profile 로 지정하세요.", file=sys.stderr)
        return 1

    # ── 1. 공고 확보 및 분석 ────────────────────────────────────────────
    item = None
    if bid_no:
        from collectors import download_attachments, fetch_bid_by_no
        res = fetch_bid_by_no(bid_no)
        if not res["items"]:
            print(f"공고 {bid_no} 조회 결과 없음", file=sys.stderr)
            return 1
        item = max(res["items"], key=lambda x: int(x.get("bidNtceOrd") or 0))
        title = title or item.get("bidNtceNm", bid_no)
        manifest = download_attachments(item, version="v1")
        if not manifest["rfp_file"]:
            print("RFP 첨부를 찾지 못함 — 확인 불가", file=sys.stderr)
            return 1
        parsed = parse_document(manifest["rfp_file"])
    else:
        parsed = parse_document(file)
        title = title or str(file)

    if parsed["parse_status"] == "failed":
        print(f"[파싱 실패] {parsed['parse_notes']}\n확인 불가 — 담당자 확인 필요")
        return 2

    clauses = build_clauses()
    chunks = chunk_rfp(parsed["full_text"])
    findings = detect_standard_diff(chunks, clauses) + detect_patterns(chunks)

    extra_notes = []
    if parsed["parse_status"] == "partial":
        extra_notes.append(f"파서 경고 — {parsed['parse_notes']}")

    slot_out = extract_slots(chunks)
    if slot_out["status"] != "ok":
        print(f"자격요건 슬롯 추출 불가({slot_out['notes']}) — 대화를 진행할 수 없습니다.")
        return 2
    slots = slot_out["slots"]
    if slot_out["notes"]:
        extra_notes.append(f"슬롯 추출 참고 — {slot_out['notes']}")

    demo = bool(profile.get("_demo"))

    def show_report():
        api_results = judge_api_fields(item, profile) if item else []
        results = judge_slots(slots, profile)
        print(render_report(title, api_results, results, findings,
                            extra_notes, demo=demo))
        return results

    print()
    results = show_report()

    # ── 2. 되묻기 대화 ──────────────────────────────────────────────────
    pending = [r for r in results if r.get("되묻기")]
    if not pending:
        print("\n판정 보류 항목이 없습니다. 대화를 종료합니다.")
        return 0

    print("\n" + "=" * 72)
    print(f"■ 확인이 필요한 항목이 {len(pending)}건 있습니다. 하나씩 여쭙겠습니다.")
    print(HELP)
    print("=" * 72)

    answered = 0
    for idx, r in enumerate(pending, 1):
        slot = r["slot"]
        print(f"\n[{idx}/{len(pending)}] 요건: {(slot.get('raw') or '')[:70]}")
        print(f"  Q. {r['되묻기']}")

        while True:
            ans = _read("  > ")
            if not ans:
                continue
            if ans in ("/quit", "/q"):
                print("\n대화를 종료합니다.")
                _finish(profile, save_profile, show_report, answered)
                return 0
            if ans in ("/help", "/h"):
                print(HELP)
                continue
            if ans in ("/skip", "/s"):
                print("  → 건너뜁니다. 판정 보류가 유지됩니다.")
                break
            if ans == "/report":
                show_report()
                continue
            if ans.startswith("/save"):
                parts = ans.split(maxsplit=1)
                path = parts[1] if len(parts) > 1 else save_profile
                if not path:
                    print("  저장 경로를 지정하세요: /save <경로>")
                else:
                    print(f"  → 저장 완료: {_save_profile(profile, path)}")
                continue

            # 자연어 답변 → Luna가 정형화, 코드가 검증·정규화
            parsed_ans = parse_answer(slot, r["되묻기"], ans)
            atype = parsed_ans["answer_type"]

            for rej in parsed_ans["rejected"]:
                print(f"  ⚠ 폐기: {rej}")

            if atype in ("llm_unavailable", "failed"):
                print(f"  → 답변 해석 실패({parsed_ans['notes']}) — 판정 보류 유지")
                break
            if atype == "모름":
                print("  → '확인 필요'로 접수했습니다. 판정 보류가 유지됩니다.")
                break
            if atype == "무관":
                print("  → 질문과 관련된 답변으로 보이지 않습니다. 다시 답해 주세요. "
                      "(건너뛰려면 /skip)")
                continue
            if not parsed_ans["updates"]:
                print("  → 반영할 값을 찾지 못했습니다. 수치를 포함해 다시 답해 주세요. "
                      "(건너뛰려면 /skip)")
                continue

            profile = apply_updates(profile, parsed_ans["updates"])
            answered += 1
            # 이 항목만 즉시 재판정 (판정은 코드)
            after = judge_slots([slot], profile)[0]
            print(f"  → 반영: {_fmt_updates(parsed_ans['updates'])}")
            print(f"  → 재판정: {r['verdict']} → {after['verdict']}  ({after['근거']})")
            break

    _finish(profile, save_profile, show_report, answered)
    return 0


def _fmt_updates(updates):
    parts = []
    for key, val in updates.items():
        if key == "실적":
            if val:
                amounts = ", ".join("{:,}원".format(p["계약금액"]) for p in val)
                parts.append(f"실적 {len(val)}건 추가 ({amounts})")
            else:
                parts.append("실적 없음으로 기록")
        elif key == "기술인력":
            parts.append(f"기술인력 {val}")
        elif isinstance(val, list):
            parts.append(f"{key} {val or '없음'}")
        else:
            parts.append(f"{key} {val}")
    return " / ".join(parts)


def _finish(profile, save_profile, show_report, answered):
    print("\n" + "=" * 72)
    print(f"■ 대화 종료 — 답변 {answered}건 반영 후 최종 판정")
    print("=" * 72 + "\n")
    show_report()
    if save_profile:
        print(f"\n갱신된 프로필 저장: {_save_profile(profile, save_profile)}")
    else:
        print("\n※ 프로필은 저장하지 않았습니다. "
              "저장하려면 --save-profile <경로> 로 실행하세요.")
