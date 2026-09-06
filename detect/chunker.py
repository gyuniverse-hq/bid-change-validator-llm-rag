# -*- coding: utf-8 -*-
"""RFP 본문을 조항/절 단위 청크로 분리.

RFP는 표준 예규와 달리 번호 체계가 제각각이다:
"제3조", "3.2", "3.2.1", "가.", "1)", "□", "○" 등을 헤딩 후보로 본다.
청크에는 원문 그대로의 조항 라벨(clause_label)을 보존한다 — 근거 표시용.
"""
import re

_HEADING_PATTERNS = [
    re.compile(r"^\s*(제\d+조(?:의\d+)?)\s*[(\s]"),      # 제3조( / 제3조
    re.compile(r"^\s*(제\d+장)\s"),                       # 제2장
    re.compile(r"^\s*(\d+(?:\.\d+)+)[.)]?\s+"),           # 3.2 / 3.2.1
    re.compile(r"^\s*(\d+)[.)]\s+"),                      # 3. / 3)
    re.compile(r"^\s*([IVXivx]+)\.\s+"),                  # IV.
    re.compile(r"^\s*([가-힣])[.)]\s+"),                  # 가. / 나)
]

_MAX_CHUNK_CHARS = 1500


def _match_heading(line):
    for pat in _HEADING_PATTERNS:
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


def chunk_rfp(full_text):
    """[{chunk_id, clause_label, text}] 반환. 문서 순서 보존."""
    lines = full_text.splitlines()
    chunks = []
    cur_label = None
    cur_lines = []

    def flush():
        nonlocal cur_lines, cur_label
        text = "\n".join(cur_lines).strip()
        if text:
            chunks.append({
                "chunk_id": len(chunks),
                "clause_label": cur_label,
                "text": text,
            })
        cur_lines = []

    for line in lines:
        label = _match_heading(line)
        if label is not None:
            flush()
            cur_label = label
        cur_lines.append(line)
        # 헤딩 없이 지나치게 길어지면 문단 단위로 끊는다
        if sum(len(x) for x in cur_lines) > _MAX_CHUNK_CHARS:
            flush()
    flush()
    return chunks
