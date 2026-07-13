import threading
import unittest

from remote_cache_tester.model import MEBIBYTE, RpcCall
from remote_cache_tester.runner import BenchmarkError, BuildResult
from remote_cache_tester.suites import (
    BenchmarkContext,
    ConcurrencyDownloadBenchmark,
    DownloadBenchmark,
    LookupBenchmark,
)


class FakeRunner:
    def __init__(self):
        self.invocations = []
        self._lock = threading.Lock()

    def build(self, targets, *, flags=(), capture_grpc_log=True):
        with self._lock:
            self.invocations.append((tuple(targets), tuple(flags)))

        if "--config=remote_cache_download" in flags:
            target = targets[0]
            return BuildResult(
                calls=(
                    RpcCall(
                        "google.bytestream.ByteStream/Read",
                        0,
                        1.0,
                        2.0,
                        50 * MEBIBYTE,
                        target,
                        f"blobs/expected/{50 * MEBIBYTE}",
                    ),
                    RpcCall(
                        "google.bytestream.ByteStream/Read",
                        0,
                        1.0,
                        2.0,
                        50 * MEBIBYTE,
                        "//:UnrelatedTarget",
                        f"blobs/unrelated/{50 * MEBIBYTE}",
                    ),
                )
            )

        status = 5 if any("REMOTE_CACHE_TESTER_MISS" in flag for flag in flags) else 0
        return BuildResult(
            calls=(
                RpcCall(
                    "build.bazel.remote.execution.v2.ActionCache/GetActionResult",
                    status,
                    1.0,
                    1.01,
                ),
            )
        )


class NoRemoteReadRunner:
    def build(self, targets, *, flags=(), capture_grpc_log=True):
        return BuildResult(calls=())


class UnrelatedRemoteReadRunner:
    def build(self, targets, *, flags=(), capture_grpc_log=True):
        return BuildResult(
            calls=(
                RpcCall(
                    "google.bytestream.ByteStream/Read",
                    0,
                    1.0,
                    2.0,
                    50 * MEBIBYTE,
                    "//:UnrelatedTarget",
                ),
            )
        )


class UncachedRunner:
    def build(self, targets, *, flags=(), capture_grpc_log=True):
        raise BenchmarkError("required remote cache entry was not found")


class FixedWorkloadTest(unittest.TestCase):
    def test_lookup_suites_run_ten_times(self):
        for name, status, force_miss in (
            ("cache-hit", 0, False),
            ("cache-miss", 5, True),
        ):
            with self.subTest(name=name):
                runner = FakeRunner()
                result = LookupBenchmark(name, status, force_miss).run(
                    BenchmarkContext(runner=runner)
                )

                self.assertEqual(len(runner.invocations), 10)
                self.assertEqual(result.summary[0]["request_count"], 10)
                self.assertAlmostEqual(
                    result.summary[0]["average_latency_ms"], 10.0
                )

    def test_download_suite_runs_each_blob_once(self):
        runner = FakeRunner()

        result = DownloadBenchmark().run(BenchmarkContext(runner=runner))

        self.assertEqual(len(runner.invocations), 6)
        self.assertEqual(len(result.samples), 6)
        self.assertTrue(
            all(row["duration_seconds"]["mean"] == 1.0 for row in result.summary)
        )
        self.assertTrue(
            all(
                "--config=remote_cache_download" in flags
                for _, flags in runner.invocations
            )
        )

    def test_download_suite_rejects_local_or_disk_cache_results(self):
        with self.assertRaisesRegex(BenchmarkError, "prepare"):
            DownloadBenchmark().run(BenchmarkContext(runner=NoRemoteReadRunner()))

    def test_download_suite_rejects_reads_for_other_targets(self):
        with self.assertRaisesRegex(BenchmarkError, "//:File_1MB"):
            DownloadBenchmark().run(
                BenchmarkContext(runner=UnrelatedRemoteReadRunner())
            )

    def test_download_suite_prompts_prepare_for_uncached_actions(self):
        with self.assertRaisesRegex(BenchmarkError, "prepare"):
            DownloadBenchmark().run(BenchmarkContext(runner=UncachedRunner()))

    def test_concurrency_suite_compares_same_and_distinct_50_mb_digests(self):
        runner = FakeRunner()

        result = ConcurrencyDownloadBenchmark().run(BenchmarkContext(runner=runner))

        self.assertEqual(len(runner.invocations), 16)
        self.assertEqual(
            [row["case"] for row in result.summary],
            ["same digest", "distinct digests"],
        )
        self.assertTrue(all(row["worker_count"] == 8 for row in result.summary))
        self.assertTrue(
            all(row["max_active_downloads"] == 8 for row in result.summary)
        )
        self.assertTrue(
            all(
                row["aggregate_throughput_mbps"]["mean"] == 400.0
                for row in result.summary
            )
        )
        self.assertTrue(
            all(
                row["wave_duration_seconds"]["mean"] == 1.0
                for row in result.summary
            )
        )
        invoked_targets = [targets[0] for targets, _ in runner.invocations]
        self.assertEqual(invoked_targets[:8], ["//:File_50MB"] * 8)
        self.assertEqual(
            set(invoked_targets[8:]),
            {f"//:File_50MB_{index}" for index in range(1, 9)},
        )
        self.assertTrue(
            all(
                "--config=remote_cache_download" in flags
                for _, flags in runner.invocations
            )
        )


if __name__ == "__main__":
    unittest.main()
