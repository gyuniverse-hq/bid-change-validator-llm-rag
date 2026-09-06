# -*- coding: utf-8 -*-
"""수치 정규화 모듈 — LLM 미개입, 순수 코드.

원칙:
- 원문(raw)은 절대 보존한다.
- 파싱 실패 시 임의 추정하지 않고 parse_status="failed"로 기록한다.
- 기간의 내부 표준 단위는 "개월"(MONTH)로 통일한다.
"""
import re

COMPARATORS = {
    "이상": ">=", "초과": ">",
    "이하": "<=", "미만": "<",
    "이내": "<=", "이후": ">=",
}

KOREAN_UNITS = {"조": 10**12, "억": 10**8, "만": 10**4, "천": 10**3}

PERIOD_UNITS = {"년": 12, "개월": 1, "월": 1, "주": 0.25, "일": 1 / 30}

# 금액 앞에 붙는 의미 라벨 — 추정가격과 기초금액은 의미가 다르므로 반드시 보존
AMOUNT_LABELS = (
    "추정가격", "추정금액", "기초금액", "계약금액", "사업금액",
    "배정예산", "사업예산", "총사업비", "예정가격",
)

_HANGUL_DIGITS = {
    "영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4,
    "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9,
}
_SMALL_MULT = {"십": 10, "백": 100, "천": 1000}
_GROUP_UNITS = {"만": 10**4, "억": 10**8, "조": 10**12}

_NUM_TOKEN_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)"          # 아라비아 숫자 (쉼표 허용)
    r"|([영공일이삼사오육륙칠팔구])"   # 한글 수사
    r"|([십백천])"                    # 소승수
    r"|([만억조])"                    # 그룹 단위
)


def parse_korean_number(text):
    """한글 수사·아라비아 숫자 혼합 표기를 정수/실수로 변환.

    예: "3억 5천만" -> 350000000, "오억" -> 500000000, "500,000,000" -> 500000000
    파싱 불가 시 None 반환 (임의 추정 금지).
    """
    if not text:
        return None
    total = 0.0
    section = 0.0   # 현재 그룹(만/억/조 미만) 누적
    num = None      # 대기 중인 숫자
    matched_any = False
    for m in _NUM_TOKEN_RE.finditer(text):
        arabic, hdigit, small, group = m.groups()
        matched_any = True
        if arabic is not None:
            num = float(arabic.replace(",", ""))
        elif hdigit is not None:
            num = (num or 0) * 10 + _HANGUL_DIGITS[hdigit] if num and num == int(num) and num < 10 else float(_HANGUL_DIGITS[hdigit])
        elif small is not None:
            section += (num if num is not None else 1) * _SMALL_MULT[small]
            num = None
        elif group is not None:
            section += num if num is not None else 0
            if section == 0:
                section = 1  # "억원" 단독 표기
            total += section * _GROUP_UNITS[group]
            section = 0.0
            num = None
    if not matched_any:
        return None
    total += section + (num if num is not None else 0)
    if total == int(total):
        return int(total)
    return total


def _find_op(text, after_pos=0):
    """비교 표현 탐색. (op, keyword) 또는 (None, None)."""
    best = None
    for kw, op in COMPARATORS.items():
        i = text.find(kw, after_pos)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, kw, op)
    if best:
        return best[2], best[1]
    return None, None


def _extract_label(text):
    for label in AMOUNT_LABELS:
        if label in text:
            return label
    return None


def _extract_paren_note(text):
    m = re.search(r"\(([^)]*)\)", text)
    return m.group(1).strip() if m else None


def _failed(raw, unit=None, reason=""):
    return {
        "raw": raw, "value": None, "unit": unit, "op": None,
        "parse_status": "failed", "parse_notes": reason or "수치 해석 불가",
    }


# 금액 표현: 숫자/한글수사 뭉치 + "원"
_AMOUNT_RE = re.compile(
    r"(?:금\s*)?"
    r"((?:[\d,\.]|[영공일이삼사오육륙칠팔구십백천만억조]|\s)+?)\s*원(?:정)?"
)
_OP_RE = re.compile("|".join(COMPARATORS.keys()))


def normalize_amount(raw):
    """금액 문자열 정규화. 범위("10억원 이상 20억원 미만")는 range로 저장."""
    if not raw or not raw.strip():
        return _failed(raw, "KRW", "빈 문자열")
    text = raw.strip()
    label = _extract_label(text)
    # 괄호 부가정보는 분리 보존 후 본문에서 제거하고 파싱
    note = _extract_paren_note(text)
    body = re.sub(r"\([^)]*\)", " ", text)

    found = []  # (value, op) 순서대로
    pos = 0
    for m in _AMOUNT_RE.finditer(body):
        chunk = m.group(1)
        value = parse_korean_number(chunk)
        if value is None or value == 0 and not re.search(r"[0영공]", chunk):
            continue
        # 금액 직후의 비교 표현만 그 금액에 귀속시킨다
        tail = body[m.end():]
        op_m = _OP_RE.match(tail.lstrip())
        op = COMPARATORS[op_m.group(0)] if op_m else None
        found.append((value, op))
        pos = m.end()

    if not found:
        return _failed(raw, "KRW", "금액 표현을 찾지 못함")

    base = {"raw": raw, "unit": "KRW", "parse_status": "success", "parse_notes": ""}
    if label:
        base["label"] = label
    if note:
        base["note"] = note

    if len(found) >= 2:
        # 범위: 하한(>=, >)과 상한(<=, <)이 함께 있는 경우
        lows = [(v, o) for v, o in found if o in (">=", ">")]
        highs = [(v, o) for v, o in found if o in ("<=", "<")]
        if lows and highs:
            base.update({
                "value": None, "op": None,
                "range": {
                    "min": lows[0][0], "min_op": lows[0][1],
                    "max": highs[0][0], "max_op": highs[0][1],
                },
            })
            return base
        return _failed(raw, "KRW", "복수 금액이 있으나 범위로 해석 불가")

    value, op = found[0]
    base.update({"value": value, "op": op})
    return base


_PERIOD_RE = re.compile(r"(\d+(?:\.\d+)?|[영공일이삼사오육륙칠팔구십백천]+)\s*(년|개월|월|주|일)")


def normalize_period(raw):
    """기간 문자열을 개월(MONTH) 단위로 정규화. "3년" == "36개월"."""
    if not raw or not raw.strip():
        return _failed(raw, "MONTH", "빈 문자열")
    text = raw.strip()
    m = _PERIOD_RE.search(text)
    if not m:
        return _failed(raw, "MONTH", "기간 표현을 찾지 못함")
    num_str, unit = m.groups()
    if re.match(r"^[\d.]+$", num_str):
        n = float(num_str)
    else:
        n = parse_korean_number(num_str)
        if n is None:
            return _failed(raw, "MONTH", "기간 수치 해석 불가")
    months = n * PERIOD_UNITS[unit]
    op, _kw = _find_op(text, m.end())
    result = {
        "raw": raw, "value": round(months, 4), "unit": "MONTH", "op": op,
        "parse_status": "success", "parse_notes": "",
        "orig_value": n, "orig_unit": unit,
    }
    return result


_PERCENT_BUNUI_RE = re.compile(r"(\d+(?:\.\d+)?|[일이삼사오육륙칠팔구십백천]+)\s*분의\s*(\d+(?:\.\d+)?|[일이삼사오육륙칠팔구십백천]+)")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|퍼센트|프로|퍼)")


def normalize_percent(raw):
    """백분율 정규화. "100분의 30" -> 30(PERCENT), "2%" -> 2."""
    if not raw or not raw.strip():
        return _failed(raw, "PERCENT", "빈 문자열")
    text = raw.strip()
    m = _PERCENT_BUNUI_RE.search(text)
    value = None
    end = 0
    if m:
        denom_s, numer_s = m.groups()
        denom = float(denom_s) if re.match(r"^[\d.]+$", denom_s) else parse_korean_number(denom_s)
        numer = float(numer_s) if re.match(r"^[\d.]+$", numer_s) else parse_korean_number(numer_s)
        if denom and numer is not None:
            value = numer / denom * 100
            end = m.end()
    if value is None:
        m2 = _PERCENT_RE.search(text)
        if m2:
            value = float(m2.group(1))
            end = m2.end()
    if value is None:
        return _failed(raw, "PERCENT", "백분율 표현을 찾지 못함")
    op, _kw = _find_op(text, end)
    if value == int(value):
        value = int(value)
    return {
        "raw": raw, "value": value, "unit": "PERCENT", "op": op,
        "parse_status": "success", "parse_notes": "",
    }


_COUNT_RE = re.compile(r"(\d+|[일이삼사오육륙칠팔구십]+)\s*(?:명|인(?![근시])|인원)")


def normalize_count(raw):
    """인원 수 정규화. "2인 이상" -> PERSON 2, op ">=". 기술인력 요건 판정용."""
    if not raw or not raw.strip():
        return _failed(raw, "PERSON", "빈 문자열")
    text = raw.strip()
    m = _COUNT_RE.search(text)
    if not m:
        return _failed(raw, "PERSON", "인원 표현을 찾지 못함")
    num_str = m.group(1)
    if re.match(r"^\d+$", num_str):
        n = int(num_str)
    else:
        n = parse_korean_number(num_str)
        if n is None:
            return _failed(raw, "PERSON", "인원 수치 해석 불가")
    op, _kw = _find_op(text, m.end())
    return {
        "raw": raw, "value": int(n), "unit": "PERSON", "op": op,
        "parse_status": "success", "parse_notes": "",
    }


def normalize_value(raw):
    """종류 자동 판별 정규화. 백분율 > 금액 > 기간 > 인원 순으로 판별."""
    if not raw or not raw.strip():
        return _failed(raw, None, "빈 문자열")
    text = raw.strip()
    if _PERCENT_BUNUI_RE.search(text) or _PERCENT_RE.search(text):
        return normalize_percent(text)
    if re.search(r"원", text) and _AMOUNT_RE.search(re.sub(r"\([^)]*\)", " ", text)):
        return normalize_amount(text)
    if _PERIOD_RE.search(text):
        return normalize_period(text)
    if _COUNT_RE.search(text):
        return normalize_count(text)
    return _failed(raw, None, "금액/기간/백분율/인원 어느 것에도 해당하지 않음")


def extract_values(text):
    """자유 텍스트에서 금액·기간·백분율 표현을 모두 찾아 정규화 목록으로 반환.

    탐지 단계(detect)에서 조항 텍스트를 스캔할 때 사용한다.
    """
    results = []
    if not text:
        return results
    body = text
    # 백분율 (100분의 30)
    for m in _PERCENT_BUNUI_RE.finditer(body):
        span_text = body[max(0, m.start() - 10):min(len(body), m.end() + 10)]
        r = normalize_percent(m.group(0) + body[m.end():m.end() + 6])
        if r["parse_status"] == "success":
            r["context"] = span_text
            results.append(r)
    for m in _PERCENT_RE.finditer(body):
        r = normalize_percent(m.group(0) + body[m.end():m.end() + 6])
        if r["parse_status"] == "success":
            r["context"] = body[max(0, m.start() - 10):min(len(body), m.end() + 10)]
            results.append(r)
    # 금액
    for m in _AMOUNT_RE.finditer(re.sub(r"\([^)]*\)", " ", body)):
        seg = body[max(0, m.start() - 15):min(len(body), m.end() + 10)]
        r = normalize_amount(m.group(0) + body[m.end():m.end() + 6])
        if r["parse_status"] == "success":
            r["context"] = seg
            results.append(r)
    # 기간
    for m in _PERIOD_RE.finditer(body):
        r = normalize_period(m.group(0) + body[m.end():m.end() + 6])
        if r["parse_status"] == "success":
            r["context"] = body[max(0, m.start() - 15):min(len(body), m.end() + 10)]
            results.append(r)
    return results
