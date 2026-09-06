# -*- coding: utf-8 -*-
"""변경 감지.

- 공고번호 단건 조회로 최신 차수(bidNtceOrd)만 가볍게 확인 (전체 재수집 금지 — 1,000회/일 한도)
- 차수 변경 감지 시 첨부 재다운로드 → **파일 해시 비교**
  (공고 메타만 바뀌고 첨부는 그대로인 경우가 많다)
- 문서가 실제로 바뀌었으면 v2로 저장, v1은 보존
"""
import json
from pathlib import Path

from collectors.narajangteo import ATTACH_DIR, download_attachments, fetch_bid_by_no


def _versions(bid_dir):
    if not bid_dir.exists():
        return []
    vs = [d for d in bid_dir.iterdir() if d.is_dir() and d.name.startswith("v")]
    return sorted(vs, key=lambda d: int(d.name[1:]))


def _load_manifest(vdir):
    p = vdir / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def latest_version_dir(bid_ntce_no):
    vs = _versions(ATTACH_DIR / bid_ntce_no)
    return vs[-1] if vs else None


def check_and_update(bid_ntce_no):
    """변경 확인 + 필요 시 새 버전 저장.

    반환: {"changed": bool, "kind": "none"|"meta_only"|"attachment"|"initial",
           "old_version", "new_version", "old_manifest", "new_manifest", "latest_item"}
    """
    result = fetch_bid_by_no(bid_ntce_no)
    items = result["items"]
    if not items:
        raise RuntimeError(f"공고 {bid_ntce_no} 조회 결과 없음")
    latest = max(items, key=lambda x: int(x.get("bidNtceOrd") or 0))

    bid_dir = ATTACH_DIR / bid_ntce_no
    versions = _versions(bid_dir)

    if not versions:
        manifest = download_attachments(latest, version="v1")
        return {"changed": True, "kind": "initial",
                "old_version": None, "new_version": "v1",
                "old_manifest": None, "new_manifest": manifest,
                "latest_item": latest}

    old_dir = versions[-1]
    old_manifest = _load_manifest(old_dir)
    old_ord = int(old_manifest.get("bid_ntce_ord") or 0) if old_manifest else 0
    new_ord = int(latest.get("bidNtceOrd") or 0)

    if new_ord <= old_ord:
        return {"changed": False, "kind": "none",
                "old_version": old_dir.name, "new_version": old_dir.name,
                "old_manifest": old_manifest, "new_manifest": old_manifest,
                "latest_item": latest}

    # 차수가 올랐다 — 첨부 재다운로드 후 해시 비교
    next_name = f"v{int(old_dir.name[1:]) + 1}"
    new_manifest = download_attachments(latest, version=next_name)

    old_hashes = {f["name"]: f["sha256"] for f in (old_manifest or {}).get("files", [])}
    new_hashes = {f["name"]: f["sha256"] for f in new_manifest.get("files", [])}
    if old_hashes == new_hashes:
        # 첨부는 그대로 — 새 버전 디렉터리를 유지하되 메타 변경으로 분류
        return {"changed": True, "kind": "meta_only",
                "old_version": old_dir.name, "new_version": next_name,
                "old_manifest": old_manifest, "new_manifest": new_manifest,
                "latest_item": latest}
    return {"changed": True, "kind": "attachment",
            "old_version": old_dir.name, "new_version": next_name,
            "old_manifest": old_manifest, "new_manifest": new_manifest,
            "latest_item": latest}


def save_analysis(bid_ntce_no, version, chunks, findings, slots=None):
    """버전별 분석 스냅샷 저장 — 재판정 시 diff 기준.

    slots(참가자격 슬롯, eligibility/slots.py 결과)도 함께 저장한다.
    이게 없으면 다음 버전과 비교할 때 "정정공고로 실적요건 금액이 바뀌었는지"를
    확인 필요 조항(경로 A/B)과는 별개로 감지할 방법이 없다.
    """
    vdir = ATTACH_DIR / bid_ntce_no / version
    vdir.mkdir(parents=True, exist_ok=True)
    payload = {"chunks": chunks, "findings": findings}
    if slots is not None:
        payload["slots"] = slots
    (vdir / "analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_analysis(bid_ntce_no, version):
    p = ATTACH_DIR / bid_ntce_no / version / "analysis.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
