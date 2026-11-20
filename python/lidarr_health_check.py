#!/usr/bin/env python3
"""
Pre-flight / monitoring health check for a Lidarr instance.

Checks Lidarr's own health endpoint, plus indexer and download client
connectivity, and prints a pass/fail summary. Exits 0 if everything is
healthy, 1 otherwise, so it can be used in cron/monitoring setups or as a
sanity check before running one of the bulk-import scripts in this repo.

Requires: requests
Install: pip install requests
"""

import argparse
import os
import sys

from lidarr_common import LidarrClient


def main():
    parser = argparse.ArgumentParser(description='Run a health check against a Lidarr instance')
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--skip-indexers', action='store_true', help='Skip testing indexers')
    parser.add_argument('--skip-download-clients', action='store_true', help='Skip testing download clients')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    client = LidarrClient(args.url, args.api_key)
    problems = []

    status = client.get_json('system/status')
    if status is None:
        print("FAIL: could not reach Lidarr (check URL and API key)")
        sys.exit(1)
    print(f"Lidarr version: {status.get('version', 'unknown')}")

    print("\nHealth checks:")
    health = client.get_json('health')
    if health is None:
        print("  FAIL: could not fetch health endpoint")
        problems.append('health endpoint unreachable')
    elif not health:
        print("  OK: no health issues reported")
    else:
        for issue in health:
            severity = issue.get('type', 'warning').upper()
            print(f"  {severity}: {issue.get('message', 'unknown issue')}")
            if severity == 'ERROR':
                problems.append(issue.get('message', 'unknown health error'))

    if not args.skip_indexers:
        print("\nIndexer connectivity:")
        results = client.test_all_indexers()
        if results is None:
            print("  FAIL: could not test indexers")
            problems.append('indexer test failed to run')
        elif not results:
            print("  OK: all configured indexers passed")
        else:
            for r in results:
                print(f"  FAIL: indexer {r.get('id', '?')} - {r.get('errorMessage', 'validation failed')}")
                problems.append(f"indexer {r.get('id', '?')} failed")

    if not args.skip_download_clients:
        print("\nDownload client connectivity:")
        results = client.test_all_download_clients()
        if results is None:
            print("  FAIL: could not test download clients")
            problems.append('download client test failed to run')
        elif not results:
            print("  OK: all configured download clients passed")
        else:
            for r in results:
                print(f"  FAIL: download client {r.get('id', '?')} - {r.get('errorMessage', 'validation failed')}")
                problems.append(f"download client {r.get('id', '?')} failed")

    print("\n" + "=" * 50)
    if problems:
        print(f"UNHEALTHY: {len(problems)} problem(s) found")
        print("=" * 50)
        sys.exit(1)
    print("HEALTHY")
    print("=" * 50)


if __name__ == '__main__':
    main()
