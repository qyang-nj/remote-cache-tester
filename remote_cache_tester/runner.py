from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .grpc_log import GrpcLogError, GrpcLogParser
from .model import RpcCall


class BenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    calls: tuple[RpcCall, ...]


class BazelRunner:
    def __init__(self, workspace: Path, bazel_rc: Path):
        self._workspace = workspace
        self._bazel_rc = bazel_rc
        self._log_parser = GrpcLogParser()

    def build(
        self,
        targets: Iterable[str],
        *,
        flags: Iterable[str] = (),
        capture_grpc_log: bool = True,
    ) -> BuildResult:
        with tempfile.TemporaryDirectory(prefix="remote-cache-tester-") as temp_dir:
            root = Path(temp_dir)
            grpc_log = root / "remote-grpc.log"
            command = [
                "bazel",
                "--batch",
                f"--output_base={root / 'output-base'}",
                f"--bazelrc={self._bazel_rc}",
                "build",
                "--color=no",
                "--curses=no",
                "--experimental_convenience_symlinks=ignore",
                "--noshow_progress",
            ]
            if capture_grpc_log:
                command.append(f"--remote_grpc_log={grpc_log}")
            command.extend(flags)
            command.extend(targets)

            try:
                completed = subprocess.run(
                    command,
                    cwd=self._workspace,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            except FileNotFoundError as error:
                raise BenchmarkError("bazel executable was not found in PATH") from error

            if completed.returncode != 0:
                details = _last_lines(completed.stderr or completed.stdout)
                raise BenchmarkError(
                    f"Bazel build failed with exit code {completed.returncode}\n{details}"
                )

            if not capture_grpc_log:
                return BuildResult(calls=())
            if not grpc_log.exists():
                raise BenchmarkError(
                    "Bazel did not create the gRPC log; verify that the remote cache "
                    "uses grpc:// or grpcs://"
                )
            try:
                calls = self._log_parser.parse(grpc_log)
            except GrpcLogError as error:
                raise BenchmarkError(f"cannot parse Bazel gRPC log: {error}") from error
            return BuildResult(calls=tuple(calls))


def _last_lines(output: str, count: int = 20) -> str:
    lines = output.strip().splitlines()
    tail = "\n".join(lines[-count:])
    return re.sub(
        r"(--(?:remote|remote_cache|remote_exec|remote_downloader)_header=)\S+",
        r"\1<redacted>",
        tail,
    )
