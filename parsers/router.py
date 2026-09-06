# -*- coding: utf-8 -*-
"""확장자별 분기 + 매직바이트 스니핑 + 폴백.

주의: 실제 배포 파일은 확장자를 신뢰할 수 없다.
(예: 법제처 계약예규 파일은 확장자 .hwp이지만 실제로는 HWPML(XML)이다.)
따라서 파일 앞부분 바이트로 실제 형식을 먼저 판별하고, 실패 시 확장자로 폴백한다.
"""
from pathlib import Path

from .base import make_result
from .hwp_parser import parse_hwp
from .hwpml_parser import parse_hwpml
from .hwpx_parser import parse_hwpx
from .pdf_parser import parse_pdf

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _sniff(path):
    try:
        head = Path(path).open("rb").read(4096)
    except OSError:
        return None
    if head.startswith(b"PK\x03\x04"):
        return "hwpx"  # ZIP — HWPX (docx 등도 여기로 오지만 hwpx 파서가 검증)
    if head.startswith(_OLE_MAGIC):
        return "hwp"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.lstrip().startswith(b"<?xml") and b"HWPML" in head:
        return "hwpml"
    return None


def _parse_txt(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = Path(path).read_text(encoding="cp949", errors="replace")
    if not text.strip():
        return make_result(path, parse_status="failed", parse_notes="빈 텍스트", fmt="txt")
    return make_result(path, full_text=text, tables=[], parse_status="partial",
                       parse_notes="일반 텍스트 — 표 구조 없음", fmt="txt")


_BY_EXT = {".hwp": "hwp", ".hwpx": "hwpx", ".hml": "hwpml", ".pdf": "pdf", ".txt": "txt"}
_PARSERS = {"hwp": parse_hwp, "hwpx": parse_hwpx, "hwpml": parse_hwpml,
            "pdf": parse_pdf, "txt": _parse_txt}


def parse_document(path):
    """통일 반환 형식으로 문서를 파싱한다. 형식 판별 실패도 조용히 넘기지 않는다."""
    p = Path(path)
    if not p.exists():
        return make_result(path, parse_status="failed", parse_notes="파일 없음")

    fmt = _sniff(p)
    ext_fmt = _BY_EXT.get(p.suffix.lower())
    tried = []

    order = []
    if fmt:
        order.append(fmt)
    if ext_fmt and ext_fmt not in order:
        order.append(ext_fmt)
    if not order:
        return make_result(path, parse_status="failed",
                           parse_notes=f"지원하지 않는 형식 (확장자 {p.suffix})")

    last = None
    for f in order:
        result = _PARSERS[f](p)
        tried.append(f"{f}={result['parse_status']}")
        if result["parse_status"] in ("success", "partial"):
            if fmt and ext_fmt and fmt != ext_fmt:
                extra = f"확장자({ext_fmt})와 실제 형식({fmt}) 불일치 — 실제 형식으로 파싱"
                result["parse_notes"] = (result["parse_notes"] + "; " + extra).strip("; ")
            return result
        last = result
    last["parse_notes"] = f"모든 경로 실패 [{', '.join(tried)}]: " + last["parse_notes"]
    return last
