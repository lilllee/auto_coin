from __future__ import annotations

import pytest

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


# ---- atomic_update ----


def test_atomic_update_basic(tmp_path):
    """atomic_update가 load → fn → save를 수행한다."""
    store = OrderStore(tmp_path / "state.json")
    store.save(State(daily_pnl_ratio=0.01))

    result = store.atomic_update(lambda s: State(
        position=s.position,
        orders=s.orders,
        daily_pnl_ratio=s.daily_pnl_ratio + 0.02,
        daily_pnl_date=s.daily_pnl_date,
        last_exit_at=s.last_exit_at,
    ))

    assert result.daily_pnl_ratio == 0.03
    assert store.load().daily_pnl_ratio == 0.03


def test_atomic_update_sequential_no_lost_update(tmp_path):
    """연속 두 번 update 시 두 번째가 첫 번째 결과를 반영한다."""
    store = OrderStore(tmp_path / "state.json")
    rec1 = OrderRecord(uuid="u1", side="buy", market="KRW-BTC", krw_amount=50_000,
                       volume=0.001, price=50_000_000.0, placed_at=now_iso(), status="paper")
    rec2 = OrderRecord(uuid="u2", side="sell", market="KRW-BTC", krw_amount=50_000,
                       volume=0.001, price=51_000_000.0, placed_at=now_iso(), status="paper")

    store.atomic_update(lambda s: State(orders=[*s.orders, rec1]))
    store.atomic_update(lambda s: State(orders=[*s.orders, rec2]))

    loaded = store.load()
    assert len(loaded.orders) == 2
    assert loaded.orders[0].uuid == "u1"
    assert loaded.orders[1].uuid == "u2"


def test_atomic_update_exception_releases_lock(tmp_path):
    """fn에서 예외 발생 시 lock이 풀리고 이후 작업이 가능해야 한다."""
    store = OrderStore(tmp_path / "state.json")
    store.save(State(daily_pnl_ratio=0.05))

    def bad_fn(state):
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        store.atomic_update(bad_fn)

    # lock이 풀렸으므로 이후 정상 작업 가능
    result = store.atomic_update(lambda s: State(
        daily_pnl_ratio=s.daily_pnl_ratio + 0.01,
    ))
    assert result.daily_pnl_ratio == pytest.approx(0.06)


def test_atomic_update_concurrent_threads(tmp_path):
    """두 스레드가 동시에 update해도 모든 변경이 보존된다."""
    import threading

    store = OrderStore(tmp_path / "state.json")
    store.save(State())

    def append_order(order_id):
        def _fn(state):
            rec = OrderRecord(
                uuid=order_id, side="buy", market="KRW-BTC",
                krw_amount=10_000, volume=0.001, price=100.0,
                placed_at=now_iso(), status="paper",
            )
            return State(orders=[*state.orders, rec])
        store.atomic_update(_fn)

    threads = [threading.Thread(target=append_order, args=(f"t-{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = store.load()
    # atomic_update 덕분에 10개 모두 보존
    assert len(loaded.orders) == 10
    uuids = {o.uuid for o in loaded.orders}
    assert uuids == {f"t-{i}" for i in range(10)}
