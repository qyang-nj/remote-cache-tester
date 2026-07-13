import tempfile
import unittest
from pathlib import Path

from remote_cache_tester.grpc_log import GrpcLogParser


def varint(value):
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def integer(field, value):
    return varint(field << 3) + varint(value)


def message(field, value):
    return varint((field << 3) | 2) + varint(len(value)) + value


class GrpcLogParserTest(unittest.TestCase):
    def test_parses_read_entry(self):
        metadata = message(6, b"//:File_50MB_1")
        status = integer(1, 0)
        read_request = message(1, b"uploads/instance/blobs/abc123/10485760")
        read_details = (
            message(1, read_request)
            + integer(2, 4)
            + integer(3, 10 * 1024 * 1024)
        )
        details = message(5, read_details)
        start = integer(1, 100) + integer(2, 100_000_000)
        end = integer(1, 101) + integer(2, 600_000_000)
        entry = b"".join(
            (
                message(1, metadata),
                message(2, status),
                message(3, b"google.bytestream.ByteStream/Read"),
                message(4, details),
                message(5, start),
                message(6, end),
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "grpc.log"
            path.write_bytes(varint(len(entry)) + entry)
            calls = GrpcLogParser().parse(path)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].status_code, 0)
        self.assertEqual(calls[0].bytes_read, 10 * 1024 * 1024)
        self.assertEqual(calls[0].target_id, "//:File_50MB_1")
        self.assertEqual(
            calls[0].resource_name,
            "uploads/instance/blobs/abc123/10485760",
        )
        self.assertAlmostEqual(calls[0].duration_seconds, 1.5)

    def test_parses_cache_miss(self):
        entry = b"".join(
            (
                message(2, integer(1, 5)),
                message(
                    3,
                    b"build.bazel.remote.execution.v2.ActionCache/GetActionResult",
                ),
                message(5, integer(1, 10)),
                message(6, integer(1, 11)),
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "grpc.log"
            path.write_bytes(varint(len(entry)) + entry)
            calls = GrpcLogParser().parse(path)

        self.assertEqual(calls[0].status_code, 5)
        self.assertTrue(calls[0].method.endswith("ActionCache/GetActionResult"))
        self.assertEqual(calls[0].duration_seconds, 1)


if __name__ == "__main__":
    unittest.main()
