"""표시용 포매터.

KRW 마켓은 티커별로 가격 자릿수가 크게 다르다:
- KRW-BTC ≈ 100,000,000 (정수)
- KRW-XRP ≈ 2,000       (정수)
- KRW-DRIFT ≈ 100       (정수, 하지만 단위가 작아 소수점이 유의미할 수 있음)
- KRW-PEPE ≈ 0.02       (소수점 필수)
- KRW-SHIB ≈ 0.0001     (소수점 6자리 이상)

`.0f`로 고정하면 저가 종목은 전부 0이나 1자리 정수로 찍혀 움직임을 못 본다.
본 함수는 가격 크기에 따라 소수점 자릿수를 자동 조정한다.
"""

from __future__ import annotations

import math


def format_price(value: float | int | None) -> str:
    """가격을 크기에 맞는 소수점 자릿수로 포매팅.

    규칙:
        >= 100        : 정수 + 콤마        (예: 3,352,000)
        10 ~ 100      : 소수점 1자리        (예: 99.1)
        1 ~ 10        : 소수점 2자리        (예: 9.49)
        0.01 ~ 1      : 소수점 4자리        (예: 0.0421)
        0.0001 ~ 0.01 : 소수점 6자리        (예: 0.002134)
        그 이하       : 소수점 8자리        (예: 0.00001234)
        0             : "0"
        None/NaN/inf  : repr 그대로 반환 (방어적)

    양수·음수 모두 처리. abs(value) 기준으로 판단.
    """
    if value is None:
        return "None"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v) or math.isinf(v):
        return str(v)
    if v == 0:
        return "0"

    abs_v = abs(v)
    if abs_v >= 100:
        return f"{v:,.0f}"
    if abs_v >= 10:
        return f"{v:,.1f}"
    if abs_v >= 1:
        return f"{v:,.2f}"
    if abs_v >= 0.01:
        return f"{v:.4f}"
    if abs_v >= 0.0001:
        return f"{v:.6f}"
    return f"{v:.8f}"
