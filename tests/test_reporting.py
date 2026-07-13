import io
import unittest

from remote_cache_tester.model import SuiteResult
from remote_cache_tester.reporting import ConsoleReporter


def stats(count=1, value=12.34):
    return {
        "count": count,
        "minimum": value,
        "mean": value,
        "p50": value,
        "p90": value,
        "p99": value,
        "maximum": value,
    }


class ConsoleReporterTest(unittest.TestCase):
    def setUp(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.reporter = ConsoleReporter(self.stdout, self.stderr)

    def test_progress_and_results_use_separate_streams(self):
        self.reporter.suite_started("cache-hit", 1, 1)
        self.reporter.suite_finished("cache-hit", "passed")

        self.assertEqual(self.stdout.getvalue(), "")
        self.assertIn("[1/1] Running cache-hit", self.stderr.getvalue())
        self.assertIn("cache-hit suite passed", self.stderr.getvalue())

        self.reporter.report(
            [
                SuiteResult(
                    name="cache-hit",
                    summary=[
                        {
                            "request_count": 10,
                            "average_latency_ms": 12.34,
                        }
                    ],
                )
            ]
        )

        output = self.stdout.getvalue()
        self.assertIn("Bazel Remote Cache Benchmark", output)
        self.assertIn("Cache Lookup Latency", output)
        self.assertIn("Average", output)
        self.assertNotIn("P50", output)
        self.assertNotIn("Running", output)

    def test_prepare_progress_uses_stderr_and_result_uses_stdout(self):
        self.reporter.preparation_started()
        self.reporter.preparation_finished()

        self.assertEqual(self.stdout.getvalue(), "Remote cache is ready.\n")
        self.assertEqual(self.stderr.getvalue(), "Populating remote cache ...\n")

    def test_download_durations_are_rendered_in_seconds(self):
        self.reporter.report(
            [
                SuiteResult(
                    name="download",
                    summary=[
                        {
                            "size_mb": 50,
                            "duration_seconds": stats(value=1.25),
                            "throughput_mbps": stats(value=40.0),
                        }
                    ],
                ),
                SuiteResult(
                    name="concurrency",
                    summary=[
                        {
                            "case": "same digest",
                            "worker_count": 8,
                            "max_active_downloads": 8,
                            "wave_duration_seconds": stats(value=2.5),
                            "aggregate_throughput_mbps": stats(value=160.0),
                        }
                    ],
                ),
            ]
        )

        output = self.stdout.getvalue()
        self.assertIn("Duration", output)
        self.assertIn("1.25 s", output)
        self.assertIn("2.50 s", output)
        self.assertIn("Same Digest", output)
        self.assertNotIn("Latency", output)
        self.assertNotIn(" ms", output)


if __name__ == "__main__":
    unittest.main()
