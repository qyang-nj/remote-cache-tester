#!/usr/bin/env python3

import argparse
import sys
import subprocess
import tempfile
import json
import shutil
import atexit

BLOB_1MB = {'size': 1024 * 1024, 'target': '//:File_1MB'}
BLOB_10MB = {'size': 1024 * 1024 * 10, 'target': '//:File_10MB'}
BLOB_30MB = {'size': 1024 * 1024 * 30, 'target': '//:File_30MB'}
BLOB_50MB = {'size': 1024 * 1024 * 50, 'target': '//:File_50MB'}
BLOB_100MB = {'size': 1024 * 1024 * 100, 'target': '//:File_100MB'}
BLOB_200MB = {'size': 1024 * 1024 * 200, 'target': '//:File_200MB'}

BLOBS = [BLOB_1MB, BLOB_10MB, BLOB_30MB, BLOB_50MB, BLOB_100MB, BLOB_200MB]


def _download_duration():
    """Parse the profile.json file to get the download duration in microseconds"""
    with open('profile.json', 'r', encoding="utf-8") as f:
        profile = json.load(f)

    downloads = [event for event in profile.get(
        'traceEvents', []) if event.get('cat') == 'remote output download']

    if len(downloads) != 1:
        _error_and_exit(
            f"expected 1 download event, got {len(downloads)}. You may need to call upload first.")

    return downloads[0]['dur']


def _error_and_exit(message, exit_code=1):
    print(f"\033[91mError: {message}\033[0m")
    sys.exit(exit_code)


def _populate_cache(server, remote_header_args, temp_dir):
    """Generate the fixed-size blobs and upload them to the remote cache"""

    targets = [blob['target'] for blob in BLOBS]

    cmd = [
        'bazel',
        f'--output_base={temp_dir}',
        'build',
        f'--remote_cache={server}',
        *remote_header_args,
        '--remote_upload_local_results=true',
        *targets
    ]
    subprocess.run(cmd, check=True)


def _measure_download_speed(server, remote_header_args, temp_dir):
    """Measure the download speed by downloading the fixed-size blobs from the remote cache"""
    print(f"Downloading from server: {server}")

    for blob in BLOBS:
        size_mb = blob['size'] // (1024 * 1024)

        cmd = [
            'bazel',
            f'--output_base={temp_dir}',
            'build',
            f'--remote_cache={server}',
            *remote_header_args,
            '--profile=profile.json',
            blob['target']
        ]

        print(f'Downloading {size_mb:3} MB ...', end='', flush=True)

        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)

        # convert from microseconds to seconds
        elapsed = _download_duration() / 1_000_000
        print(
            f" {elapsed:5.2f} seconds | {size_mb / elapsed:5.2f} MB/s | {blob['target']}")


def main():
    parser = argparse.ArgumentParser(
        description='Bazel remote cache speed tester')
    parser.add_argument(
        'server', help='Remote cache server URL, e.g. grpc://example.com')
    parser.add_argument('--upload', action='store_true',
                        help='Upload fixed-size blobs to remote cache')
    parser.add_argument('--remote-header', action='append', default=[],
                        help='Remote headers that will be directly passed to Bazel')

    args = parser.parse_args()

    # Pass remote headers to bazel as --remote_header=...
    remote_header_args = [
        f'--remote_header={header}' for header in args.remote_header]

    # Create a temporary directory as the Bazel output base
    temp_dir = tempfile.mkdtemp()
    atexit.register(lambda: shutil.rmtree(temp_dir, ignore_errors=True))

    if args.upload:
        # Switch to upload mode
        _populate_cache(args.server, remote_header_args, temp_dir)
        return

    _measure_download_speed(args.server, remote_header_args, temp_dir)


if __name__ == '__main__':
    main()
