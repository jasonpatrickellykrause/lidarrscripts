#!/usr/bin/env python3
"""
Find albums in Lidarr that have more downloaded track files than the
release's expected track count - a strong signal of duplicate rips
(e.g. a FLAC copy and an MP3 copy of the same album both kept on disk).

This complements the filesystem-only powershell/Find-MixedAudioDirectory.ps1
script by using Lidarr's own database instead of scanning folders, so it
catches duplicates even when the files aren't in the same directory.

Requires: requests
Install: pip install requests
"""

import argparse
import os

from lidarr_common import LidarrClient


def find_duplicate_candidates(client: LidarrClient):
    """Albums where trackFileCount exceeds totalTrackCount."""
    albums = client.get_albums()
    artists_by_id = {a['id']: a for a in client.get_artists()}

    candidates = []
    for album in albums:
        stats = album.get('statistics', {}) or {}
        file_count = stats.get('trackFileCount', 0)
        expected = stats.get('totalTrackCount', 0)
        if expected and file_count > expected:
            artist = artists_by_id.get(album.get('artistId'), {})
            candidates.append({
                'artist': artist.get('artistName', 'Unknown Artist'),
                'album': album.get('title', 'Unknown'),
                'album_id': album.get('id'),
                'file_count': file_count,
                'expected': expected,
            })
    return candidates


def show_track_file_details(client: LidarrClient, album_id: int):
    """Fetch and print the actual file paths for a flagged album."""
    files = client.get_json('trackfile', params={'albumId': album_id}) or []
    for f in files:
        quality = (f.get('quality') or {}).get('quality', {}).get('name', 'Unknown quality')
        print(f"      {f.get('path', 'unknown path')} [{quality}]")


def main():
    parser = argparse.ArgumentParser(
        description="Find Lidarr albums with more track files than expected tracks (likely duplicates)"
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--verbose', action='store_true',
                         help='Fetch and print the actual file paths for each flagged album')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    client = LidarrClient(args.url, args.api_key)

    print("Scanning albums for duplicate track files...")
    candidates = find_duplicate_candidates(client)

    if not candidates:
        print("No likely duplicates found.")
        return

    print(f"\nFound {len(candidates)} album(s) with more files than expected tracks:\n")
    for c in candidates:
        print(f"  {c['artist']} - {c['album']}: {c['file_count']} files for {c['expected']} expected tracks")
        if args.verbose:
            show_track_file_details(client, c['album_id'])


if __name__ == '__main__':
    main()
