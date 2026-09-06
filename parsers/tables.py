# -*- coding: utf-8 -*-
"""표 구조 공용 유틸 — 배점표 식별 등."""

_SCORE_KEYWORDS = ("배점", "평가항목", "평가기준", "평점", "가점", "감점")


def is_score_table(table):
    """배점표(평가 배점 관련 표)로 보이는지 판별."""
    flat = " ".join(" ".join(row) for row in table.get("rows", []))
    return any(kw in flat for kw in _SCORE_KEYWORDS)


def find_score_tables(tables):
    return [t for t in tables if is_score_table(t)]


def table_to_text(table):
    """표를 행 단위 텍스트로 직렬화 (검색·근거 표시용)."""
    return "\n".join(" | ".join(cell.replace("\n", " ") for cell in row)
                     for row in table.get("rows", []))
