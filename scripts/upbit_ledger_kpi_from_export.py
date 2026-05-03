"""Codex 0010 — 업비트 한글 paste/CSV export → ledger KPI 변환 CLI.

분석 전용 스크립트. 다음을 절대 하지 않음:

- 업비트 private/account 엔드포인트 호출
- 주문 생성/취소
- live/paper 봇 상태 변경

지원 입력:

1. ``--input <path>`` — 업비트 한글 체결내역 paste 텍스트 파일.
   헤더 컬럼: ``체결시간 / 코인 / 마켓 / 종류 / 거래수량 / 거래단가 /
   거래금액 / 수수료 / 정산금액 / 주문시간`` (탭/2칸 공백/파이프 구분 허용).
2. ``--csv <path>`` — 동일 컬럼의 CSV. 헤더는 한글 또는 영어 alias 허용.
3. stdin — 파이프로 paste 텍스트 입력.

출력: ``--out <path>`` JSON. 미지정 시 stdout JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from auto_coin.web.services.upbit_ledger_kpi import (
    SIDE_BUY,
    SIDE_SELL,
    LedgerEvent,
    compute_ledger_kpi,
    parse_korean_upbit_table,
)

CSV_HEADER_ALIASES = {
    "체결시간": "fill_time",
    "fill_time": "fill_time",
    "timestamp": "fill_time",
    "코인": "asset",
    "asset": "asset",
    "ticker": "asset",
    "마켓": "market",
    "market": "market",
    "종류": "side",
    "side": "side",
    "거래수량": "quantity",
    "quantity": "quantity",
    "volume": "quantity",
    "거래단가": "price",
    "price": "price",
    "거래금액": "gross_krw",
    "gross_krw": "gross_krw",
    "수수료": "fee_krw",
    "fee_krw": "fee_krw",
    "정산금액": "net_krw",
    "net_krw": "net_krw",
    "주문시간": "order_time",
    "order_time": "order_time",
}


def _parse_number(value: str) -> float:
    s = (value or "").strip().replace(",", "")
    if not s or s in ("-", "—"):
        return 0.0
    return float(s)


def _parse_dt(value: str) -> datetime:
    s = (value or "").strip()
    fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized timestamp: {value!r}")


def _side_from_token(token: str) -> str | None:
    s = (token or "").strip().lower()
    if s in {"매수", "buy"}:
        return SIDE_BUY
    if s in {"매도", "sell"}:
        return SIDE_SELL
    return None


def parse_csv_export(path: Path) -> list[LedgerEvent]:
    events: list[LedgerEvent] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return []
        normalized = {f: CSV_HEADER_ALIASES.get(f.strip(), f.strip()) for f in reader.fieldnames}
        for row in reader:
            mapped = {normalized[k]: v for k, v in row.items() if k in normalized}
            try:
                ts = _parse_dt(mapped.get("fill_time", ""))
                quantity = _parse_number(mapped.get("quantity", ""))
                price = _parse_number(mapped.get("price", ""))
                gross = _parse_number(mapped.get("gross_krw", ""))
                fee = _parse_number(mapped.get("fee_krw", ""))
                net = _parse_number(mapped.get("net_krw", "")) or (
                    gross + fee if _side_from_token(mapped.get("side", "")) == SIDE_BUY
                    else gross - fee
                )
            except ValueError:
                continue
            side = _side_from_token(mapped.get("side", ""))
            if side is None:
                continue
            events.append(LedgerEvent(
                timestamp=ts,
                asset=(mapped.get("asset") or "").strip(),
                market=(mapped.get("market") or "KRW").strip() or None,
                side=side,  # type: ignore[arg-type]
                quantity=quantity,
                price=price,
                gross_krw=gross,
                fee_krw=fee,
                net_krw=net,
                source="csv",
                raw={k: v for k, v in row.items()},
            ))
    return events


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, help="paste 텍스트 파일")
    ap.add_argument("--csv", type=Path, help="CSV 파일")
    ap.add_argument("--out", type=Path, help="출력 JSON 경로 (미지정 시 stdout)")
    ap.add_argument("--summary", action="store_true",
                    help="JSON 대신 사람이 읽기 쉬운 요약을 stdout으로 출력")
    args = ap.parse_args(argv)

    if args.input and args.csv:
        ap.error("--input 과 --csv 는 동시에 지정할 수 없습니다")

    if args.input:
        text = args.input.read_text(encoding="utf-8")
        events = parse_korean_upbit_table(text, source=str(args.input))
    elif args.csv:
        events = parse_csv_export(args.csv)
    else:
        text = sys.stdin.read()
        if not text.strip():
            ap.error("입력이 비어있습니다. --input <file> 또는 --csv <file> 또는 stdin 으로 paste 하세요.")
        events = parse_korean_upbit_table(text, source="stdin")

    result = compute_ledger_kpi(events)
    payload = result.to_dict()

    if args.summary:
        print(_render_summary(payload))
        return 0

    out_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text, encoding="utf-8")
        print(f"wrote {args.out} ({result.parsed_event_count} events, "
              f"{result.matched_trade_count} matched)")
    else:
        print(out_text)
    return 0


def _render_summary(payload: dict) -> str:
    lines = [
        "## Upbit ledger KPI",
        f"period: {payload['period_start']} ~ {payload['period_end']}",
        f"parsed events     : {payload['parsed_event_count']}",
        f"matched trades    : {payload['matched_trade_count']}",
        f"unmatched buys    : {payload['unmatched_buy_count']}",
        f"unmatched sells   : {payload['unmatched_sell_count']}",
        f"realized PnL (KRW): {payload['realized_pnl_krw']:.2f}",
        f"total fee   (KRW) : {payload['total_fee_krw']:.2f}",
        f"win/loss          : {payload['win_count']}/{payload['loss_count']} "
        f"(win_rate {payload['win_rate']:.2f}%)",
        f"avg pnl ratio     : {payload['avg_pnl_ratio'] * 100:.4f}%",
        f"cash flow (KRW)   : {payload['cash_flow_krw']:.2f}",
    ]
    if payload["by_asset"]:
        lines.append("")
        lines.append("### by asset")
        for b in payload["by_asset"]:
            lines.append(
                f"  {b['asset']:<8} matched={b['matched_count']:>3} "
                f"pnl={b['realized_pnl_krw']:>10.2f} KRW "
                f"win/loss={b['win_count']}/{b['loss_count']}"
            )
    if payload["notes"]:
        lines.append("")
        lines.append("### notes")
        for n in payload["notes"]:
            lines.append(f"  - {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
