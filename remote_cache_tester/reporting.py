from __future__ import annotations

import sys
from typing import TextIO

from .model import SuiteResult


class ConsoleReporter:
    def __init__(
        self,
        output: TextIO | None = None,
        progress: TextIO | None = None,
    ):
        self._output = output or sys.stdout
        self._progress = progress or sys.stderr

    def preparation_started(self) -> None:
        print("Populating remote cache ...", file=self._progress, flush=True)

    def preparation_finished(self) -> None:
        print("Remote cache is ready.", file=self._output)

    def suite_started(self, name: str, position: int, total: int) -> None:
        print(
            f"[{position}/{total}] Running {name} suite ...",
            file=self._progress,
            flush=True,
        )

    def suite_finished(self, name: str, status: str) -> None:
        print(
            f"      {name} suite {status}.",
            file=self._progress,
            flush=True,
        )

    def report(self, results: list[SuiteResult]) -> None:
        self._line("Bazel Remote Cache Benchmark")
        self._line("============================")

        lookups = [
            result
            for result in results
            if result.status == "passed"
            and result.name in ("cache-hit", "cache-miss")
        ]
        if lookups:
            self._lookup(lookups)

        download = self._passed_result(results, "download")
        if download:
            self._download(download)

        concurrency = self._passed_result(results, "concurrency")
        if concurrency:
            self._concurrency(concurrency)

        failures = [result for result in results if result.status == "failed"]
        if failures:
            self._failures(failures)

    def _lookup(self, results: list[SuiteResult]) -> None:
        self._section("Cache Lookup Latency")
        self._line(f"{'Result':<12} {'Requests':>8} {'Average':>14}")
        for result in results:
            summary = result.summary[0]
            label = result.name.replace("cache-", "").title()
            self._line(
                f"{label:<12} {summary['request_count']:>8} "
                f"{summary['average_latency_ms']:>10.2f} ms"
            )

    def _download(self, result: SuiteResult) -> None:
        self._section("Sequential Download")
        self._line(f"{'Size':>8} {'Duration':>16} {'Throughput':>18}")
        for row in result.summary:
            duration = row["duration_seconds"]
            throughput = row["throughput_mbps"]
            self._line(
                f"{row['size_mb']:>5} MB {duration['mean']:>13.2f} s "
                f"{throughput['mean']:>14.2f} MB/s"
            )

    def _concurrency(self, result: SuiteResult) -> None:
        self._section("Concurrent Download (50 MB per worker)")
        self._line(
            f"{'Case':<18} {'Workers':>7} {'Observed':>10} {'Wave duration':>18} "
            f"{'Throughput':>18}"
        )
        for row in result.summary:
            duration = row["wave_duration_seconds"]
            throughput = row["aggregate_throughput_mbps"]
            self._line(
                f"{row['case'].title():<18} "
                f"{row['worker_count']:>7} "
                f"{row['max_active_downloads']:>10} "
                f"{duration['mean']:>15.2f} s "
                f"{throughput['mean']:>14.2f} MB/s"
            )

    def _failures(self, results: list[SuiteResult]) -> None:
        self._section("Failures")
        for result in results:
            self._line(f"{result.name}:")
            for line in (result.error or "unknown error").splitlines():
                self._line(f"  {line}")

    def _section(self, title: str) -> None:
        self._line("")
        self._line(title)
        self._line("-" * len(title))

    def _line(self, text: str) -> None:
        print(text, file=self._output)

    @staticmethod
    def _passed_result(
        results: list[SuiteResult], name: str
    ) -> SuiteResult | None:
        return next(
            (
                result
                for result in results
                if result.name == name and result.status == "passed"
            ),
            None,
        )
