# -*- coding: utf-8 -*-
"""표준 문서(계약예규) 조문 인덱싱.

data/standards/의 원본을 파서로 읽어 조문 단위로 잘라 clauses.json으로 저장한다.
- 가지번호(제35조의2 등)를 커버하는 조문 분리
- 장(章) 구조 보존 — 제4장 소프트웨어용역 계약조건 소속 여부가 중요
- 매 실행마다 재파싱하지 않음 (clauses.json 캐시)
- 원본 HWP는 감사 대비용으로 그대로 보관
"""
import json
import re
from pathlib import Path

from parsers import parse_document

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "standards"
CLAUSES_PATH = DATA_DIR / "clauses.json"

# 조문 헤더: 제58조(하자보수 등), 제35조의2(...) — 가지번호 필수 커버
CLAUSE_HEADER_RE = re.compile(r"제(\d+)조(의\d+)?\(([^)]+)\)")
CHAPTER_RE = re.compile(r"^\s*제(\d+)장\s+(.+?)\s*$", re.MULTILINE)

# 문서 표시명 매핑 (파일명 키워드 -> source 명)
_SOURCE_NAMES = [
    ("용역계약일반조건", "용역계약일반조건"),
    ("집행기준", "정부 입찰·계약 집행기준"),
    # 용역계약일반조건 제55조가 지체상금률을 시행규칙 제75조로 위임하고 있어,
    # 위임 대상 원문이 있어야 지체상금'율'을 판정할 수 있다.
    ("법률 시행규칙", "국가계약법 시행규칙"),
    ("법률 시행령", "국가계약법 시행령"),
]


def _source_name(filename):
    for kw, name in _SOURCE_NAMES:
        if kw in filename:
            return name
    return Path(filename).stem


def _split_clauses(source, text):
    """본문을 조문 단위로 분리. 장 헤더 위치를 추적해 각 조문에 소속 장을 부여."""
    chapters = [(m.start(), f"제{m.group(1)}장 {m.group(2)}")
                for m in CHAPTER_RE.finditer(text)]

    def chapter_at(pos):
        cur = None
        for cpos, cname in chapters:
            if cpos <= pos:
                cur = cname
            else:
                break
        return cur

    headers = list(CLAUSE_HEADER_RE.finditer(text))
    clauses = []
    for i, m in enumerate(headers):
        # 본문 중 조문 인용("제21조 및 제22조의 인수")과 구분:
        # 조문 헤더는 줄 시작(또는 공백 뒤 줄 시작)에 온다.
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start:m.start()].strip():
            continue  # 줄 중간 등장 — 인용이므로 스킵
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        # 다음 헤더가 인용으로 스킵될 수 있으니 실제 다음 '헤더 줄'까지로 재계산
        for j in range(i + 1, len(headers)):
            nm = headers[j]
            ls = text.rfind("\n", 0, nm.start()) + 1
            if not text[ls:nm.start()].strip():
                end = nm.start()
                break
        else:
            end = len(text)
        body = text[m.start():end].strip()
        num = m.group(1) + (m.group(2) or "")
        clauses.append({
            "source": source,
            "chapter": chapter_at(m.start()),
            "clause_no": f"{num}조" if not m.group(2) else f"{m.group(1)}조{m.group(2)}",
            "title": f"제{m.group(1)}조{m.group(2) or ''}({m.group(3)})",
            "text": body,
        })
    return clauses


def build_clauses(force=False):
    """표준 HWP를 파싱해 clauses.json 생성. 이미 있으면 재파싱하지 않음."""
    if CLAUSES_PATH.exists() and not force:
        return load_clauses()

    all_clauses = []
    parse_reports = []
    for f in sorted(DATA_DIR.iterdir()):
        if f.suffix.lower() not in (".hwp", ".hwpx", ".hml", ".pdf"):
            continue
        result = parse_document(f)
        parse_reports.append({
            "file": f.name,
            "parse_status": result["parse_status"],
            "parse_notes": result["parse_notes"],
        })
        if result["parse_status"] == "failed":
            continue
        source = _source_name(f.name)
        all_clauses.extend(_split_clauses(source, result["full_text"]))

    payload = {"parse_reports": parse_reports, "clauses": all_clauses}
    CLAUSES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return all_clauses


def load_clauses():
    payload = json.loads(CLAUSES_PATH.read_text(encoding="utf-8"))
    return payload["clauses"]


def find_clause(clauses, source, clause_no):
    for c in clauses:
        if c["source"] == source and c["clause_no"] == clause_no:
            return c
    return None


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    clauses = build_clauses(force=force)
    print(f"조문 {len(clauses)}건 인덱싱 완료 -> {CLAUSES_PATH}")
    by_src = {}
    for c in clauses:
        by_src.setdefault(c["source"], 0)
        by_src[c["source"]] += 1
    for s, n in by_src.items():
        print(f"  {s}: {n}건")
