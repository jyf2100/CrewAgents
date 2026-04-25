from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconnectPolicy:
    initial_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.1


def compute_backoff(policy: ReconnectPolicy, attempt: int) -> float:
    delay = min(policy.initial_delay * (policy.multiplier ** attempt), policy.max_delay)
    jitter_range = delay * policy.jitter
    return max(0.0, delay + random.uniform(-jitter_range, jitter_range))
