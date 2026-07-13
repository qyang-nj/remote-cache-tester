from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import fmean
from typing import Any, Iterable


MEBIBYTE = 1024 * 1024


@dataclass(frozen=True)
class Blob:
    size_bytes: int
    target: str

    @property
    def size_mb(self) -> int:
        return self.size_bytes // MEBIBYTE


BLOBS = tuple(
    Blob(size_mb * MEBIBYTE, f"//:File_{size_mb}MB")
    for size_mb in (1, 10, 30, 50, 100, 200)
)

DISTINCT_50MB_BLOBS = tuple(
    Blob(50 * MEBIBYTE, f"//:File_50MB_{index}") for index in range(1, 9)
)


@dataclass(frozen=True)
class RpcCall:
    method: str
    status_code: int
    start_time: float
    end_time: float
    bytes_read: int = 0
    target_id: str = ""
    resource_name: str = ""

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass(frozen=True)
class Statistics:
    count: int
    minimum: float
    mean: float
    p50: float
    p90: float
    p99: float
    maximum: float

    @classmethod
    def from_values(cls, values: Iterable[float]) -> "Statistics":
        ordered = sorted(values)
        if not ordered:
            raise ValueError("at least one value is required")
        return cls(
            count=len(ordered),
            minimum=ordered[0],
            mean=fmean(ordered),
            p50=_percentile(ordered, 0.50),
            p90=_percentile(ordered, 0.90),
            p99=_percentile(ordered, 0.99),
            maximum=ordered[-1],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SuiteResult:
    name: str
    status: str = "passed"
    summary: list[dict[str, Any]] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def failed(cls, name: str, error: str) -> "SuiteResult":
        return cls(name=name, status="failed", error=error)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interval_span(calls: Iterable[RpcCall]) -> float:
    calls = tuple(calls)
    if not calls:
        return 0.0
    return max(call.end_time for call in calls) - min(call.start_time for call in calls)


def max_concurrency(calls: Iterable[RpcCall]) -> int:
    events: list[tuple[float, int]] = []
    for call in calls:
        events.append((call.start_time, 1))
        events.append((call.end_time, -1))

    active = 0
    maximum = 0
    # Ends sort before starts at the same timestamp, making intervals half-open.
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def _percentile(ordered: list[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
