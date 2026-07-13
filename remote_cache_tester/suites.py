from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import fmean

from .model import (
    BLOBS,
    DISTINCT_50MB_BLOBS,
    MEBIBYTE,
    Blob,
    RpcCall,
    Statistics,
    SuiteResult,
    interval_span,
    max_concurrency,
)
from .runner import BazelRunner, BenchmarkError, BuildResult


GET_ACTION_RESULT = "ActionCache/GetActionResult"
BYTE_STREAM_READ = "ByteStream/Read"
OK = 0
NOT_FOUND = 5
REMOTE_DOWNLOAD_CONFIG = "--config=remote_cache_download"
PREPARE_HINT = 'Run the "prepare" command first.'


@dataclass(frozen=True)
class BenchmarkContext:
    runner: BazelRunner


class BenchmarkSuite(ABC):
    name: str

    @abstractmethod
    def run(self, context: BenchmarkContext) -> SuiteResult:
        pass


class LookupBenchmark(BenchmarkSuite):
    ITERATIONS = 10

    def __init__(self, name: str, expected_status: int, force_miss: bool):
        self.name = name
        self._expected_status = expected_status
        self._force_miss = force_miss

    def run(self, context: BenchmarkContext) -> SuiteResult:
        samples: list[dict[str, float | int]] = []
        for iteration in range(self.ITERATIONS):
            flags = ["--remote_upload_local_results=false"]
            if self._force_miss:
                nonce = uuid.uuid4().hex
                flags.append(f"--action_env=REMOTE_CACHE_TESTER_MISS={nonce}")

            result = context.runner.build([BLOBS[0].target], flags=flags)
            calls = _calls_for_method(result, GET_ACTION_RESULT)
            matching = [
                call for call in calls if call.status_code == self._expected_status
            ]
            if not matching:
                statuses = sorted({call.status_code for call in calls})
                hint = (
                    "run the prepare command first"
                    if not self._force_miss
                    else "the miss action unexpectedly resolved from cache"
                )
                raise BenchmarkError(
                    f"expected GetActionResult status {self._expected_status}, "
                    f"got {statuses or 'no calls'}; {hint}"
                )
            samples.extend(
                {
                    "iteration": iteration + 1,
                    "latency_ms": call.duration_seconds * 1000,
                    "status_code": call.status_code,
                }
                for call in matching
            )

        average_latency_ms = fmean(
            float(sample["latency_ms"]) for sample in samples
        )
        return SuiteResult(
            name=self.name,
            summary=[
                {
                    "request_count": len(samples),
                    "average_latency_ms": average_latency_ms,
                }
            ],
            samples=samples,
        )


class DownloadBenchmark(BenchmarkSuite):
    name = "download"

    def run(self, context: BenchmarkContext) -> SuiteResult:
        samples: list[dict[str, float | int | str]] = []
        summaries: list[dict[str, object]] = []

        for blob in BLOBS:
            blob_samples: list[dict[str, float | int | str]] = []
            result = _remote_download(context.runner, blob.target)
            read_calls = _successful_reads(result, blob.target)
            measurement = _download_measurement(read_calls)
            sample = {
                "iteration": 1,
                "target": blob.target,
                "size_mb": blob.size_mb,
                **measurement,
            }
            samples.append(sample)
            blob_samples.append(sample)

            summaries.append(
                {
                    "target": blob.target,
                    "size_mb": blob.size_mb,
                    "duration_seconds": Statistics.from_values(
                        float(sample["duration_seconds"]) for sample in blob_samples
                    ).to_dict(),
                    "throughput_mbps": Statistics.from_values(
                        float(sample["throughput_mbps"]) for sample in blob_samples
                    ).to_dict(),
                }
            )

        return SuiteResult(name=self.name, summary=summaries, samples=samples)


class ConcurrencyDownloadBenchmark(BenchmarkSuite):
    name = "concurrency"
    WORKER_COUNT = 8
    BLOB_SIZE_MB = 50

    def __init__(
        self,
        shared_blob: Blob | None = None,
        distinct_blobs: tuple[Blob, ...] | None = None,
    ):
        self._shared_blob = shared_blob or next(
            candidate for candidate in BLOBS if candidate.size_mb == self.BLOB_SIZE_MB
        )
        self._distinct_blobs = distinct_blobs or DISTINCT_50MB_BLOBS
        if len(self._distinct_blobs) != self.WORKER_COUNT:
            raise ValueError(
                f"expected {self.WORKER_COUNT} distinct concurrency blobs, "
                f"got {len(self._distinct_blobs)}"
            )
        if any(blob.size_mb != self.BLOB_SIZE_MB for blob in self._distinct_blobs):
            raise ValueError("all concurrency blobs must be 50 MB")

    def run(self, context: BenchmarkContext) -> SuiteResult:
        samples: list[dict[str, float | int | str]] = []
        summaries: list[dict[str, object]] = []

        cases = (
            (
                "same digest",
                (self._shared_blob.target,) * self.WORKER_COUNT,
            ),
            (
                "distinct digests",
                tuple(blob.target for blob in self._distinct_blobs),
            ),
        )
        for case, targets in cases:
            case_samples: list[dict[str, float | int | str]] = []
            read_calls = self._run_wave(context.runner, targets)
            measurement = _download_measurement(read_calls)
            measurement["wave_duration_seconds"] = measurement.pop(
                "duration_seconds"
            )
            measurement["max_active_downloads"] = max_concurrency(read_calls)
            sample = {
                "iteration": 1,
                "case": case,
                "worker_count": self.WORKER_COUNT,
                **measurement,
            }
            samples.append(sample)
            case_samples.append(sample)

            summaries.append(
                {
                    "case": case,
                    "worker_count": self.WORKER_COUNT,
                    "max_active_downloads": max(
                        int(sample["max_active_downloads"])
                        for sample in case_samples
                    ),
                    "wave_duration_seconds": Statistics.from_values(
                        float(sample["wave_duration_seconds"])
                        for sample in case_samples
                    ).to_dict(),
                    "aggregate_throughput_mbps": Statistics.from_values(
                        float(sample["throughput_mbps"])
                        for sample in case_samples
                    ).to_dict(),
                }
            )

        return SuiteResult(name=self.name, summary=summaries, samples=samples)

    def _run_wave(
        self, runner: BazelRunner, targets: tuple[str, ...]
    ) -> list[RpcCall]:
        barrier = threading.Barrier(len(targets))

        def download(target: str) -> BuildResult:
            barrier.wait()
            return _remote_download(runner, target)

        with ThreadPoolExecutor(max_workers=len(targets)) as executor:
            results = list(executor.map(download, targets))

        calls: list[RpcCall] = []
        for target, result in zip(targets, results):
            calls.extend(_successful_reads(result, target))
        return calls


class SuiteFactory:
    _SUITES = {
        "cache-hit": lambda: LookupBenchmark("cache-hit", OK, False),
        "cache-miss": lambda: LookupBenchmark("cache-miss", NOT_FOUND, True),
        "download": DownloadBenchmark,
        "concurrency": ConcurrencyDownloadBenchmark,
    }

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(cls._SUITES)

    @classmethod
    def create(cls, name: str) -> BenchmarkSuite:
        try:
            return cls._SUITES[name]()
        except KeyError as error:
            raise ValueError(f"unknown benchmark suite: {name}") from error

    @classmethod
    def create_selection(cls, name: str) -> list[BenchmarkSuite]:
        names = cls.names() if name == "all" else (name,)
        return [cls.create(suite_name) for suite_name in names]


def _calls_for_method(result: BuildResult, method_suffix: str) -> list[RpcCall]:
    return [call for call in result.calls if call.method.endswith(method_suffix)]


def _successful_reads(result: BuildResult, expected_target: str) -> list[RpcCall]:
    calls = [
        call
        for call in _calls_for_method(result, BYTE_STREAM_READ)
        if call.status_code == OK
        and call.bytes_read > 0
        and call.target_id == expected_target
    ]
    if not calls:
        raise BenchmarkError(
            "no successful remote ByteStream.Read calls were recorded for "
            f"{expected_target}. "
            f"{PREPARE_HINT}"
        )
    return calls


def _remote_download(runner: BazelRunner, target: str) -> BuildResult:
    try:
        return runner.build([target], flags=(REMOTE_DOWNLOAD_CONFIG,))
    except BenchmarkError as error:
        raise BenchmarkError(
            f"remote cache download failed for {target}. {PREPARE_HINT}\n{error}"
        ) from error


def _download_measurement(calls: list[RpcCall]) -> dict[str, float | int]:
    duration = interval_span(calls)
    if duration <= 0:
        raise BenchmarkError("download RPC duration was zero")
    bytes_read = sum(call.bytes_read for call in calls)
    return {
        "bytes_read": bytes_read,
        "duration_seconds": duration,
        "throughput_mbps": bytes_read / MEBIBYTE / duration,
    }
