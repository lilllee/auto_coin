from __future__ import annotations

from auto_coin.executor.store import OrderRecord, OrderStore, Position, State, now_iso


def test_load_returns_empty_state_when_file_missing(tmp_path):
    store = OrderStore(tmp_path / "state.json")
    s = store.load()
    assert s.position is None
    assert s.orders == []
    assert s.daily_pnl_ratio == 0.0


def test_save_then_load_roundtrip(tmp_path):
    store = OrderStore(tmp_path / "state.json")
    pos = Position(ticker="KRW-BTC", volume=0.001, avg_entry_price=50_000_000.0,
                   entry_uuid="u1", entry_at=now_iso())
    rec = OrderRecord(uuid="u1", side="buy", market="KRW-BTC", krw_amount=50_000,
                      volume=0.001, price=50_000_000.0, placed_at=now_iso(), status="paper")
    state = State(position=pos, orders=[rec], daily_pnl_ratio=-0.01, daily_pnl_date="2026-04-13")
    store.save(state)

    loaded = store.load()
    assert loaded.position == pos
    assert loaded.orders == [rec]
    assert loaded.daily_pnl_ratio == -0.01
    assert loaded.daily_pnl_date == "2026-04-13"


def test_save_creates_parent_directory(tmp_path):
    store = OrderStore(tmp_path / "nested" / "dir" / "state.json")
    store.save(State())
    assert (tmp_path / "nested" / "dir" / "state.json").exists()


def test_load_handles_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = OrderStore(path)
    s = store.load()
    assert s.position is None
    assert s.orders == []


def test_save_is_atomic_no_temp_files_left(tmp_path):
    store = OrderStore(tmp_path / "state.json")
    store.save(State())
    leftover = list(tmp_path.glob(".state-*"))
    assert leftover == []


def test_state_last_exit_at_roundtrip(tmp_path):
    """last_exit_at 필드가 save/load 라운드트립에서 보존된다."""
    store = OrderStore(tmp_path / "state.json")
    ts = "2026-04-14T08:55:00+00:00"
    state = State(last_exit_at=ts)
    store.save(state)
    loaded = store.load()
    assert loaded.last_exit_at == ts
