from hermes_orchestrator.services.health_monitor import AdaptiveHealthChecker


def test_base_interval_on_first_call():
    checker = AdaptiveHealthChecker()
    interval = checker.next_interval("agent-1", last_check_ok=True)
    assert interval == 5.0


def test_increases_on_healthy():
    checker = AdaptiveHealthChecker()
    checker.next_interval("a1", True)
    interval = checker.next_interval("a1", True)
    assert interval > 5.0
    assert interval <= 30.0


def test_decreases_on_unhealthy():
    checker = AdaptiveHealthChecker()
    checker.next_interval("a1", True)
    checker.next_interval("a1", True)
    healthy_interval = checker.next_interval("a1", True)
    unhealthy_interval = checker.next_interval("a1", False)
    assert unhealthy_interval < healthy_interval
    assert unhealthy_interval >= 2.0


def test_max_interval_cap():
    checker = AdaptiveHealthChecker()
    for _ in range(50):
        checker.next_interval("a1", True)
    interval = checker.next_interval("a1", True)
    assert interval <= 30.0


def test_min_interval_floor():
    checker = AdaptiveHealthChecker()
    for _ in range(50):
        checker.next_interval("a1", False)
    interval = checker.next_interval("a1", False)
    assert interval >= 2.0


def test_min_current_interval():
    checker = AdaptiveHealthChecker()
    checker.next_interval("a1", True)
    checker.next_interval("a2", False)
    assert checker.min_current_interval() >= 2.0
