# Bazel Remote Cache Tester

This tool allows you to upload fixed-size blobs to a Bazel remote cache server and measure download speeds.

## Usage
Clone this repository and run the `remote-cache-tester.py` script.

* Populate the Remote Cache

```sh
$ remote-cache-tester.py grpc://example.com --upload [--remote-header=***]
```

* Measure Download Speed

```sh
$ remote-cache-tester.py grpc://example.com [--remote-header=***]
Downloading from server: grpc://example.com
Downloading   1 MB ...  0.63 seconds |  1.58 MB/s | //:File_1MB
Downloading  10 MB ...  1.16 seconds |  8.60 MB/s | //:File_10MB
Downloading  30 MB ...  2.82 seconds | 10.65 MB/s | //:File_30MB
Downloading  50 MB ...  4.78 seconds | 10.46 MB/s | //:File_50MB
Downloading 100 MB ...  6.82 seconds | 14.66 MB/s | //:File_100MB
Downloading 200 MB ... 12.61 seconds | 15.86 MB/s | //:File_200MB
```
