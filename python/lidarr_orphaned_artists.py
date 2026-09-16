#!/usr/bin/env python3
"""
Find Lidarr artists whose folder no longer exists on disk.

Lidarr can lose track of an artist's folder if it was renamed or moved
outside Lidarr (e.g. by a separate file-organizing tool). This is the
Lidarr-side complement to powershell/Find-EmptyAlbumFolder.ps1, which finds
the opposite case (folders on disk with nothing in them).

This must run somewhere with the same filesystem view Lidarr itself has -
directly on the host, or inside the same container/mount namespace. If you
run it elsewhere, every artist will look "orphaned" because the paths won't
resolve at all.

Requires: requests
Install: pip install requests
"""

import argparse
import os
import time

from lidarr_common import LidarrClient


def main():
    parser = argparse.ArgumentParser(
        description="Find Lidarr artists whose folder no longer exists on disk"
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--unmonitor', action='store_true',
                         help='Unmonitor orphaned artists in Lidarr (does not touch any files)')
    parser.add_argument('--dry-run', action='store_true',
                         help='With --unmonitor, preview without making changes')
    parser.add_argument('--delay', type=float, default=0.5,
                         help='Delay between updates in seconds (default: 0.5)')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    client = LidarrClient(args.url, args.api_key)

    print("Fetching artists...")
    artists = client.get_artists()
    if not artists:
        print("No artists found (or the request failed).")
        return

    orphaned = [a for a in artists if a.get('path') and not os.path.isdir(a['path'])]

    if not orphaned:
        print(f"Checked {len(artists)} artist(s): none orphaned.")
        return

    print(f"\n{len(orphaned)}/{len(artists)} artist(s) have a missing folder:\n")
    for artist in orphaned:
        print(f"  {artist.get('artistName', 'Unknown')}: {artist.get('path')}")

    if not args.unmonitor:
        print("\nRun with --unmonitor to unmonitor these artists in Lidarr (files are never touched).")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] Would unmonitor {len(orphaned)} artist(s)")
        return

    print()
    updated = failed = 0
    for artist in orphaned:
        payload = dict(artist)
        payload['monitored'] = False
        if client.update_artist(payload):
            print(f"Unmonitored: {artist.get('artistName')}")
            updated += 1
        else:
            print(f"Failed to update: {artist.get('artistName')}")
            failed += 1
        time.sleep(args.delay)

    print("\n" + "=" * 50)
    print(f"Unmonitored: {updated}  Failed: {failed}")
    print("=" * 50)


if __name__ == '__main__':
    main()
