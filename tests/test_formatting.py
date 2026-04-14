from __future__ import annotations

import math

import pytest

from auto_coin.formatting import format_price


@pytest.mark.parametrize("value, expected", [
    # 대형주: 정수 + 콤마
    (3_352_000, "3,352,000"),
    (108_000_000.0, "108,000,000"),
    (1_000, "1,000"),
    (100, "100"),
    # 중형: .1f
    (99.1, "99.1"),
    (87.6, "87.6"),
    (10.0, "10.0"),
    # 소형: .2f
    (9.49, "9.49"),
    (1.23, "1.23"),
    (1.0, "1.00"),
    # 저가 밈: .4f
    (0.0421, "0.0421"),
    (0.5, "0.5000"),
    (0.01, "0.0100"),
    # 초저가 (PEPE/SHIB 영역): .6f / .8f
    (0.002134, "0.002134"),
    (0.0001, "0.000100"),
    (0.00001234, "0.00001234"),
    # zero
    (0, "0"),
    (0.0, "0"),
])
def test_format_price_ranges(value, expected):
    assert format_price(value) == expected


def test_format_price_negative():
    assert format_price(-3_352_000) == "-3,352,000"
    assert format_price(-0.0421) == "-0.0421"


def test_format_price_none_and_bad_types():
    assert format_price(None) == "None"
    assert format_price(float("nan")) == "nan"
    assert format_price(float("inf")) == "inf"


def test_format_price_int_and_float_equivalent():
    assert format_price(1000) == format_price(1000.0)
    assert format_price(42) == format_price(42.0)


def test_format_price_string_input_returns_repr():
    # 방어적 — 잘못된 타입도 raise하지 않고 문자열화
    assert format_price("oops") == "oops"


def test_format_price_preserves_sigfigs_for_small_values():
    """저가 종목의 소수점 변화를 읽을 수 있어야 한다."""
    # 87.6 → 87.5 (0.1 단위 변화가 보임)
    assert format_price(87.6) != format_price(87.5)
    # 0.0421 → 0.0422 (10000분의 1 단위 변화가 보임)
    assert format_price(0.0421) != format_price(0.0422)
    # 0.00001234 → 0.00001235
    assert format_price(0.00001234) != format_price(0.00001235)


def test_format_price_very_large():
    # 업비트에 이런 값은 없지만 방어적
    assert format_price(1e9) == "1,000,000,000"


def test_format_price_type_annotations_accept_int():
    # Python 정수도 그대로 처리
    result = format_price(100)
    assert isinstance(result, str)
    assert result == "100"


def test_format_price_not_math_nan_without_quote():
    # math 모듈이 없으면 어떻게 될지 확인 — 단순 존재 테스트
    assert math.isnan(float("nan"))
