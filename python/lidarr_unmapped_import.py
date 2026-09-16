#!/usr/bin/env python3
"""
Process unmapped files in Lidarr by finding MusicBrainz release groups and adding artists.

This script fetches unmapped files from Lidarr, searches MusicBrainz for the release group
based on artist and release names, and then adds all artists from that release group to Lidarr.

Requires: requests, musicbrainzngs
Install: pip install requests musicbrainzngs
"""

import sys
import argparse
import os
import time
import musicbrainzngs
from typing import Optional

from lidarr_common import (
    LidarrClient, MB_USER_AGENT_CONTACT, VARIOUS_ARTISTS_MBID,
    build_artist_payload, extract_foreign_artist_id, extract_artist_name,
    mb_get_release_artists,
)

musicbrainzngs.set_useragent("LidarrUnmappedImporter", "1.0", MB_USER_AGENT_CONTACT)


def search_musicbrainz_release(artist_name: str, release_name: str) -> Optional[str]:
    """Search MusicBrainz for a release and return its release group ID."""
    try:
        query = f'artist:"{artist_name}" release:"{release_name}"'
        results = musicbrainzngs.search_releases(query, limit=1)
        if results.get('release-list'):
            return results['release-list'][0].get('release-group', {}).get('id')
        return None
    except Exception as e:
        print(f"  Error searching MusicBrainz: {e}", file=sys.stderr)
        return None


def get_release_group_first_release_artists(release_group_id: str):
    """Get all credited artists for the first release in a MusicBrainz release group."""
    try:
        result = musicbrainzngs.get_release_group_by_id(release_group_id, includes=['releases'])
        release_group = result['release-group']
        if not release_group.get('release-list'):
            return []
        release_id = release_group['release-list'][0]['id']
    except Exception as e:
        print(f"  Error fetching release group: {e}", file=sys.stderr)
        return []
    return mb_get_release_artists(musicbrainzngs, release_id)


def extract_artist_and_release(file_path: str):
    """Extract artist and release names from a Lidarr-relative file path.

    Assumes standard Lidarr format: Artist Name/Album Name/TrackFile
    (Lidarr's API returns relative paths with forward slashes regardless of host OS.)
    """
    parts = file_path.split('/')
    if len(parts) >= 3:
        return parts[0], parts[1]
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Process unmapped Lidarr files by adding artists from MusicBrainz release groups'
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of files to process')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between API calls in seconds')
    parser.add_argument('--no-monitor', dest='monitor', action='store_false', default=True,
                         help='Do not monitor artists')
    parser.add_argument('--search', action='store_true', help='Search for missing albums after adding')
    parser.add_argument('--dry-run', action='store_true',
                         help='Preview what would be added without making changes')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    lidarr = LidarrClient(args.url, args.api_key)

    print("Getting Lidarr configuration...")
    root_folder = lidarr.get_root_folder()
    quality_profile = lidarr.get_quality_profile_id()
    metadata_profile = lidarr.get_metadata_profile_id()

    if not all([root_folder, quality_profile, metadata_profile]):
        print("Error: could not get Lidarr configuration. Check your URL and API key.", file=sys.stderr)
        sys.exit(1)

    print(f"Root folder: {root_folder}")
    print(f"Quality profile ID: {quality_profile}")
    print(f"Metadata profile ID: {metadata_profile}")
    print()

    print("Fetching unmapped files...")
    unmapped = lidarr.get_json('trackimport/unmapped')
    if not unmapped:
        print("Error: could not fetch unmapped files, or none found.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(unmapped)} unmapped file(s)")
    print()

    files_to_process = unmapped
    if args.limit and len(unmapped) > args.limit:
        files_to_process = unmapped[:args.limit]
        print(f"Limiting to {args.limit} file(s)")
        print()

    if args.dry_run:
        print("=" * 50)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 50)
        print()

    stats = {'processed': 0, 'added': 0, 'skipped': 0, 'failed': 0}

    for i, file_info in enumerate(files_to_process, 1):
        rel_path = file_info.get('relativePath') or file_info.get('path') or str(file_info)
        print(f"[{i}/{len(files_to_process)}] Processing: {rel_path}")

        extracted = extract_artist_and_release(rel_path)
        if not extracted:
            print(f"  Could not parse artist/release from path")
            stats['skipped'] += 1
            stats['processed'] += 1
            print()
            continue

        artist_name, release_name = extracted
        print(f"  Artist: {artist_name}")
        print(f"  Release: {release_name}")

        print(f"  Searching MusicBrainz...")
        release_group_id = search_musicbrainz_release(artist_name, release_name)
        if not release_group_id:
            print(f"  Could not find release group on MusicBrainz")
            stats['skipped'] += 1
            stats['processed'] += 1
            print()
            time.sleep(args.delay)
            continue
        print(f"  Found release group: {release_group_id}")

        artists = get_release_group_first_release_artists(release_group_id)
        if not artists:
            print(f"  No artists found in release group")
            stats['skipped'] += 1
            stats['processed'] += 1
            print()
            time.sleep(args.delay)
            continue
        print(f"  Found {len(artists)} artist(s)")

        if args.dry_run:
            for artist in artists:
                if artist['id'] != VARIOUS_ARTISTS_MBID:
                    print(f"    Would add: {artist['name']}")
            stats['added'] += 1
            stats['processed'] += 1
            print()
            continue

        added_count = 0
        for artist in artists:
            if artist['id'] == VARIOUS_ARTISTS_MBID:
                continue

            artist_data = lidarr.search_by_mbid(artist['id'])
            if not artist_data:
                print(f"    - {artist['name']}: not found in search")
                continue

            if isinstance(artist_data.get('artist'), dict) and 'id' in artist_data['artist']:
                print(f"    - {artist['name']}: already in Lidarr")
                added_count += 1
                continue

            foreign_id = extract_foreign_artist_id(artist_data)
            resolved_name = extract_artist_name(artist_data) or artist['name']
            if not foreign_id:
                print(f"    - {artist['name']}: missing MusicBrainz ID in search result")
                continue

            payload = build_artist_payload(
                foreign_id, resolved_name, root_folder, quality_profile, metadata_profile,
                monitored=args.monitor, search_for_missing=args.search
            )
            result = lidarr.add_artist(payload)
            if result in ('added', 'skipped'):
                print(f"    {artist['name']}: {result}")
                added_count += 1
            else:
                print(f"    {artist['name']}: failed to add")

        if added_count > 0:
            stats['added'] += 1
        else:
            stats['failed'] += 1

        stats['processed'] += 1
        print()
        time.sleep(args.delay)

    print("=" * 50)
    print(f"Summary:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Added: {stats['added']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Failed: {stats['failed']}")
    print("=" * 50)


if __name__ == '__main__':
    main()
