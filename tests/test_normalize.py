# -*- coding: utf-8 -*-
"""normalize 모듈 단위 테스트 — 스펙의 필수 케이스 전부 포함.

이 테스트가 깨지면 LLM 성능과 무관하게 전체 파이프라인이 틀어진다.
"""
import pytest

from normalize import (
    parse_korean_number,
    normalize_amount,
    normalize_period,
    normalize_percent,
    normalize_count,
    normalize_value,
    extract_values,
)


class TestParseKoreanNumber:
    def test_arabic_with_group_units(self):
        assert parse_korean_number("3억 5천만") == 350_000_000

    def test_comma_number(self):
        assert parse_korean_number("500,000,000") == 500_000_000

    def test_hangul_numeral(self):
        assert parse_korean_number("오억") == 500_000_000

    def test_mixed_small_units(self):
        assert parse_korean_number("1억 2천 3백만") == 123_000_000

    def test_plain_arabic(self):
        assert parse_korean_number("42") == 42

    def test_jo_unit(self):
        assert parse_korean_number("1조 2억") == 1_000_200_000_000

    def test_none_on_garbage(self):
        assert parse_korean_number("없음") is None
        assert parse_korean_number("") is None


class TestNormalizeAmount:
    def test_composite_unit(self):
        """3억 5천만원 — 복합 단위, 억·천만 각각 계산 후 합산."""
        r = normalize_amount("3억 5천만원")
        assert r["parse_status"] == "success"
        assert r["value"] == 350_000_000
        assert r["unit"] == "KRW"
        assert r["raw"] == "3억 5천만원"

    def test_comma_removal(self):
        r = normalize_amount("500,000,000원")
        assert r["value"] == 500_000_000
        assert r["parse_status"] == "success"

    def test_paren_note_preserved(self):
        """5억원(부가세 포함) — 괄호 내 부가정보 분리 보존."""
        r = normalize_amount("5억원(부가세 포함)")
        assert r["value"] == 500_000_000
        assert r["note"] == "부가세 포함"
        assert r["raw"] == "5억원(부가세 포함)"

    def test_hangul_numeral_geum_jeong(self):
        """금 오억원정 — 한글 수사."""
        r = normalize_amount("금 오억원정")
        assert r["value"] == 500_000_000
        assert r["parse_status"] == "success"

    def test_range(self):
        """10억원 이상 20억원 미만 — 단일값이 아닌 구간으로 저장."""
        r = normalize_amount("10억원 이상 20억원 미만")
        assert r["parse_status"] == "success"
        assert r["value"] is None
        assert r["range"]["min"] == 1_000_000_000
        assert r["range"]["min_op"] == ">="
        assert r["range"]["max"] == 2_000_000_000
        assert r["range"]["max_op"] == "<"

    def test_comparator_isang(self):
        r = normalize_amount("5억원 이상")
        assert r["value"] == 500_000_000
        assert r["op"] == ">="

    def test_comparator_miman(self):
        r = normalize_amount("3억원 미만")
        assert r["op"] == "<"

    def test_label_estimated_price(self):
        """추정가격 5억원 vs 기초금액 5억원 — 라벨 보존 (의미가 다름)."""
        r1 = normalize_amount("추정가격 5억원")
        r2 = normalize_amount("기초금액 5억원")
        assert r1["value"] == r2["value"] == 500_000_000
        assert r1["label"] == "추정가격"
        assert r2["label"] == "기초금액"

    def test_failed_no_guess(self):
        """파싱 실패 시 임의 추정 금지 — failed로 기록."""
        r = normalize_amount("협의하여 정함")
        assert r["parse_status"] == "failed"
        assert r["value"] is None

    def test_raw_always_preserved(self):
        raw = "금 삼억원정(부가가치세 별도)"
        r = normalize_amount(raw)
        assert r["raw"] == raw
        assert r["value"] == 300_000_000


class TestNormalizePeriod:
    def test_36_months(self):
        r = normalize_period("36개월")
        assert r["value"] == 36
        assert r["unit"] == "MONTH"

    def test_3_years_equals_36_months(self):
        """36개월 / 3년 — 둘 다 36개월로 정규화."""
        r = normalize_period("3년")
        assert r["value"] == 36
        assert r["unit"] == "MONTH"

    def test_1_year(self):
        r = normalize_period("1년")
        assert r["value"] == 12

    def test_days(self):
        r = normalize_period("14일 이내")
        assert r["value"] == pytest.approx(14 / 30, abs=0.01)
        assert r["op"] == "<="

    def test_weeks(self):
        r = normalize_period("2주")
        assert r["value"] == 0.5

    def test_comparator_inae(self):
        r = normalize_period("최근 3년 이내")
        assert r["value"] == 36
        assert r["op"] == "<="

    def test_failed(self):
        r = normalize_period("상당 기간")
        assert r["parse_status"] == "failed"
        assert r["value"] is None


class TestNormalizePercent:
    def test_bunui(self):
        """100분의 30 — 백분율 표기 -> PERCENT 30."""
        r = normalize_percent("100분의 30")
        assert r["value"] == 30
        assert r["unit"] == "PERCENT"

    def test_bunui_2(self):
        """100분의 2 — 하자보수보증금율."""
        r = normalize_percent("계약금액의 100분의 2")
        assert r["value"] == 2

    def test_percent_sign(self):
        r = normalize_percent("30%")
        assert r["value"] == 30

    def test_bunui_1000(self):
        """1000분의 5 (지체상금율류 표기)."""
        r = normalize_percent("1000분의 5")
        assert r["value"] == 0.5

    def test_failed(self):
        r = normalize_percent("일정 비율")
        assert r["parse_status"] == "failed"


class TestNormalizeCount:
    def test_persons_isang(self):
        r = normalize_count("2인 이상")
        assert r["value"] == 2
        assert r["unit"] == "PERSON"
        assert r["op"] == ">="

    def test_myeong(self):
        r = normalize_count("특급기술자 3명")
        assert r["value"] == 3

    def test_hangul_numeral(self):
        r = normalize_count("오 명")
        assert r["value"] == 5

    def test_failed(self):
        r = normalize_count("충분한 인력")
        assert r["parse_status"] == "failed"
        assert r["value"] is None


class TestNormalizeValueAutoDetect:
    def test_amount(self):
        r = normalize_value("3억 5천만원 이상")
        assert r["unit"] == "KRW"
        assert r["value"] == 350_000_000
        assert r["op"] == ">="

    def test_period(self):
        r = normalize_value("3년")
        assert r["unit"] == "MONTH"
        assert r["value"] == 36

    def test_percent(self):
        r = normalize_value("100분의 30")
        assert r["unit"] == "PERCENT"
        assert r["value"] == 30

    def test_unknown_failed(self):
        r = normalize_value("성실히 수행한다")
        assert r["parse_status"] == "failed"


class TestExtractValues:
    def test_finds_period_in_clause(self):
        text = "하자보수 기간은 검사 완료 후 3년간으로 한다."
        vals = extract_values(text)
        months = [v for v in vals if v["unit"] == "MONTH"]
        assert any(v["value"] == 36 for v in months)

    def test_finds_percent_in_clause(self):
        text = "지체상금은 계약금액의 100분의 30을 초과할 수 없다."
        vals = extract_values(text)
        pcts = [v for v in vals if v["unit"] == "PERCENT"]
        assert any(v["value"] == 30 for v in pcts)

    def test_empty(self):
        assert extract_values("") == []
