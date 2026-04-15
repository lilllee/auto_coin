from __future__ import annotations

from auto_coin.config import Settings
from auto_coin.main import run_scheduler


class _DummyBot:
    def tick(self):
        return []

    def daily_reset(self):
        return None

    def force_exit_if_holding(self):
        return []

    def daily_report(self):
        return ""

    def watch(self):
        return None

    def heartbeat(self):
        return None


class _DummyNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


class _FakeScheduler:
    instances: list[_FakeScheduler] = []

    def __init__(self, timezone: str) -> None:
        self.timezone = timezone
        self.jobs: list[dict] = []
        _FakeScheduler.instances.append(self)

    def add_job(self, func, trigger, id: str, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "id": id, "kwargs": kwargs})

    def start(self) -> None:
        return None

    def shutdown(self, wait: bool = False) -> None:
        return None


def _job_ids() -> list[str]:
    assert _FakeScheduler.instances, "scheduler was not instantiated"
    return [job["id"] for job in _FakeScheduler.instances[-1].jobs]


def test_run_scheduler_disables_force_exit_for_composite(monkeypatch):
    _FakeScheduler.instances.clear()
    monkeypatch.setattr("auto_coin.main.BlockingScheduler", _FakeScheduler)
    bot = _DummyBot()
    notifier = _DummyNotifier()
    settings = Settings(
        _env_file=None,
        strategy_name="sma200_ema_adx_composite",
        heartbeat_interval_hours=0,
        watch_interval_minutes=1,
    )

    rc = run_scheduler(bot, settings, notifier)

    assert rc == 0
    assert "force_exit" not in _job_ids()
    assert "daily_report" in _job_ids()


def test_run_scheduler_keeps_force_exit_for_volatility_breakout(monkeypatch):
    _FakeScheduler.instances.clear()
    monkeypatch.setattr("auto_coin.main.BlockingScheduler", _FakeScheduler)
    bot = _DummyBot()
    notifier = _DummyNotifier()
    settings = Settings(
        _env_file=None,
        strategy_name="volatility_breakout",
        heartbeat_interval_hours=0,
        watch_interval_minutes=1,
    )

    rc = run_scheduler(bot, settings, notifier)

    assert rc == 0
    assert "force_exit" in _job_ids()
