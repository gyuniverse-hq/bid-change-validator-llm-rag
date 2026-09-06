# -*- coding: utf-8 -*-
"""6-1. API 필드 기반 참가자격 판정 — 코드만, LLM 불필요.

회사 프로필 × 공고 API 응답 필드(면허제한, 참가가능지역, 추정가격 등) 직접 비교.
정보가 없으면 임의 판정하지 않고 "확인 불가"로 둔다.
"""


def _v(item, *keys):
    for k in keys:
        val = item.get(k)
        if val not in (None, ""):
            return str(val).strip()
    return None


def judge_api_fields(item, profile):
    """[{항목, verdict("충족"|"미충족"|"확인 불가"), 근거}] 반환."""
    results = []

    # 참가가능지역
    region_limit = _v(item, "prtcptPsblRgnNm", "prtcptLmtRgnNm")
    my_region = (profile or {}).get("소재지역")
    if not region_limit or any(t in region_limit for t in ("전국", "제한없음", "제한 없음")):
        results.append({"항목": "참가가능지역", "verdict": "충족",
                        "근거": f"지역제한 없음(공고값: {region_limit or '미기재'})"})
    elif not my_region:
        results.append({"항목": "참가가능지역", "verdict": "확인 불가",
                        "근거": "프로필에 소재지역 정보 없음"})
    else:
        ok = any(tok and tok in region_limit
                 for tok in (my_region, my_region[:2]))
        results.append({
            "항목": "참가가능지역",
            "verdict": "충족" if ok else "미충족",
            "근거": f"공고 지역제한 '{region_limit}' vs 소재지 '{my_region}'",
        })

    # 면허제한
    lic_limit = _v(item, "lcnsLmtNm")
    my_lics = (profile or {}).get("보유면허") or []
    if not lic_limit:
        results.append({"항목": "면허제한", "verdict": "충족", "근거": "면허제한 미기재"})
    elif not my_lics:
        results.append({"항목": "면허제한", "verdict": "확인 불가",
                        "근거": "프로필에 보유면허 정보 없음"})
    else:
        ok = any(lic in lic_limit for lic in my_lics)
        results.append({
            "항목": "면허제한",
            "verdict": "충족" if ok else "미충족",
            "근거": f"공고 면허제한 '{lic_limit}' vs 보유 {my_lics}",
        })

    # 참고 정보 — 추정가격/기초금액 (판정이 아니라 맥락 제공)
    presmpt = _v(item, "presmptPrce")
    bss = _v(item, "bssamt", "bssAmt")
    info = []
    if presmpt:
        info.append(f"추정가격 {int(float(presmpt)):,}원")
    if bss:
        info.append(f"기초금액 {int(float(bss)):,}원")
    if info:
        results.append({"항목": "공고금액(참고)", "verdict": "정보",
                        "근거": ", ".join(info)})
    return results
