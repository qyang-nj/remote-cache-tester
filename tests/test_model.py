import unittest

from remote_cache_tester.model import RpcCall, Statistics, max_concurrency


class StatisticsTest(unittest.TestCase):
    def test_calculates_interpolated_percentiles(self):
        stats = Statistics.from_values([1, 2, 3, 4, 5])

        self.assertEqual(stats.p50, 3)
        self.assertEqual(stats.p90, 4.6)
        self.assertEqual(stats.p99, 4.96)

    def test_calculates_maximum_concurrency(self):
        calls = [
            RpcCall("Read", 0, 0.0, 2.0),
            RpcCall("Read", 0, 1.0, 3.0),
            RpcCall("Read", 0, 1.5, 1.75),
        ]

        self.assertEqual(max_concurrency(calls), 3)

    def test_adjacent_calls_do_not_overlap(self):
        calls = [
            RpcCall("Read", 0, 0.0, 1.0),
            RpcCall("Read", 0, 1.0, 2.0),
        ]

        self.assertEqual(max_concurrency(calls), 1)


if __name__ == "__main__":
    unittest.main()
