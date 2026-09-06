# -*- coding: utf-8 -*-
"""단일 공고에 대한 '확인 → 재판정 → 저장' 전체 흐름을 한 함수로 묶는다.

`main.py`의 `monitor`(공고 1건 수동 확인)와 `watch`(감시 목록 전체 순회),
그리고 `server/api.py`의 `/api/bid`(브라우저에서 공고를 열 때)가 전부
이 함수 하나를 공유한다 — 같은 시퀀스가 세 곳에 따로 있으면 나중에
한쪽만 고치고 어긋나기 쉽다. 특히 웹 데모에서 "공고를 다시 열 때마다
실제로 최신인지 확인"하는 요구는, CLI의 감시 기능과 완전히 같은 로직
(check_and_update로 진짜 API를 매번 확인)이어야 의미가 있다 — 화면에서만
다시 확인하는 척하고 실제로는 예전 캐시를 보여주면 안 된다.

이 함수는 상태(no_change/meta_only 포함)와 무관하게 **항상 item/title/
findings/slots를 채워 반환**한다. 그래야 호출하는 쪽이 "바뀐 게 없으니
이전 화면 그대로 보여주면 되는지, 재계산된 새 내용을 보여줘야 하는지"를
따로 분기하지 않고 반환값만 그대로 렌더링하면 된다.
"""
from collectors.narajangteo import ATTACH_DIR
from detect import chunk_rfp, detect_patterns, detect_standard_diff
from eligibility import extract_slots
from parsers import parse_document

from .align import align_chunks
from .change import _load_manifest, check_and_update, load_analysis, save_analysis
from .rejudge import diff_eligibility_slots, diff_findings, rejudge_changed


def check_and_rejudge(bid_no, clauses):
    """공고 1건을 실제 조달청 API로 확인하고, 바뀐 경우에만 재판정해 저장한다.

    반환:
    {
      "status": "no_change" | "meta_only" | "no_rfp" | "parse_failed" | "initial" | "updated",
      "kind": check_and_update()의 kind 그대로,
      "message": 사람이 읽을 한 줄 요약,
      "old_version", "new_version",
      "item": 최신 API 응답 원본 (제목·발주기관·마감일 등 표시용, 매 호출마다 새로 조회됨),
      "title", "rfp_file",
      "chunks": 현재 조항 청크 전체 (원문 요약 등 호출부가 원문이 필요할 때 재사용),
      "findings": 현재 유효한 확인 필요/확인 불가 findings 전체 목록,
      "slots": 현재 참가자격 슬롯 전체 목록,
      "finding_states": [...],   # status=="updated"일 때만. diff_findings() 결과
      "slot_states": [...],      # status=="updated"일 때만. diff_eligibility_slots() 결과
    }
    """
    st = check_and_update(bid_no)
    item = st["latest_item"]
    out = {
        "status": None, "kind": st["kind"], "message": "",
        "old_version": st["old_version"], "new_version": st["new_version"],
        "item": item, "title": item.get("bidNtceNm", bid_no), "rfp_file": None,
        "chunks": [], "findings": [], "slots": [], "finding_states": [], "slot_states": [],
    }

    if st["kind"] in ("none", "meta_only"):
        out["status"] = "no_change" if st["kind"] == "none" else "meta_only"
        out["message"] = ("변경 없음" if st["kind"] == "none" else
                          "공고 메타만 변경, 첨부 동일(해시 일치) — 재판정 불필요")
        # 문서 자체는 안 바뀌었으니 재계산하지 않고 마지막 저장본을 그대로 쓴다.
        snap = load_analysis(bid_no, st["new_version"])
        if snap:
            out["chunks"] = snap.get("chunks", [])
            out["findings"] = snap.get("findings", [])
            out["slots"] = snap.get("slots", [])
        manifest = _load_manifest(ATTACH_DIR / bid_no / st["new_version"])
        if manifest:
            out["rfp_file"] = manifest.get("rfp_file")
        return out

    new_rfp = st["new_manifest"]["rfp_file"]
    out["rfp_file"] = new_rfp
    if not new_rfp:
        out["status"] = "no_rfp"
        out["message"] = "새 버전에서 RFP 첨부를 찾지 못함 — 확인 불가"
        return out
    new_parsed = parse_document(new_rfp)
    if new_parsed["parse_status"] == "failed":
        out["status"] = "parse_failed"
        out["message"] = f"[파싱 실패] {new_parsed['parse_notes']}"
        return out

    new_chunks = chunk_rfp(new_parsed["full_text"])
    new_findings_full = detect_standard_diff(new_chunks, clauses) + detect_patterns(new_chunks)
    slot_out = extract_slots(new_chunks)
    new_slots = slot_out.get("slots", []) if slot_out["status"] == "ok" else []
    out["chunks"] = new_chunks
    out["findings"] = new_findings_full
    out["slots"] = new_slots

    if st["kind"] == "initial":
        save_analysis(bid_no, st["new_version"], new_chunks, new_findings_full, slots=new_slots)
        out["status"] = "initial"
        out["message"] = "최초 수집 — 전체 분석 저장 완료"
        return out

    old = load_analysis(bid_no, st["old_version"])
    if not old:
        save_analysis(bid_no, st["new_version"], new_chunks, new_findings_full, slots=new_slots)
        out["status"] = "initial"
        out["message"] = "이전 분석 스냅샷 없음 — 전체 분석으로 대체"
        return out

    # 조항 정렬은 임베딩 유사도 — 조항 번호 매칭 금지 (정정 시 번호가 밀린다)
    alignment = align_chunks(old["chunks"], new_chunks)
    new_findings, changed_ids = rejudge_changed(
        old["chunks"], new_chunks, alignment, old["findings"], clauses)
    finding_states = diff_findings(old["findings"], new_findings, alignment, changed_ids)

    # 이전 스냅샷에 슬롯이 없으면(구버전 데이터) 비교 자체를 생략 —
    # "전부 신규발생"으로 잘못 표시하지 않는다.
    old_slots = old.get("slots")
    slot_states = diff_eligibility_slots(old_slots, new_slots) if old_slots is not None else []

    kept_findings = [s["finding"] for s in finding_states if s["state"] != "해소됨"]
    save_analysis(bid_no, st["new_version"], new_chunks, kept_findings, slots=new_slots)

    out["status"] = "updated"
    out["message"] = "문서 변경 확인 — 재판정 완료"
    out["findings"] = kept_findings
    out["alignment"] = alignment
    out["finding_states"] = finding_states
    out["slot_states"] = slot_states
    return out
