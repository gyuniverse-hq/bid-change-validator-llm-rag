# -*- coding: utf-8 -*-
"""되묻기 답변 해석 — 자연어 답변을 회사 프로필 필드로 변환한다 (Luna).

역할 경계는 슬롯추출(6-2단계)과 동일하다:
  - LLM은 **산문 → 정형 필드 변환만** 한다. "6억 1천만원" 같은 원문 문자열만 뽑는다.
  - **숫자·날짜 변환은 코드**가 한다 (normalize 모듈 + 여기의 날짜 파서).
  - **판정은 절대 하지 않는다.** 충족/미충족은 eligibility/judge.py가 정한다.
  - structured output으로 스키마 이탈을 디코딩 단계에서 차단한다.

환각 방지가 특히 중요하다. 담당자가 "네 있습니다"라고만 답했는데 LLM이
금액을 지어내면 잘못된 충족 판정으로 이어진다. 그래서 **숫자를 담은 필드는
답변 원문에 실제로 등장하는지 코드가 대조**하고, 없으면 폐기한다.
"""
import re
from datetime import date

from llm import get_client
from normalize import normalize_count, normalize_value

_ANSWER_SCHEMA = {
    "name": "followup_answer",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer_type": {
                "type": "string",
                "enum": ["제공", "해당없음", "모름", "무관"],
                "description": ("제공=값을 알려줌, 해당없음=없다고 답함, "
                                "모름=확인이 필요하다고 답함, 무관=질문과 무관한 답변"),
            },
            "보유인증": {"type": "array", "items": {"type": "string"}},
            "보유면허": {"type": "array", "items": {"type": "string"}},
            "소재지역": {"type": ["string", "null"]},
            "실적": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "사업명": {"type": ["string", "null"]},
                        "발주처": {"type": ["string", "null"]},
                        "금액_raw": {"type": ["string", "null"],
                                    "description": "금액 원문 그대로. 예: '6억 1천만원'. 숫자로 바꾸지 마라"},
                        "완료일_raw": {"type": ["string", "null"],
                                     "description": "완료 시점 원문 그대로. 예: '작년 8월', '2024-08-30'"},
                    },
                    "required": ["사업명", "발주처", "금액_raw", "완료일_raw"],
                },
            },
            "기술인력": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "등급": {"type": "string", "description": "특급/고급/중급/초급 중 하나"},
                        "인원_raw": {"type": ["string", "null"],
                                   "description": "인원 원문 그대로. 예: '1명'. 숫자로 바꾸지 마라"},
                    },
                    "required": ["등급", "인원_raw"],
                },
            },
        },
        "required": ["answer_type", "보유인증", "보유면허", "소재지역", "실적", "기술인력"],
    },
}

_SYSTEM = """너는 입찰 담당자의 답변을 회사 프로필 필드로 옮겨 적는 도구다. 규칙:
1. 답변에 **실제로 적힌 내용만** 옮긴다. 추측하거나 값을 지어내지 마라.
2. 금액·기간·인원은 **원문 문자열 그대로** 담는다. 숫자로 변환하지 마라.
   ("6억 1천만원"을 610000000으로 바꾸지 마라)
3. 담당자가 "없다"고 하면 answer_type=해당없음, 값 배열은 비운다.
4. "모르겠다/확인해보겠다"면 answer_type=모름, 값 배열은 비운다.
5. 질문과 상관없는 답변이면 answer_type=무관.
6. 판정하지 마라. 요건을 충족하는지 여부는 네가 결정할 일이 아니다."""


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def _appears_in(value, answer_text):
    """숫자를 담은 값이 답변 원문에 실제로 있는지 — 환각 차단."""
    return bool(value) and _squash(value) in _squash(answer_text)


def _loosely_appears(value, answer_text):
    """명칭류(인증·면허·지역)는 표기 차이를 허용한 느슨한 대조.

    "ISO 27001"이라고 답해도 LLM이 "ISO/IEC 27001"로 정규화할 수 있으므로,
    2글자 이상 토큰 하나라도 답변에 있으면 인정한다.
    """
    if not value:
        return False
    squashed = _squash(answer_text)
    tokens = [t for t in re.split(r"[^0-9A-Za-z가-힣]+", value) if len(t) >= 2]
    if not tokens:
        return _squash(value) in squashed
    return any(t in squashed or t.lower() in squashed.lower() for t in tokens)


_REL_YEAR = {"올해": 0, "금년": 0, "작년": -1, "지난해": -1, "재작년": -2}


def parse_date_raw(raw):
    """완료일 원문 → date. 해석 불가 시 None (임의 추정 금지).

    날짜 변환도 LLM이 아니라 코드가 한다.
    """
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"(\d{4})[-.\/년]\s*(\d{1,2})[-.\/월]\s*(\d{1,2})", text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{4})[-.\/년]\s*(\d{1,2})\s*월?", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return date(y, mo, 28)  # 일자 미상 — 월말 근처로 보수 처리
    for word, delta in _REL_YEAR.items():
        if word in text:
            y = date.today().year + delta
            mm = re.search(r"(\d{1,2})\s*월", text)
            mo = int(mm.group(1)) if mm and 1 <= int(mm.group(1)) <= 12 else 12
            return date(y, mo, 28)
    m = re.fullmatch(r"\s*(\d{4})\s*년?\s*", text)
    if m:
        return date(int(m.group(1)), 12, 28)
    return None


def parse_answer(slot, question, answer_text):
    """자연어 답변 → 프로필 갱신안.

    반환:
    {
      "answer_type": "제공"|"해당없음"|"모름"|"무관"|"llm_unavailable"|"failed",
      "updates": {필드: 값},        # 프로필에 병합할 내용
      "rejected": [str],            # 환각 의심으로 폐기한 항목
      "notes": str,
    }
    """
    client = get_client("luna")
    if not client.available:
        return {"answer_type": "llm_unavailable", "updates": {}, "rejected": [],
                "notes": "OPENAI_API_KEY 미설정 — 답변 해석 불가"}

    user = (f"[확인하려는 요건]\n{slot.get('raw', '')}\n\n"
            f"[담당자에게 한 질문]\n{question}\n\n"
            f"[담당자의 답변]\n{answer_text}")
    try:
        out = client.chat(_SYSTEM, user, json_schema=_ANSWER_SCHEMA)
    except Exception as e:
        return {"answer_type": "failed", "updates": {}, "rejected": [],
                "notes": f"LLM 호출 실패: {e}"}

    atype = out.get("answer_type", "무관")
    updates, rejected = {}, []

    # 실적 — 금액·완료일은 답변 원문 대조 후 코드가 변환
    perfs = []
    for p in out.get("실적", []):
        amt_raw = p.get("금액_raw")
        if amt_raw and not _appears_in(amt_raw, answer_text):
            rejected.append(f"실적 금액 '{amt_raw}' — 답변 원문에 없음(환각 의심)")
            continue
        done_raw = p.get("완료일_raw")
        if done_raw and not _appears_in(done_raw, answer_text):
            rejected.append(f"실적 완료일 '{done_raw}' — 답변 원문에 없음(환각 의심)")
            done_raw = None
        if not amt_raw:
            rejected.append("실적 금액이 답변에 없음 — 판정 보류 유지")
            continue
        norm = normalize_value(amt_raw)          # 숫자 변환은 코드
        if norm["parse_status"] != "success" or norm.get("value") is None:
            rejected.append(f"실적 금액 '{amt_raw}' 정규화 실패 — 반영하지 않음")
            continue
        done = parse_date_raw(done_raw)          # 날짜 변환도 코드
        if done is None:
            rejected.append(f"실적 완료일 '{done_raw}' 해석 불가 — 최근 실적 판정 불가")
            continue
        perfs.append({
            "사업명": p.get("사업명") or "(담당자 답변)",
            "발주처": p.get("발주처") or "",
            "계약금액": norm["value"],
            "계약금액_raw": amt_raw,
            "완료일": done.isoformat(),
            "완료일_raw": done_raw,
            "출처": "되묻기 답변",
        })
    if perfs:
        updates["실적"] = perfs
    elif atype == "해당없음" and slot.get("유형") == "실적요건":
        updates["실적"] = []   # 실적이 없다고 명시 → 빈 목록(판정 가능 상태)

    # 인증·면허 — 명칭은 느슨하게 대조
    for field in ("보유인증", "보유면허"):
        vals = [v for v in out.get(field, []) if v]
        kept = []
        for v in vals:
            if _loosely_appears(v, answer_text):
                kept.append(v)
            else:
                rejected.append(f"{field} '{v}' — 답변 원문과 대응 안 됨(환각 의심)")
        if kept:
            updates[field] = kept
        elif atype == "해당없음" and slot.get("유형") in ("인증요건", "면허요건"):
            updates[field] = []

    # 지역
    region = out.get("소재지역")
    if region and _loosely_appears(region, answer_text):
        updates["소재지역"] = region
    elif region:
        rejected.append(f"소재지역 '{region}' — 답변 원문과 대응 안 됨(환각 의심)")

    # 기술인력 — 인원 수 변환은 코드
    staff = {}
    for s in out.get("기술인력", []):
        grade, cnt_raw = s.get("등급"), s.get("인원_raw")
        if not grade or not cnt_raw:
            continue
        if not _appears_in(cnt_raw, answer_text):
            rejected.append(f"기술인력 '{grade} {cnt_raw}' — 답변 원문에 없음(환각 의심)")
            continue
        norm = normalize_count(cnt_raw)
        if norm["parse_status"] != "success":
            rejected.append(f"기술인력 '{cnt_raw}' 정규화 실패 — 반영하지 않음")
            continue
        staff[grade] = norm["value"]
    if staff:
        updates["기술인력"] = staff
    elif atype == "해당없음" and slot.get("유형") == "인력요건":
        updates["기술인력"] = {}

    return {"answer_type": atype, "updates": updates, "rejected": rejected, "notes": ""}


def apply_updates(profile, updates):
    """프로필에 갱신안을 병합한 새 dict 반환 (원본 불변).

    실적은 누적, 인증·면허는 합집합, 나머지는 치환.
    """
    merged = dict(profile)
    for key, val in updates.items():
        if key == "실적":
            if val:
                merged["실적"] = list(merged.get("실적") or []) + val
            else:
                merged["실적"] = []
        elif key in ("보유인증", "보유면허"):
            if val:
                existing = list(merged.get(key) or [])
                merged[key] = existing + [v for v in val if v not in existing]
            else:
                merged[key] = []
        elif key == "기술인력":
            if val:
                cur = dict(merged.get("기술인력") or {})
                cur.update(val)
                merged["기술인력"] = cur
            else:
                merged["기술인력"] = {}
        else:
            merged[key] = val
    return merged
