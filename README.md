# Bazel Remote Cache Tester

This tool measures Bazel remote cache lookup latency and sequential and concurrent download performance. Metrics are calculated from Bazel's `--remote_grpc_log`, so lookup latency and throughput describe client-observed remote RPCs rather than total build time.

## Usage

Clone this repository and run the `remote-cache-tester.py` script.

Create a Bazel rc file that configures the remote cache:

```sh
build --remote_cache=grpc://example.com
build --remote_header=Header-Name=HeaderValue
```

Populate the deterministic test artifacts before running benchmarks:

```sh
$ ./remote-cache-tester.py --bazel-rc /path/to/bazel.rc prepare
```

Run all benchmark suites:

```sh
$ ./remote-cache-tester.py --bazel-rc /path/to/bazel.rc run
```

`run` defaults to `--suite all`, which executes:

- `cache-hit`: successful `GetActionResult` lookup latency
- `cache-miss`: `GetActionResult` `NOT_FOUND` lookup latency
- `download`: one sequential download for every artifact size
- `concurrency`: two 8-worker, 50 MB download waves, comparing one shared digest with eight distinct digests

Run one suite with:

```sh
$ ./remote-cache-tester.py --bazel-rc /path/to/bazel.rc run --suite cache-hit
$ ./remote-cache-tester.py --bazel-rc /path/to/bazel.rc run --suite concurrency
```

## Benchmark Methodology

Every measured Bazel invocation uses batch mode and a fresh output base. This prevents Bazel state from an earlier invocation from satisfying the request. Bazel writes a separate gRPC log for every invocation, and the tester calculates metrics from the RPC start time, end time, status, and transferred byte count in that log.

The metrics are client-observed remote RPC measurements. They do not include Bazel startup, loading and analysis, local action execution, or work after the last measured RPC. They also cannot separate network time from remote-server processing time.

### Cache Hit

The `cache-hit` suite measures Action Cache lookup latency:

1. It starts 10 independent Bazel invocations that build `//:File_1MB` without changing its action key.
2. Each invocation has a fresh output base and disables local-result uploads.
3. The suite selects successful `ActionCache/GetActionResult` RPCs with gRPC status `OK`.
4. Each sample is `GetActionResult end time - start time`.
5. The report shows the request count and average latency in milliseconds.

Artifact downloads are not included in this metric. If no successful `GetActionResult` call is recorded, the suite fails and prompts the user to run `prepare`.

### Cache Miss

The `cache-miss` suite measures missing Action Cache lookup latency:

1. It starts 10 independent Bazel invocations that build `//:File_1MB`.
2. Each invocation adds a unique `REMOTE_CACHE_TESTER_MISS` action environment value, producing an action key that is not expected to exist remotely.
3. Local-result uploads are disabled so these intentionally missing actions do not populate the remote cache.
4. The suite selects `ActionCache/GetActionResult` RPCs with gRPC status `NOT_FOUND`.
5. Each sample is `GetActionResult end time - start time`, and the report shows the average in milliseconds.

Bazel may execute the action locally after the miss, but that work is outside the measured lookup RPC and is not included in the result.

### Sequential Download

The `download` suite downloads each deterministic artifact once: 1, 10, 30, 50, 100, and 200 MB.

Each invocation enables the `remote_cache_download` configuration from `.bazelrc`. This configuration downloads all outputs, disables local-result uploads, and requires the action to already be cached. The suite requires at least one successful remote `ByteStream.Read` RPC whose gRPC request metadata identifies the expected Bazel target. Reads for other targets are ignored, preventing unrelated remote activity, a local build, or a disk-cache result from being reported as the target's remote download.

For each artifact:

```text
duration = latest Read end time - earliest Read start time
throughput = total bytes from successful Read RPCs / duration
```

Duration is reported in seconds and throughput in MB/s. A missing cached action or missing remote read fails the suite and prompts the user to run `prepare`.

### Concurrent Download

The `concurrency` suite compares two fixed workloads. Both launch eight independent Bazel batch processes, synchronize their process launch with a barrier, use fresh output bases, and download 50 MB per worker:

- `Same Digest`: all eight workers download `//:File_50MB`, transferring the same CAS digest eight times.
- `Distinct Digests`: the workers download `//:File_50MB_1` through `//:File_50MB_8`. These files have equal sizes and different contents, producing eight CAS digests.

Each case transfers 400 MB in total. Process launch is synchronized, but Bazel startup can stagger the actual remote reads. For each worker, only successful `ByteStream.Read` RPCs whose request metadata matches that worker's target are counted. The `Observed` value is the maximum number of those target-matched Read intervals that overlap; Reads for any other target are ignored.

For each case:

```text
wave duration = latest Read end time - earliest Read start time
aggregate throughput = total bytes from all workers / wave duration
```

Wave duration is reported in seconds and aggregate throughput in MB/s. The same remote-only validation used by the sequential download suite applies to every worker.

## Prepare

`prepare` builds all benchmark artifacts with local-result uploads enabled. This populates both the Action Cache entries and CAS blobs required by cache-hit and download suites. Preparation is setup only; its upload time is not measured. Run it again after changing the benchmark targets or when the remote cache has evicted them.

## Output Streams

Progress messages are written to standard error. The final benchmark report is written to standard output, so it can be redirected independently:

```sh
$ ./remote-cache-tester.py --bazel-rc /path/to/bazel.rc run > report.txt
```
