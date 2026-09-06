# -*- coding: utf-8 -*-
"""나라장터(조달청) 입찰공고 수집기.

- 오퍼레이션: getBidPblancListInfoServc (용역)
- API 키는 .env의 PUBLIC_INFO_API_KEY (URL 인코딩된 상태로 저장돼 있어 unquote 후 사용)
- 원본 응답(raw JSON)을 파싱 전에 통째로 data/raw/에 저장 — 재파싱·감사용
- 첨부는 sha256 해시와 함께 저장 — 변경 감지용
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"
OP_SERVC = "getBidPblancListInfoServc"

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
ATTACH_DIR = ROOT / "data" / "attachments"

# RFP 식별 키워드 (우선순위 순)
RFP_KEYWORDS = ("제안요청서", "과업내용서", "과업지시서", "RFP")
DOC_EXTS = (".hwp", ".hwpx", ".pdf")


def _service_key():
    key = os.getenv("PUBLIC_INFO_API_KEY")
    if not key:
        raise RuntimeError("PUBLIC_INFO_API_KEY 미설정 (.env 확인)")
    # .env에 URL 인코딩된 키가 저장돼 있음 — requests가 재인코딩하므로 원복
    if "%" in key:
        key = unquote(key)
    return key


def _save_raw(op, payload_text, tag=""):
    """원본 응답을 파싱해서 버리지 않는다 — 통째로 먼저 저장."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    path = RAW_DIR / f"{ts}_{op}{suffix}.json"
    path.write_text(payload_text, encoding="utf-8")
    return path


def _call(op, params, tag=""):
    url = f"{BASE_URL}/{op}"
    q = {"serviceKey": _service_key(), "type": "json", **params}
    resp = requests.get(url, params=q, timeout=60)
    resp.raise_for_status()
    raw_path = _save_raw(op, resp.text, tag=tag)
    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError(f"JSON 아님(원본은 {raw_path}에 보존): {resp.text[:200]}") from e
    header = (data.get("response") or {}).get("header") or {}
    code = header.get("resultCode")
    if code not in (None, "00", "0"):
        raise RuntimeError(f"API 오류 {code}: {header.get('resultMsg')} (원본: {raw_path})")
    return data, raw_path


def _items(data):
    body = (data.get("response") or {}).get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):  # 단건일 때 {"item": {...}} 형태 방어
        items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
    return items, body.get("totalCount", 0)


def fetch_service_bids(inqry_bgn_dt, inqry_end_dt, page=1, rows=50, keyword=None):
    """용역 입찰공고 목록 조회 (공고게시일시 범위, inqryDiv=1).

    inqry_bgn_dt/inqry_end_dt: 'YYYYMMDDHHMM'
    """
    params = {
        "pageNo": page, "numOfRows": rows,
        "inqryDiv": 1, "inqryBgnDt": inqry_bgn_dt, "inqryEndDt": inqry_end_dt,
    }
    if keyword:
        params["bidNtceNm"] = keyword
    data, raw_path = _call(OP_SERVC, params)
    items, total = _items(data)
    return {"items": items, "total": total, "raw_path": str(raw_path)}


def fetch_bid_by_no(bid_ntce_no):
    """공고번호로 조회 (inqryDiv=2). 정정공고가 있으면 차수(bidNtceOrd)별로 복수 반환."""
    params = {"pageNo": 1, "numOfRows": 30, "inqryDiv": 2, "bidNtceNo": bid_ntce_no}
    data, raw_path = _call(OP_SERVC, params, tag=bid_ntce_no)
    items, total = _items(data)
    return {"items": items, "total": total, "raw_path": str(raw_path)}


def list_spec_files(item):
    """공고 항목에서 첨부 (파일명, URL) 목록 추출. ntceSpecFileNm1~10 / ntceSpecDocUrl1~10."""
    files = []
    for i in range(1, 11):
        name = (item.get(f"ntceSpecFileNm{i}") or "").strip()
        url = (item.get(f"ntceSpecDocUrl{i}") or "").strip()
        if name and url:
            files.append({"name": name, "url": url})
    return files


def pick_rfp_attachments(item):
    """RFP 후보 첨부 선택.

    1순위 — 파일명에 제안요청서/과업내용서/과업지시서/RFP 키워드
    폴백  — hwp/hwpx/pdf 전부 반환 (다운로드 후 크기 최대 파일을 RFP로 간주)
    반환: (후보 목록, 선택 방법 문자열)
    """
    files = list_spec_files(item)
    for kw in RFP_KEYWORDS:
        hits = [f for f in files if kw.lower() in f["name"].lower()]
        if hits:
            return hits, f"keyword:{kw}"
    fallback = [f for f in files
                if any(f["name"].lower().endswith(ext) for ext in DOC_EXTS)]
    return fallback, "fallback:largest_doc"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def download_attachments(item, version="v1"):
    """첨부 다운로드 + sha256 기록. data/attachments/<공고번호>/<version>/에 저장.

    반환 manifest:
    {"bid_ntce_no", "bid_ntce_ord", "version", "selection_method",
     "files": [{"name","url","path","sha256","size"}], "rfp_file": 경로 or None}
    """
    bid_no = item.get("bidNtceNo", "unknown")
    dest = ATTACH_DIR / _safe_name(bid_no) / version
    dest.mkdir(parents=True, exist_ok=True)

    candidates, method = pick_rfp_attachments(item)
    records = []
    for f in candidates:
        out = dest / _safe_name(f["name"])
        if not out.exists():
            r = requests.get(f["url"], timeout=120)
            r.raise_for_status()
            out.write_bytes(r.content)
        records.append({
            "name": f["name"], "url": f["url"], "path": str(out),
            "sha256": _sha256(out), "size": out.stat().st_size,
        })

    rfp_file = None
    if records:
        if method.startswith("keyword"):
            rfp_file = records[0]["path"]
        else:
            rfp_file = max(records, key=lambda r: r["size"])["path"]

    manifest = {
        "bid_ntce_no": bid_no,
        "bid_ntce_ord": item.get("bidNtceOrd"),
        "version": version,
        "selection_method": method,
        "files": records,
        "rfp_file": rfp_file,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
