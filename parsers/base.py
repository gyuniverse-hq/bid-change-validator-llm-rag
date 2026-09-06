# -*- coding: utf-8 -*-
"""모든 파서가 공유하는 통일 반환 형식."""


def make_result(source_file, full_text="", tables=None,
                parse_status="failed", parse_notes="", fmt=None):
    """파서 통일 반환 형식.

    parse_status:
      success — 텍스트·표 모두 정상 추출
      partial — 텍스트는 추출됐으나 표 구조 등 일부 소실
      failed  — 추출 실패 (임의 판정 금지, 상위에서 "확인 불가" 처리)
    """
    return {
        "source_file": str(source_file),
        "full_text": full_text,
        "tables": tables if tables is not None else [],
        "parse_status": parse_status,
        "parse_notes": parse_notes,
        "format": fmt,
    }
