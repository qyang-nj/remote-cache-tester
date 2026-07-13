from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import BLOBS, DISTINCT_50MB_BLOBS, SuiteResult
from .reporting import ConsoleReporter
from .runner import BazelRunner, BenchmarkError
from .suites import BenchmarkContext, SuiteFactory


WORKSPACE = Path(__file__).resolve().parent.parent


class RemoteCacheTester:
    def __init__(self, runner: BazelRunner, reporter: ConsoleReporter):
        self._runner = runner
        self._reporter = reporter

    def prepare(self) -> None:
        self._reporter.preparation_started()
        self._runner.build(
            [blob.target for blob in (*BLOBS, *DISTINCT_50MB_BLOBS)],
            flags=["--remote_upload_local_results=true"],
            capture_grpc_log=False,
        )
        self._reporter.preparation_finished()

    def run(self, suite_name: str) -> list[SuiteResult]:
        context = BenchmarkContext(runner=self._runner)
        results: list[SuiteResult] = []
        suites = SuiteFactory.create_selection(suite_name)
        for position, suite in enumerate(suites, start=1):
            self._reporter.suite_started(suite.name, position, len(suites))
            try:
                result = suite.run(context)
            except (BenchmarkError, ValueError) as error:
                result = SuiteResult.failed(suite.name, str(error))
            results.append(result)
            self._reporter.suite_finished(suite.name, result.status)
        self._reporter.report(results)
        return results


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bazel remote cache performance tester")
    parser.add_argument(
        "--bazel-rc",
        required=True,
        type=Path,
        help="Bazel rc file that configures the remote cache",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="populate deterministic remote cache entries")

    run = commands.add_parser("run", help="run remote cache benchmarks")
    run.add_argument(
        "--suite",
        choices=("all", *SuiteFactory.names()),
        default="all",
        help="benchmark suite to run (default: all)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    bazel_rc = args.bazel_rc.expanduser().resolve()
    if not bazel_rc.is_file():
        parser.error(f"Bazel rc file does not exist: {bazel_rc}")

    tester = RemoteCacheTester(
        BazelRunner(WORKSPACE, bazel_rc), ConsoleReporter()
    )
    try:
        if args.command == "prepare":
            tester.prepare()
            return 0

        results = tester.run(args.suite)
        return 1 if any(result.status == "failed" for result in results) else 0
    except BenchmarkError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
