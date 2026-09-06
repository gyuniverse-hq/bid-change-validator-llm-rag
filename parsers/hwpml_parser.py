# -*- coding: utf-8 -*-
"""HWPML(.hml — XML 단일파일 한글 문서) 파서.

법제처 등에서 받은 계약예규 파일이 확장자만 .hwp이고 실제로는 HWPML인 경우가 있다.
구조: <HWPML><BODY><SECTION><P><TEXT><CHAR>텍스트</CHAR>
표: <TABLE><ROW><CELL><PARALIST><P>...
"""
from lxml import etree

from .base import make_result


def _nearest_ancestor_p(el):
    cur = el.getparent()
    while cur is not None:
        if cur.tag == "P":
            return cur
        cur = cur.getparent()
    return None


def _para_own_text(p):
    """해당 P에 직접 속한 CHAR 텍스트만 수집 (중첩 표 셀의 P 텍스트 중복 방지)."""
    parts = []
    for char in p.iter("CHAR"):
        if _nearest_ancestor_p(char) is p and char.text:
            parts.append(char.text)
    return "".join(parts)


def _cell_text(cell):
    parts = []
    for p in cell.iter("P"):
        t = _para_own_text(p)
        if t:
            parts.append(t)
    return "\n".join(parts)


def parse_hwpml(path):
    try:
        parser = etree.XMLParser(recover=True, huge_tree=True)
        tree = etree.parse(str(path), parser)
        root = tree.getroot()
    except Exception as e:
        return make_result(path, parse_status="failed",
                           parse_notes=f"HWPML XML 파싱 실패: {e}", fmt="hwpml")

    lines = []
    for p in root.iter("P"):
        t = _para_own_text(p)
        lines.append(t)
    full_text = "\n".join(lines)

    tables = []
    table_ok = True
    try:
        for tbl in root.iter("TABLE"):
            rows = []
            for row in tbl.findall("ROW"):
                cells = [_cell_text(c) for c in row.findall("CELL")]
                rows.append(cells)
            if rows:
                tables.append({"rows": rows})
    except Exception:
        table_ok = False

    if not full_text.strip():
        return make_result(path, parse_status="failed",
                           parse_notes="본문 텍스트 없음", fmt="hwpml")
    status = "success" if table_ok else "partial"
    notes = "" if table_ok else "표 추출 중 오류 — 표 구조 일부 소실 가능"
    return make_result(path, full_text=full_text, tables=tables,
                       parse_status=status, parse_notes=notes, fmt="hwpml")
