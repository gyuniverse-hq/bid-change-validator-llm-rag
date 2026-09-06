# -*- coding: utf-8 -*-
"""6-3. 판정 — 코드.

정규화된 값끼리 비교한다. 프로필에 값이 없는 슬롯은 판정 불가로 두고
되묻기 질문을 생성한다(Luna, 없으면 템플릿 폴백).
"""
import re
from datetime import date, timedelta

from llm import get_client
from normalize import normalize_count

# "특급기술자 2인 이상" 형식에서 등급과 필요 인원을 뽑는다 (수치 변환은 normalize)
_STAFF_REQ_RE = re.compile(r"(특급|고급|중급|초급)[^.\n]{0,10}?(\d+\s*[인명])")


_TOKEN_SPLIT_RE = re.compile(r"[0-9]+|[A-Za-z]+|[가-힣]+")


def _name_matches(held, requirement_text):
    """보유 명칭이 요건 문구를 가리키는가 — 표기 차이를 흡수한 토큰 대조.

    구분자(공백·슬래시 등)뿐 아니라 **영문-숫자 경계**도 나눠서 토큰화한다.
    "ISO 27001"과 "ISO27001"(붙여쓰기)이 같은 토큰 ["ISO","27001"]이 되게 해야
    "ISO/IEC 27001"처럼 사이에 다른 글자가 낀 요건과도 맞는다. 구분자로만 나누면
    "ISO27001"이 통째로 한 토큰이 되어 "ISO/IEC 27001"의 어디에도 연속 부분문자열로
    나타나지 않아 매칭이 실패한다.
    """
    tokens = [t for t in _TOKEN_SPLIT_RE.findall(held or "") if len(t) >= 2]
    if not tokens:
        return False
    target = (requirement_text or "").lower()
    return all(t.lower() in target for t in tokens)


def _parse_staff_requirement(raw):
    """요건 원문 → (등급, 필요인원). 특정 못 하면 None (임의 추정 금지)."""
    m = _STAFF_REQ_RE.search(raw or "")
    if not m:
        return None
    norm = normalize_count(m.group(2))
    if norm["parse_status"] != "success":
        return None
    return m.group(1), norm["value"]


def _recent_performance_total(profile, months):
    """최근 N개월 내 완료 실적 합계 (계약금액 기준)."""
    cutoff = date.today() - timedelta(days=months * 30.44)
    total = 0
    best_single = 0
    for perf in (profile or {}).get("실적", []):
        try:
            done = date.fromisoformat(perf.get("완료일", ""))
        except ValueError:
            continue
        if done >= cutoff:
            amt = perf.get("계약금액") or 0
            total += amt
            best_single = max(best_single, amt)
    return total, best_single


def _followup_question(slot):
    """판정 불가 슬롯에 대한 되묻기 질문. Luna 사용, 실패 시 템플릿."""
    template = f"'{slot.get('raw', '')[:60]}' 요건과 관련된 정보가 프로필에 없습니다. 해당 요건을 충족하시나요?"
    client = get_client("luna")
    if not client.available:
        return template
    try:
        q = client.chat(
            "입찰 담당자에게 부족한 프로필 정보를 확인하는 한 문장짜리 정중한 질문을 만들어라. 질문 한 문장만 출력.",
            f"요건 원문: {slot.get('raw', '')}")
        return q.strip().splitlines()[0][:200]
    except Exception:
        return template


def judge_slots(slots, profile):
    """슬롯별 판정. [{slot, verdict("충족"|"미충족"|"판정 불가"), 근거, 되묻기?}]"""
    results = []
    for slot in slots:
        r = {"slot": slot, "verdict": "판정 불가", "근거": ""}
        stype = slot.get("유형")

        if not profile:
            r["근거"] = "회사 프로필 없음"
            r["되묻기"] = _followup_question(slot)
            results.append(r)
            continue

        if stype == "실적요건":
            amt = slot.get("금액_norm") or {}
            period = slot.get("기간_norm") or {}
            # 프로필에 실적 키가 아예 없는 것과 실적이 0건인 것은 다르다.
            # 전자는 "정보가 없음"이므로 미충족으로 단정하지 말고 되물어야 한다.
            if "실적" not in profile:
                r["근거"] = "프로필에 실적 정보 없음"
                r["되묻기"] = _followup_question(slot)
                results.append(r)
                continue
            if amt.get("parse_status") == "success" and amt.get("value") is not None:
                months = period.get("value") if period.get("parse_status") == "success" else None
                if months is None:
                    r["근거"] = "기간 정규화 실패 — 전체 실적으로 판정 불가 처리"
                    r["되묻기"] = _followup_question(slot)
                else:
                    total, best = _recent_performance_total(profile, months)
                    need = amt["value"]
                    # 단건/합산 기준이 명시되지 않으면 보수적으로 단건 기준 우선 확인
                    if best >= need:
                        r.update(verdict="충족",
                                 근거=f"최근 {months:.0f}개월 최대 단건 실적 {best:,.0f}원 ≥ {need:,.0f}원")
                    elif total >= need:
                        r.update(verdict="판정 불가",
                                 근거=f"단건 최대 {best:,.0f}원 < {need:,.0f}원이나 합산 {total:,.0f}원은 충족 — 단건/합산 기준 확인 필요")
                        r["되묻기"] = "해당 실적요건이 단일 계약 기준인지 합산 기준인지 확인해 주시겠어요?"
                    else:
                        r.update(verdict="미충족",
                                 근거=f"최근 {months:.0f}개월 실적 합산 {total:,.0f}원 < 요구 {need:,.0f}원")
            else:
                r["근거"] = "금액 정규화 실패 — 확인 불가"
                r["되묻기"] = _followup_question(slot)

        elif stype == "면허요건":
            raw = slot.get("raw", "")
            if "보유면허" not in profile:
                r["근거"] = "프로필에 보유면허 정보 없음"
                r["되묻기"] = _followup_question(slot)
            else:
                lics = profile.get("보유면허") or []
                hit = [l for l in lics if _name_matches(l, raw)]
                if hit:
                    r.update(verdict="충족", 근거=f"보유면허 {hit} 일치")
                else:
                    r.update(verdict="판정 불가",
                             근거=f"보유면허 {lics} 중 원문과 일치 항목 없음 — 명칭 확인 필요")
                    r["되묻기"] = _followup_question(slot)

        elif stype == "지역요건":
            region = profile.get("소재지역", "")
            raw = slot.get("raw", "")
            if region and (region in raw or region[:2] in raw):
                r.update(verdict="충족", 근거=f"소재지역 '{region}' 명시 지역과 일치")
            elif any(t in raw for t in ("전국", "제한없음", "제한 없음")):
                r.update(verdict="충족", 근거="지역 제한 없음")
            else:
                r["근거"] = f"소재지역 '{region}'과 요건 문언 불일치 여부 확인 필요"
                r["되묻기"] = _followup_question(slot)

        elif stype == "인증요건":
            raw = slot.get("raw", "")
            if "보유인증" not in profile:
                r["근거"] = "프로필에 보유인증 정보 없음"
                r["되묻기"] = _followup_question(slot)
            else:
                certs = profile.get("보유인증") or []
                hit = [c for c in certs if _name_matches(c, raw)]
                if hit:
                    r.update(verdict="충족", 근거=f"보유인증 {hit} 일치")
                elif certs:
                    r["근거"] = f"보유인증 {certs} 중 요구 인증 확인 안 됨"
                    r["되묻기"] = _followup_question(slot)
                else:
                    r.update(verdict="미충족", 근거="보유인증 없음(프로필에 빈 목록으로 명시)")

        elif stype == "인력요건":
            req = _parse_staff_requirement(slot.get("raw", ""))
            if "기술인력" not in profile:
                r["근거"] = "프로필에 기술인력 정보 없음"
                r["되묻기"] = _followup_question(slot)
            elif req is None:
                r["근거"] = "요건에서 등급·인원을 특정하지 못함 — 담당자 확인 필요"
                r["되묻기"] = _followup_question(slot)
            else:
                grade, need = req
                have = (profile.get("기술인력") or {}).get(grade)
                if have is None:
                    r["근거"] = f"프로필에 '{grade}' 인력 수 정보 없음"
                    r["되묻기"] = _followup_question(slot)
                elif have >= need:
                    r.update(verdict="충족", 근거=f"{grade} 보유 {have}인 ≥ 요구 {need}인")
                else:
                    r.update(verdict="미충족", 근거=f"{grade} 보유 {have}인 < 요구 {need}인")

        else:  # 기타요건 — 프로토타입은 되묻기로 처리
            r["근거"] = "자동 판정 미지원 유형 — 담당자 확인 필요"
            r["되묻기"] = _followup_question(slot)

        results.append(r)
    return results
