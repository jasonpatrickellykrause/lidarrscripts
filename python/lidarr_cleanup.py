#!/usr/bin/env python3
"""
Clean up a Lidarr library by removing unmonitored albums and reducing
artist-level monitoring.

For each artist, this script:
1. Removes unmonitored albums that have no downloaded files
2. Sets artist monitoring to "no new albums" (monitorNewItems = 'none')
3. Sets artist metadata profile to "None"

This is useful for cleaning up after bulk imports or reducing active
monitoring load. By default it only touches albums you've already chosen
not to monitor - pass --include-empty-monitored to also remove monitored
albums with no files, but note that will also catch upcoming releases that
simply haven't come out yet unless they're excluded by release date, which
this script does automatically.

Requires: requests
Install: pip install requests
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from lidarr_common import LidarrClient


class LidarrCleanup:
    """Cleanup operations: unmonitored/empty album removal and artist configuration."""

    def __init__(self, client: LidarrClient):
        self.client = client
        self.none_profile_id = None

    def get_none_metadata_profile_id(self) -> Optional[int]:
        """Metadata profile ID for "None", falling back to the first profile."""
        self.none_profile_id = self.client.get_metadata_profile_id(name='None')
        return self.none_profile_id

    def is_missing_album(self, album: Dict, include_empty_monitored: bool) -> bool:
        """An album is a cleanup candidate if:
        - It is unmonitored, regardless of whether files exist, OR
        - `include_empty_monitored` is set, it's monitored but has zero
          downloaded files, AND its release date has already passed (so
          upcoming/unreleased albums are never touched).
        """
        if not album.get('monitored'):
            return True

        if not include_empty_monitored:
            return False

        stats = album.get('statistics', {}) or {}
        if stats.get('trackFileCount', 0) > 0:
            return False

        release_date = album.get('releaseDate')
        if not release_date:
            return False
        try:
            released = datetime.fromisoformat(release_date.replace('Z', '+00:00'))
        except ValueError:
            return False
        return released < datetime.now(timezone.utc)

    def cleanup_artist(self, artist: Dict, albums: List[Dict], include_empty_monitored: bool,
                        dry_run: bool = False, delay: float = 0.5) -> Dict:
        """Clean up a single artist (remove missing albums, update settings)."""
        stats = {'deleted': 0, 'failed_delete': 0, 'updated': False, 'failed_update': False}

        missing_albums = [a for a in albums if self.is_missing_album(a, include_empty_monitored)]

        for album in missing_albums:
            album_title = album.get('title', 'Unknown')
            album_id = album.get('id')

            if dry_run:
                print(f"    Would delete: {album_title}")
                stats['deleted'] += 1
            elif self.client.delete_album(album_id):
                print(f"    Deleted: {album_title}")
                stats['deleted'] += 1
                time.sleep(delay)
            else:
                print(f"    Failed to delete: {album_title}")
                stats['failed_delete'] += 1

        if dry_run:
            print(f"    Would update monitoring and metadata profile")
            stats['updated'] = True
        else:
            payload = dict(artist)
            payload['metadataProfileId'] = self.none_profile_id
            payload['monitorNewItems'] = 'none'
            if self.client.update_artist(payload):
                print(f"    Updated monitoring to 'no new albums' and metadata profile to 'None'")
                stats['updated'] = True
                time.sleep(delay)
            else:
                print(f"    Failed to update artist settings")
                stats['failed_update'] = True

        return stats

    def run(self, max_artists: Optional[int] = None, include_empty_monitored: bool = False,
            dry_run: bool = False, delay: float = 0.5) -> Dict:
        """Run the cleanup operation on all artists."""
        print("Getting Lidarr configuration...")

        if not self.get_none_metadata_profile_id():
            print("Error: could not find metadata profiles", file=sys.stderr)
            return {}

        print(f"Using metadata profile ID: {self.none_profile_id}")
        print()

        print("Fetching all artists...")
        artists = self.client.get_artists()
        if not artists:
            print("Error: no artists found in Lidarr", file=sys.stderr)
            return {}

        print(f"Found {len(artists)} artist(s)")

        print("Fetching all albums...")
        all_albums = self.client.get_albums()
        albums_by_artist: Dict[int, List[Dict]] = {}
        for album in all_albums:
            albums_by_artist.setdefault(album.get('artistId'), []).append(album)
        print(f"Found {len(all_albums)} album(s)")
        print()

        artists_to_process = artists
        if max_artists and len(artists) > max_artists:
            artists_to_process = artists[:max_artists]
            print(f"Limiting to {max_artists} artist(s) (out of {len(artists)})")
            print()

        if dry_run:
            print("=" * 50)
            print("DRY RUN MODE - No changes will be made")
            print("=" * 50)
            print()

        total_stats = {
            'total_artists': len(artists_to_process),
            'total_deleted': 0,
            'total_failed_delete': 0,
            'total_updated': 0,
            'total_failed_update': 0
        }

        for i, artist in enumerate(artists_to_process, 1):
            artist_name = artist.get('artistName', 'Unknown')
            print(f"[{i}/{len(artists_to_process)}] Processing: {artist_name}")

            albums = albums_by_artist.get(artist.get('id'), [])
            stats = self.cleanup_artist(artist, albums, include_empty_monitored,
                                         dry_run=dry_run, delay=delay)

            total_stats['total_deleted'] += stats['deleted']
            total_stats['total_failed_delete'] += stats['failed_delete']
            if stats['updated']:
                total_stats['total_updated'] += 1
            if stats['failed_update']:
                total_stats['total_failed_update'] += 1

            print()

        return total_stats


def main():
    parser = argparse.ArgumentParser(
        description='Clean up a Lidarr library by removing unmonitored/empty albums and updating artist settings'
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--max-artists', type=int, default=None,
                         help='Maximum number of artists to process (default: all)')
    parser.add_argument('--include-empty-monitored', action='store_true',
                         help='Also remove monitored albums with no downloaded files, '
                              'as long as their release date has already passed')
    parser.add_argument('--dry-run', action='store_true',
                         help='Preview what would be changed without making changes')
    parser.add_argument('--delay', type=float, default=0.5,
                         help='Delay between API calls in seconds (default: 0.5)')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    cleanup = LidarrCleanup(LidarrClient(args.url, args.api_key))
    stats = cleanup.run(max_artists=args.max_artists,
                         include_empty_monitored=args.include_empty_monitored,
                         dry_run=args.dry_run, delay=args.delay)

    print("=" * 50)
    print("CLEANUP SUMMARY")
    print("=" * 50)
    print(f"Total artists processed: {stats.get('total_artists', 0)}")
    print(f"Total albums deleted: {stats.get('total_deleted', 0)}")
    print(f"Failed deletions: {stats.get('total_failed_delete', 0)}")
    print(f"Artists updated: {stats.get('total_updated', 0)}")
    print(f"Failed updates: {stats.get('total_failed_update', 0)}")
    print("=" * 50)


if __name__ == '__main__':
    main()
