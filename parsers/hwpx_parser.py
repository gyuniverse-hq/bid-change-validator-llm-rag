# -*- coding: utf-8 -*-
"""HWPX(ZIP + XML) 파서.

Contents/section*.xml 을 lxml로 순회. 텍스트 노드는 태그가 '}t'로 끝난다.
표는 <hp:tbl>을 별도 순회해 행/열 구조를 보존한다 (배점표는 순서가 깨지면 무용지물).
"""
import re
import zipfile

from lxml import etree

from .base import make_result


def _tag_ends(el, suffix):
    return isinstance(el.tag, str) and el.tag.endswith(suffix)


def _collect_text(el):
    """엘리먼트 하위의 모든 '}t' 텍스트 노드를 문서 순서대로 수집."""
    parts = []
    for node in el.iter():
        if _tag_ends(node, "}t") and node.text:
            parts.append(node.text)
    return parts


def parse_hwpx(path):
    try:
        zf = zipfile.ZipFile(str(path))
    except Exception as e:
        return make_result(path, parse_status="failed",
                           parse_notes=f"ZIP 열기 실패: {e}", fmt="hwpx")

    section_names = sorted(
        (n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
        key=lambda n: int(re.search(r"(\d+)", n).group(1)),
    )
    if not section_names:
        return make_result(path, parse_status="failed",
                           parse_notes="Contents/section*.xml 없음 — HWPX 아님", fmt="hwpx")

    lines = []
    tables = []
    table_ok = True
    for name in section_names:
        try:
            root = etree.fromstring(zf.read(name))
        except Exception as e:
            return make_result(path, parse_status="failed",
                               parse_notes=f"{name} XML 파싱 실패: {e}", fmt="hwpx")
        # 문단(}p) 단위로 줄바꿈 보존
        for node in root.iter():
            if _tag_ends(node, "}p"):
                # 직접 자식 run들의 t만 — 중첩 표 셀 문단은 자체적으로 순회됨
                own = []
                for t in node.iter():
                    if _tag_ends(t, "}t") and t.text:
                        # 셀 내부 문단(}p 중첩)의 t는 그 문단에서 처리
                        anc = t.getparent()
                        skip = False
                        while anc is not None and anc is not node:
                            if _tag_ends(anc, "}p"):
                                skip = True
                                break
                            anc = anc.getparent()
                        if not skip:
                            own.append(t.text)
                if own:
                    lines.append("".join(own))
        # 표 구조 별도 순회
        try:
            for tbl in root.iter():
                if not _tag_ends(tbl, "}tbl"):
                    continue
                rows = []
                for tr in tbl.iter():
                    if not _tag_ends(tr, "}tr"):
                        continue
                    cells = []
                    for tc in tr:
                        if _tag_ends(tc, "}tc"):
                            cells.append("\n".join(_collect_text(tc)))
                    rows.append(cells)
                if rows:
                    tables.append({"rows": rows})
        except Exception:
            table_ok = False

    full_text = "\n".join(lines)
    if not full_text.strip():
        return make_result(path, parse_status="failed",
                           parse_notes="본문 텍스트 없음", fmt="hwpx")
    status = "success" if table_ok else "partial"
    notes = "" if table_ok else "표 추출 중 오류 — 표 구조 일부 소실 가능"
    return make_result(path, full_text=full_text, tables=tables,
                       parse_status=status, parse_notes=notes, fmt="hwpx")
