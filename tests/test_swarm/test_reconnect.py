from swarm.reconnect import ReconnectPolicy, compute_backoff


def test_compute_backoff_increases():
    policy = ReconnectPolicy(initial_delay=1.0, max_delay=60.0, multiplier=2.0, jitter=0.1)
    delays = [compute_backoff(policy, attempt) for attempt in range(6)]
    # Without jitter: 1, 2, 4, 8, 16, 32
    for i in range(1, len(delays)):
        assert delays[i] >= delays[i - 1] * (1.0 - policy.jitter)


def test_compute_backoff_capped():
    policy = ReconnectPolicy(initial_delay=1.0, max_delay=10.0, multiplier=2.0, jitter=0.0)
    assert compute_backoff(policy, 100) == 10.0


def test_compute_backoff_jitter_range():
    policy = ReconnectPolicy(initial_delay=1.0, max_delay=60.0, multiplier=2.0, jitter=0.1)
    for _ in range(100):
        d = compute_backoff(policy, 0)
        assert 0.9 <= d <= 1.1  # 1.0 +/- 10%
