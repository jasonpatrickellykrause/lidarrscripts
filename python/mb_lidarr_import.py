#!/usr/bin/env python3
"""
Add all artists from a "Various Artists" MusicBrainz release to Lidarr.

This script is useful when you want to add all contributing artists from compilation
albums, soundtracks, or other various artists releases to your Lidarr library.
It fetches all artist credits from a MusicBrainz release and adds them individually.

Requires: requests, musicbrainzngs
Install: pip install requests musicbrainzngs
"""

import sys
import argparse
import os
import time
import musicbrainzngs

from lidarr_common import (
    LidarrClient, MB_USER_AGENT_CONTACT, VARIOUS_ARTISTS_MBID,
    build_artist_payload, extract_foreign_artist_id, extract_artist_name,
    mb_get_release_artists,
)

musicbrainzngs.set_useragent("LidarrMusicBrainzImporter", "1.0", MB_USER_AGENT_CONTACT)


def resolve_release_id(id_input: str):
    """Resolve a release ID or release group ID to a release ID.

    If the input is a release group ID, returns the first release in that group.
    If the input is already a release ID, returns it as-is.
    """
    try:
        result = musicbrainzngs.get_release_group_by_id(id_input, includes=['releases'])
        release_group = result['release-group']
        if release_group.get('release-list'):
            first_release = release_group['release-list'][0]
            print(f"Release group detected: {release_group.get('title', 'Unknown')}")
            print(f"  Using first release: {first_release.get('title', 'Unknown')} ({first_release['id']})")
            return first_release['id']
        print("Release group found but has no releases", file=sys.stderr)
        return None
    except musicbrainzngs.WebServiceError:
        # Not a release group, assume it's a release ID
        return id_input
    except Exception as e:
        print(f"Error resolving ID: {e}", file=sys.stderr)
        return id_input


def main():
    parser = argparse.ArgumentParser(
        description='Add all artists from a MusicBrainz release to Lidarr'
    )
    parser.add_argument('release_id', help='MusicBrainz release ID or release group ID')
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--no-monitor', dest='monitor', action='store_false', default=True,
                         help='Do not monitor artists')
    parser.add_argument('--search', action='store_true', help='Search for missing albums after adding')
    parser.add_argument('--delay', type=float, default=0.5,
                         help='Delay between Lidarr API calls in seconds (default: 0.5)')
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

    print(f"Resolving ID {args.release_id}...")
    resolved_release_id = resolve_release_id(args.release_id)
    if not resolved_release_id:
        print("Could not resolve to a valid release ID.", file=sys.stderr)
        sys.exit(1)
    print()

    print(f"Fetching release {resolved_release_id} from MusicBrainz...")
    artists = mb_get_release_artists(musicbrainzngs, resolved_release_id)
    if not artists:
        print("No artists found for this release.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(artists)} artist(s)")
    print()

    if args.dry_run:
        print("=" * 50)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 50)
        print()

    added = skipped = 0

    for artist in artists:
        print(f"Processing: {artist['name']} ({artist['id']})")

        if artist['id'] == VARIOUS_ARTISTS_MBID:
            print(f"  Skipping Various Artists")
            skipped += 1
            print()
            continue

        if args.dry_run:
            print(f"  Would look up and add this artist")
            added += 1
            print()
            continue

        artist_data = lidarr.search_by_mbid(artist['id'])
        if not artist_data:
            print(f"  Could not find artist in Lidarr search")
            skipped += 1
            print()
            time.sleep(args.delay)
            continue

        if isinstance(artist_data.get('artist'), dict) and 'id' in artist_data['artist']:
            print(f"  Already in Lidarr")
            skipped += 1
            print()
            time.sleep(args.delay)
            continue

        foreign_id = extract_foreign_artist_id(artist_data)
        artist_name = extract_artist_name(artist_data)
        if not foreign_id or not artist_name:
            print(f"  Missing required fields in search result")
            skipped += 1
            print()
            time.sleep(args.delay)
            continue

        payload = build_artist_payload(
            foreign_id, artist_name, root_folder, quality_profile, metadata_profile,
            monitored=args.monitor, search_for_missing=args.search
        )
        result = lidarr.add_artist(payload)
        if result == 'added':
            print(f"  Added successfully")
            added += 1
        elif result == 'skipped':
            print(f"  Already in Lidarr")
            skipped += 1
        else:
            print(f"  Failed to add")
            skipped += 1

        print()
        time.sleep(args.delay)

    print("=" * 50)
    print(f"Summary:")
    print(f"  Added: {added}")
    print(f"  Skipped: {skipped}")
    print(f"  Total: {len(artists)}")


if __name__ == '__main__':
    main()
