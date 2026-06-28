"""Rate limiter timing, with injected clock + sleep (no real wall-clock waits)."""

from manaless.http.rate_limiter import RateLimiter


class FakeClock:
    """Deterministic monotonic clock; advances only when its sleep is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _limiter(delay: float, clock: FakeClock) -> RateLimiter:
    return RateLimiter(delay, sleep=clock.sleep, monotonic=clock.monotonic)


def test_first_call_never_sleeps():
    clock = FakeClock()
    _limiter(0.80, clock).wait()
    assert clock.sleeps == []


def test_immediate_second_call_sleeps_full_delay():
    clock = FakeClock()
    limiter = _limiter(0.80, clock)

    limiter.wait()  # t=0, records last_call=0
    limiter.wait()  # no time passed -> owes the full delay

    assert clock.sleeps == [0.80]


def test_partial_elapsed_sleeps_only_remainder():
    clock = FakeClock()
    limiter = _limiter(0.80, clock)

    limiter.wait()
    clock.now = 0.30  # 0.30s elapsed externally
    limiter.wait()

    assert clock.sleeps == [0.80 - 0.30]


def test_enough_elapsed_does_not_sleep():
    clock = FakeClock()
    limiter = _limiter(0.12, clock)

    limiter.wait()
    clock.now = 1.0  # well past the delay
    limiter.wait()

    assert clock.sleeps == []


def test_negative_delay_rejected():
    import pytest

    with pytest.raises(ValueError):
        RateLimiter(-1.0)
