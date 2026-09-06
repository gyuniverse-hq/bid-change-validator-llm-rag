# -*- coding: utf-8 -*-
"""PDF 파서. 1차 pdfplumber(텍스트+표), 2차 pypdf(텍스트만)."""
from .base import make_result


def parse_pdf(path):
    # 1차: pdfplumber — 표 구조까지 추출
    try:
        import pdfplumber
        texts, tables = [], []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    texts.append(t)
                for tb in (page.extract_tables() or []):
                    rows = [[(c or "") for c in row] for row in tb]
                    if rows:
                        tables.append({"rows": rows})
        full_text = "\n".join(texts)
        if full_text.strip():
            return make_result(path, full_text=full_text, tables=tables,
                               parse_status="success", parse_notes="", fmt="pdf")
    except Exception as e:
        first_err = str(e)
    else:
        first_err = "pdfplumber: 텍스트 없음(스캔본 가능성)"

    # 2차: pypdf — 텍스트만
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        full_text = "\n".join((p.extract_text() or "") for p in reader.pages)
        if full_text.strip():
            return make_result(
                path, full_text=full_text, tables=[],
                parse_status="partial",
                parse_notes=f"pdfplumber 실패({first_err}) — pypdf 폴백, 표 구조 미보존",
                fmt="pdf")
    except Exception as e:
        return make_result(path, parse_status="failed",
                           parse_notes=f"pdfplumber({first_err}); pypdf({e})", fmt="pdf")
    return make_result(path, parse_status="failed",
                       parse_notes=f"텍스트 추출 불가(스캔 PDF 가능성): {first_err}", fmt="pdf")
