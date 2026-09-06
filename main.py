# -*- coding: utf-8 -*-
"""나라장터 RFP 자동 검토 프로토타입 — CLI.

사용 예:
  python main.py fetch --days 3 --keyword 시스템          # 최근 용역공고 목록
  python main.py analyze --bid-no 20240812345             # 공고번호로 전체 분석
  python main.py analyze --file path/to/rfp.hwp           # 로컬 RFP 파일 분석
  python main.py monitor --bid-no 20240812345             # 변경 감지 + 재판정
  python main.py goldenset-build [--llm]                  # 골든셋 생성 (Sol은 --llm일 때만)
  python main.py goldenset-eval                           # 재현율·정밀도 평가
"""
import argparse
import json
import sys
import time

from parsers import parse_document
from standards import build_clauses
from detect import chunk_rfp, detect_patterns, detect_standard_diff
from eligibility import extract_slots, judge_api_fields, judge_slots, load_profile
from report import render_report


def _analyze_text(full_text, title, item=None, profile=None, use_llm=True,
                  narrative=False, parse_notes=""):
    clauses = build_clauses()
    chunks = chunk_rfp(full_text)
    findings = detect_standard_diff(chunks, clauses) + detect_patterns(chunks)

    api_results = judge_api_fields(item, profile) if item else []
    slot_results = []
    unresolvable_extra = []
    if parse_notes:
        unresolvable_extra.append(f"파서 경고 — {parse_notes}")
    if use_llm:
        slot_out = extract_slots(chunks)
        if slot_out["status"] == "ok":
            slot_results = judge_slots(slot_out["slots"], profile)
            if slot_out["notes"]:
                unresolvable_extra.append(f"슬롯 추출 참고 — {slot_out['notes']}")
        else:
            unresolvable_extra.append(
                f"RFP 본문 자격요건 — 슬롯 추출 불가({slot_out['notes']}) — 담당자 확인 필요")
    else:
        unresolvable_extra.append("RFP 본문 자격요건 — LLM 미사용 모드로 추출 생략")

    # 프로필에 _demo 표시가 있으면 리포트에 데모 배너를 붙인다
    demo = bool(profile and profile.get("_demo"))
    report = render_report(title, api_results, slot_results, findings,
                           unresolvable_extra, narrative=narrative, demo=demo)
    return report, chunks, findings


def cmd_fetch(args):
    from collectors import fetch_service_bids
    end = time.strftime("%Y%m%d%H%M")
    bgn = time.strftime("%Y%m%d%H%M", time.localtime(time.time() - args.days * 86400))
    out = fetch_service_bids(bgn, end, rows=args.rows, keyword=args.keyword)
    print(f"총 {out['total']}건 (원본 저장: {out['raw_path']})")
    for it in out["items"]:
        print(f"  {it.get('bidNtceNo')}-{it.get('bidNtceOrd')} | "
              f"{it.get('bidNtceNm')} | {it.get('ntceInsttNm')} | "
              f"마감 {it.get('bidClseDt')}")


def cmd_analyze(args):
    profile = load_profile(args.profile)
    if profile and profile.get("_템플릿") and not args.profile:
        print("⚠ 기본 프로필(data/company_profile.json)은 예시 템플릿입니다. "
              "실제 회사 정보로 교체하거나 --profile 로 지정하세요.\n", file=sys.stderr)
    item = None
    title = None

    if args.bid_no:
        from collectors import download_attachments, fetch_bid_by_no
        res = fetch_bid_by_no(args.bid_no)
        if not res["items"]:
            print(f"공고 {args.bid_no} 조회 결과 없음", file=sys.stderr)
            sys.exit(1)
        item = max(res["items"], key=lambda x: int(x.get("bidNtceOrd") or 0))
        title = item.get("bidNtceNm", args.bid_no)
        manifest = download_attachments(item, version="v1")
        if not manifest["rfp_file"]:
            print("RFP 첨부를 찾지 못함 — 확인 불가", file=sys.stderr)
            sys.exit(1)
        print(f"RFP 선택: {manifest['rfp_file']} ({manifest['selection_method']})\n")
        parsed = parse_document(manifest["rfp_file"])
    else:
        parsed = parse_document(args.file)
        title = args.title or args.file

    if parsed["parse_status"] == "failed":
        print(f"[파싱 실패] {parsed['parse_notes']}")
        print("확인 불가 — 담당자 확인 필요 (임의 판정하지 않음)")
        sys.exit(2)

    report, chunks, findings = _analyze_text(
        parsed["full_text"], title, item=item, profile=profile,
        use_llm=not args.no_llm, narrative=args.narrative,
        parse_notes=parsed["parse_notes"] if parsed["parse_status"] == "partial" else "")
    print(report)

    if args.bid_no:
        from monitor.change import save_analysis
        save_analysis(args.bid_no, "v1", chunks, findings)


def cmd_monitor(args):
    from monitor import check_and_rejudge

    clauses = build_clauses()
    r = check_and_rejudge(args.bid_no, clauses)
    print(f"변경 확인: {r['kind']} (old={r['old_version']}, new={r['new_version']})")
    print(r["message"])
    if r["status"] != "updated":
        return

    print("\n재판정 결과 — 확인 필요 조항:")
    for s in r["finding_states"]:
        f = s["finding"]
        label = f.get("rfp_clause_label") or "?"
        note = f" ({s['note']})" if s.get("note") else ""
        print(f"  [{s['state']}] {label}항 {f['risk_type']}{note}")
    if not r["finding_states"]:
        print("  (변경 없음)")

    if r["slot_states"]:
        print("\n재판정 결과 — 참가자격 요건:")
        for s in r["slot_states"]:
            slot = s["new"] or s["old"]
            print(f"  [{s['state']}] {(slot.get('raw') or '')[:60]}")


def _run_watch_cycle():
    """감시 목록 1회 순회. 변경분 재판정 + 알림 기록까지 하고 감지 건수를 반환한다."""
    import time

    from monitor import append_notifications, check_and_rejudge, list_watched

    watched = list_watched()
    if not watched:
        print("감시 중인 공고가 없습니다. `python main.py watch-add --bid-no <번호>` 로 추가하세요.")
        return 0

    clauses = build_clauses()
    notifications = []
    changed_count = 0

    for entry in watched:
        bid_no = entry["bid_no"]
        label = entry.get("label", bid_no)
        print(f"\n[{bid_no}] {label} 확인 중...")
        try:
            r = check_and_rejudge(bid_no, clauses)
        except Exception as e:
            print(f"  오류: {e}")
            continue
        print(f"  {r['message']}")
        if r["status"] != "updated":
            continue

        real_findings = [s for s in r["finding_states"] if s["state"] != "유지"]
        real_slots = [s for s in r["slot_states"] if s["state"] != "유지"]
        if not real_findings and not real_slots:
            print("  문서가 바뀌었지만 확인 필요 조항·참가자격 요건에 실질적 변화 없음")
            continue

        changed_count += 1
        print(f"  ⚠ 변경 감지 — 확인 필요 조항 {len(real_findings)}건, "
              f"참가자격 요건 {len(real_slots)}건")
        for s in real_findings:
            f = s["finding"]
            print(f"    [{s['state']}] {f.get('rfp_clause_label')}항 {f['risk_type']}")
        for s in real_slots:
            slot = s["new"] or s["old"]
            print(f"    [자격요건-{s['state']}] {(slot.get('raw') or '')[:50]}")

        notifications.append({
            "id": f"{bid_no}-{int(time.time())}",
            "bid_no": bid_no, "label": label,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finding_changes": [
                {"state": s["state"], "clause_label": s["finding"].get("rfp_clause_label"),
                 "risk_type": s["finding"]["risk_type"]}
                for s in real_findings
            ],
            "slot_changes": [
                {"state": s["state"], "raw": (s["new"] or s["old"]).get("raw")}
                for s in real_slots
            ],
            "read": False,
        })

    if notifications:
        append_notifications(notifications)
        print(f"\n총 {changed_count}건의 공고에서 변경을 감지했습니다. "
              f"data/notifications.json에 기록했습니다.")
    else:
        print("\n변경된 공고 없음.")
    return changed_count


def cmd_watch(args):
    import time

    if not args.interval_hours:
        _run_watch_cycle()
        return

    # 파일/로그로 리다이렉트하면(스케줄러로 백그라운드 실행하는 경우가 많다)
    # 파이썬 stdout이 완전 버퍼링돼서, 이 루프처럼 오래 sleep하는 프로세스는
    # 종료 전까지 로그에 아무것도 안 찍힌다. 줄 단위로 강제 flush한다.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass  # 리다이렉트 불가능한 스트림 등 — 그냥 기본 동작으로 진행

    interval_sec = args.interval_hours * 3600
    print(f"반복 모드 시작 — {args.interval_hours}시간마다 감시 목록을 확인합니다. "
          f"(Ctrl+C로 종료)")
    try:
        while True:
            print(f"\n{'=' * 60}")
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 감시 사이클 시작")
            print("=" * 60)
            try:
                _run_watch_cycle()
            except Exception as e:
                print(f"이번 사이클 중 오류 발생(다음 주기에 재시도): {e}")
            next_at = time.strftime("%Y-%m-%d %H:%M:%S",
                                    time.localtime(time.time() + interval_sec))
            print(f"\n다음 확인 예정: {next_at}")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n반복 모드 종료 (Ctrl+C)")


def cmd_watch_add(args):
    from monitor import add_bid
    items = add_bid(args.bid_no, label=args.label)
    print(f"감시 목록에 추가: {args.bid_no}")
    print(f"현재 감시 중: {len(items)}건")


def cmd_watch_remove(args):
    from monitor import remove_bid
    items = remove_bid(args.bid_no)
    print(f"감시 목록에서 제거: {args.bid_no}")
    print(f"현재 감시 중: {len(items)}건")


def cmd_watch_list(args):
    from monitor import list_watched
    items = list_watched()
    if not items:
        print("감시 중인 공고가 없습니다.")
        return
    for it in items:
        print(f"  {it['bid_no']} — {it.get('label', it['bid_no'])} (추가일 {it.get('added_at', '?')})")


def cmd_serve(args):
    from pathlib import Path

    root = Path(__file__).resolve().parent
    print(f"로컬 데모 서버 시작 — 브라우저에서 http://127.0.0.1:{args.port} 열기")

    if args.reload:
        # uvicorn.run(reload=True)를 스크립트 안에서 직접 부르면 윈도우에서
        # 재시작 시 재-import 경로가 꼬여 새 코드가 안 붙는 경우가 있다
        # (multiprocessing spawn이 __main__을 다시 실행하면서 생기는 문제).
        # uvicorn 자체 CLI로 띄우면 이 재시작 경로가 정식으로 검증돼 있다.
        import subprocess
        import sys
        print("코드 변경 자동 반영(--reload) 켜짐 — server/*.py 저장 시 자동 재시작")
        print("(Ctrl+C로 종료)")
        cmd = [
            sys.executable, "-m", "uvicorn", "server.api:app",
            "--host", "127.0.0.1", "--port", str(args.port),
            "--reload", "--reload-dir", str(root),
        ]
        subprocess.run(cmd, cwd=str(root))
    else:
        import uvicorn
        print("(Ctrl+C로 종료)")
        uvicorn.run("server.api:app", host="127.0.0.1", port=args.port, reload=False)


def cmd_chat(args):
    from chat import run_chat
    code = run_chat(bid_no=args.bid_no, file=args.file, profile_path=args.profile,
                    title=args.title, save_profile=args.save_profile)
    if code:
        sys.exit(code)


def cmd_demo(args):
    """가상 공고 × 가상 회사 프로필로 판정·되묻기 흐름을 시연한다."""
    from demo.run_demo import run_demo
    run_demo(profile_name=args.profile_name, no_llm=args.no_llm,
             followup=not args.skip_followup)


def cmd_goldenset_build(args):
    from goldenset import build_goldenset
    cases = build_goldenset(use_llm=args.llm)
    n_def = sum(1 for c in cases if c["kind"] == "defect")
    n_cln = len(cases) - n_def
    print(f"골든셋 생성 완료: 변형 {n_def}건 + 정상 {n_cln}건 -> data/goldenset/")
    if not args.llm:
        print("(--llm 미지정: Sol 다듬기 없이 코드 치환본 그대로 저장)")


def cmd_goldenset_eval(args):
    from goldenset import evaluate_goldenset
    evaluate_goldenset(verbose=True)


def cmd_goldenset_eval_slots(args):
    from goldenset import evaluate_slots
    out = evaluate_slots(repeat=args.repeat, verbose=True)
    if out.get("status") != "ok":
        print(f"슬롯 평가 불가: {out.get('status')} — {out.get('notes')}")
        sys.exit(2)


def cmd_goldenset_eval_real(args):
    from goldenset import evaluate_real
    out = evaluate_real(verbose=True, with_slots=args.slots)
    if not out["cases"]:
        sys.exit(2)
    blocked = [r for r in out["results"] if r["source_status"] != "ok"]
    if blocked and len(blocked) == out["cases"]:
        sys.exit(2)   # 한 건도 평가하지 못함 — 통과한 것처럼 보이면 안 된다


def main():
    ap = argparse.ArgumentParser(description="나라장터 RFP 자동 검토 프로토타입")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="최근 용역 입찰공고 목록")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--rows", type=int, default=20)
    p.add_argument("--keyword", default=None)
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("analyze", help="공고/파일 분석")
    p.add_argument("--bid-no", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--profile", default=None)
    p.add_argument("--no-llm", action="store_true", help="LLM 호출 없이 코드 판정만")
    p.add_argument("--narrative", action="store_true", help="Luna 요약 서술 추가")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("monitor", help="공고 1건 변경 감지 + 변경분(확인필요조항·참가자격) 재판정")
    p.add_argument("--bid-no", required=True)
    p.set_defaults(fn=cmd_monitor)

    p = sub.add_parser("watch", help="감시 목록 전체를 확인 — 변경분 재판정 + data/notifications.json 기록")
    p.add_argument("--interval-hours", type=float, default=None,
                   help="지정하면 이 시간(시간 단위)마다 반복 실행 (예: 5, 24). 미지정 시 1회만 실행")
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("watch-add", help="감시 목록에 공고 추가")
    p.add_argument("--bid-no", required=True)
    p.add_argument("--label", default=None, help="목록에 표시할 이름 (기본: 공고번호)")
    p.set_defaults(fn=cmd_watch_add)

    p = sub.add_parser("watch-remove", help="감시 목록에서 공고 제거")
    p.add_argument("--bid-no", required=True)
    p.set_defaults(fn=cmd_watch_remove)

    p = sub.add_parser("watch-list", help="감시 목록 조회")
    p.set_defaults(fn=cmd_watch_list)

    p = sub.add_parser("serve", help="로컬 데모 서버 (브라우저 연결, 실제 파이프라인 호출)")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-reload", dest="reload", action="store_false",
                   help="코드 변경 자동 반영 끄기 (기본: 켜짐)")
    p.set_defaults(fn=cmd_serve, reload=True)

    p = sub.add_parser("chat", help="되묻기 대화 (자연어 답변 → LLM 정형화 → 코드 재판정)")
    p.add_argument("--bid-no", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--profile", default=None)
    p.add_argument("--save-profile", default=None,
                   help="대화로 갱신된 프로필을 저장할 경로")
    p.set_defaults(fn=cmd_chat)

    p = sub.add_parser("demo", help="가상 공고 × 가상 업체로 판정·되묻기 시연 (demo/)")
    p.add_argument("--profile-name", default=None,
                   help="특정 데모 프로필만 실행 (적격업체 / 실적부족업체 / 정보부족업체)")
    p.add_argument("--no-llm", action="store_true", help="LLM 없이 코드 판정만")
    p.add_argument("--skip-followup", action="store_true",
                   help="되묻기 답변 시뮬레이션 생략")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("goldenset-build", help="골든셋 생성 (Sol)")
    p.add_argument("--llm", action="store_true", help="Sol로 문장 다듬기 (기본: 코드 치환만)")
    p.set_defaults(fn=cmd_goldenset_build)

    p = sub.add_parser("goldenset-eval", help="탐지 규칙 평가 (재현율·정밀도, 코드 판정)")
    p.set_defaults(fn=cmd_goldenset_eval)

    p = sub.add_parser("goldenset-eval-slots",
                       help="Luna 슬롯추출 평가 (재현율·과잉추출·근거조항)")
    p.add_argument("--repeat", type=int, default=1,
                   help="반복 횟수 — LLM 변동성 측정")
    p.set_defaults(fn=cmd_goldenset_eval_slots)

    p = sub.add_parser("goldenset-eval-real",
                       help="실제 공고 라벨 평가 (data/goldenset/real/) — 합성 골든셋과 분리 보고")
    p.add_argument("--slots", action="store_true",
                   help="참가자격 슬롯추출까지 평가 (Luna 호출)")
    p.set_defaults(fn=cmd_goldenset_eval_real)

    args = ap.parse_args()
    if args.cmd in ("analyze", "chat") and not (args.bid_no or args.file):
        ap.error("--bid-no 또는 --file 중 하나가 필요합니다")
    args.fn(args)


if __name__ == "__main__":
    main()
