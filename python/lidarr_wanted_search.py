#!/usr/bin/env python3
"""
Report Lidarr's monitored-but-missing albums, and optionally trigger
searches for them in batches.

Lidarr's own "Missing" UI works fine for small libraries, but bulk-searching
hundreds of missing albums one page at a time is slow. This script lists
everything on the missing/wanted list and, with --search, issues AlbumSearch
commands in configurable batches so you don't flood your indexers at once.

Requires: requests
Install: pip install requests
"""

import argparse
import os
import sys
import time

from lidarr_common import LidarrClient


def get_wanted_missing(client: LidarrClient, page_size: int = 100):
    """Page through /api/v1/wanted/missing and return every record."""
    records = []
    page = 1
    while True:
        result = client.get_json('wanted/missing', params={
            'page': page, 'pageSize': page_size, 'sortKey': 'releaseDate', 'sortDirection': 'descending'
        })
        if not result or not result.get('records'):
            break
        records.extend(result['records'])
        if len(records) >= result.get('totalRecords', 0):
            break
        page += 1
    return records


def trigger_album_search(client: LidarrClient, album_ids, batch_size: int, delay: float):
    """Issue AlbumSearch commands in batches to avoid hammering indexers."""
    triggered = 0
    for i in range(0, len(album_ids), batch_size):
        batch = album_ids[i:i + batch_size]
        if client.run_command('AlbumSearch', albumIds=batch):
            triggered += len(batch)
            print(f"  Triggered search for {len(batch)} album(s)")
        else:
            print(f"  Failed to trigger search for batch starting at index {i}", file=sys.stderr)
        if i + batch_size < len(album_ids):
            time.sleep(delay)
    return triggered


def main():
    parser = argparse.ArgumentParser(
        description="Report Lidarr's missing albums and optionally trigger searches"
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--search', action='store_true',
                         help='Trigger AlbumSearch commands for the missing albums found')
    parser.add_argument('--batch-size', type=int, default=10,
                         help='Albums per AlbumSearch command when using --search (default: 10)')
    parser.add_argument('--delay', type=float, default=5.0,
                         help='Delay between search batches in seconds (default: 5.0)')
    parser.add_argument('--limit', type=int, default=None,
                         help='Only process the first N missing albums (default: all)')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    client = LidarrClient(args.url, args.api_key)

    print("Fetching missing albums...")
    records = get_wanted_missing(client)
    if not records:
        print("No missing albums found (or the request failed).")
        return

    if args.limit and len(records) > args.limit:
        records = records[:args.limit]

    print(f"Found {len(records)} missing album(s):\n")
    for r in records:
        artist_name = (r.get('artist') or {}).get('artistName', 'Unknown Artist')
        print(f"  {artist_name} - {r.get('title', 'Unknown')} ({r.get('releaseDate', 'no date')})")

    if not args.search:
        print("\nRun with --search to trigger AlbumSearch for these albums.")
        return

    print(f"\nTriggering searches in batches of {args.batch_size} (delay {args.delay}s)...")
    album_ids = [r['id'] for r in records if r.get('id')]
    triggered = trigger_album_search(client, album_ids, args.batch_size, args.delay)

    print("\n" + "=" * 50)
    print(f"Triggered searches for {triggered}/{len(album_ids)} album(s)")
    print("=" * 50)


if __name__ == '__main__':
    main()
