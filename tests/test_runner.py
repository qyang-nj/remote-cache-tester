import unittest

from remote_cache_tester.runner import _last_lines


class RunnerTest(unittest.TestCase):
    def test_redacts_remote_headers_from_bazel_errors(self):
        output = (
            "common --remote_header=x-api-key=secret-value\n"
            "build --remote_cache_header=authorization=secret-token\n"
            "build failed"
        )

        redacted = _last_lines(output)

        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("secret-token", redacted)
        self.assertIn("--remote_header=<redacted>", redacted)


if __name__ == "__main__":
    unittest.main()
