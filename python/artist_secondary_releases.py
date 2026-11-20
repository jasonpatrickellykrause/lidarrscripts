#!/usr/bin/env python3
"""
Add all secondary/featured releases of a MusicBrainz artist to Lidarr.

This script finds all releases where a specified artist appears but is not the primary
artist credit, and adds them to Lidarr. This is useful for tracking featured appearances,
collaborations, and compilation appearances by artists.

Requires: requests, musicbrainzngs
Install: pip install requests musicbrainzngs
"""

import sys
import argparse
import os
import time
import musicbrainzngs
from typing import List, Dict

from lidarr_common import (
    LidarrClient, MB_USER_AGENT_CONTACT, build_artist_payload, build_album_payload,
    extract_foreign_artist_id, extract_artist_name,
)

musicbrainzngs.set_useragent("LidarrSecondaryReleasesImporter", "1.0", MB_USER_AGENT_CONTACT)


def get_artist_releases(artist_mbid: str) -> List[Dict]:
    """Get all releases for a MusicBrainz artist."""
    try:
        result = musicbrainzngs.get_artist_by_id(
            artist_mbid, includes=['release-rels', 'releases']
        )
        artist = result['artist']
    except musicbrainzngs.WebServiceError as e:
        print(f"MusicBrainz error: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error fetching artist releases: {e}", file=sys.stderr)
        return []

    releases = []
    seen_ids = set()

    for rel in artist.get('release-rel-list', []):
        release = rel.get('release')
        if release and release.get('id') not in seen_ids:
            releases.append({
                'id': release.get('id'),
                'title': release.get('title'),
            })
            seen_ids.add(release.get('id'))

    for release in artist.get('release-list', []):
        if release.get('id') not in seen_ids:
            releases.append({
                'id': release.get('id'),
                'title': release.get('title'),
            })
            seen_ids.add(release.get('id'))

    return releases


def is_primary_artist(artist_mbid: str, release_id: str) -> bool:
    """Check if the artist is the primary/first artist credit on a release."""
    try:
        result = musicbrainzngs.get_release_by_id(release_id, includes=['artist-credits'])
        release = result['release']
        credits = release.get('artist-credit') or []
        if not credits:
            return False
        first_credit = credits[0]
        if isinstance(first_credit, dict) and 'artist' in first_credit:
            return first_credit['artist'].get('id') == artist_mbid
        return False
    except Exception as e:
        print(f"Error checking primary artist for release {release_id}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Add all secondary/featured releases of a MusicBrainz artist to Lidarr'
    )
    parser.add_argument('artist_mbid', help='MusicBrainz artist ID')
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--max-releases', type=int, default=None,
                         help='Maximum number of releases to add (default: unlimited)')
    parser.add_argument('--no-monitor-artist', dest='monitor_artist', action='store_false',
                         default=True, help='Do not monitor the artist')
    parser.add_argument('--no-monitor-albums', dest='monitor_albums', action='store_false',
                         default=True, help='Do not monitor the albums')
    parser.add_argument('--root-folder', type=str, default=None,
                         help='Root folder path (default: first available)')
    parser.add_argument('--quality-profile', type=int, default=None,
                         help='Quality profile ID (default: first available)')
    parser.add_argument('--metadata-profile', type=int, default=None,
                         help='Metadata profile ID (default: first available)')
    parser.add_argument('--delay', type=float, default=0.5,
                         help='Delay between Lidarr API calls in seconds (default: 0.5)')
    parser.add_argument('--dry-run', action='store_true',
                         help='Preview what would be added without making changes')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    lidarr = LidarrClient(args.url, args.api_key)

    print("Getting Lidarr configuration...")
    root_folder = args.root_folder or lidarr.get_root_folder()
    quality_profile = args.quality_profile or lidarr.get_quality_profile_id()
    metadata_profile = args.metadata_profile or lidarr.get_metadata_profile_id()

    if not all([root_folder, quality_profile, metadata_profile]):
        print("Error: could not get Lidarr configuration. Check your URL and API key.", file=sys.stderr)
        sys.exit(1)

    print(f"Root folder: {root_folder}")
    print(f"Quality profile ID: {quality_profile}")
    print(f"Metadata profile ID: {metadata_profile}")
    print()

    print(f"Fetching releases for artist {args.artist_mbid}...")
    releases = get_artist_releases(args.artist_mbid)
    if not releases:
        print("No releases found for this artist.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(releases)} total release(s)")
    print()

    print("Filtering for secondary releases (artist not primary)...")
    secondary_releases = [r for r in releases if r.get('id') and not is_primary_artist(args.artist_mbid, r['id'])]
    print(f"Found {len(secondary_releases)} secondary release(s)")
    print()

    if not secondary_releases:
        print("No secondary releases found for this artist.")
        sys.exit(0)

    releases_to_add = secondary_releases
    if args.max_releases and len(secondary_releases) > args.max_releases:
        releases_to_add = secondary_releases[:args.max_releases]
        print(f"Limiting to {args.max_releases} release(s) (out of {len(secondary_releases)})")
        print()

    if args.dry_run:
        print("=" * 50)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 50)
        print()

    print("Looking up artist in Lidarr...")
    artist_data = lidarr.search_by_mbid(args.artist_mbid)
    if not artist_data:
        print("Could not find artist in Lidarr search "
              "(it may not exist in MusicBrainz, or Lidarr's search is limited).", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        print("Adding artist to Lidarr...")
        foreign_id = extract_foreign_artist_id(artist_data)
        artist_name = extract_artist_name(artist_data)
        if foreign_id and artist_name:
            payload = build_artist_payload(
                foreign_id, artist_name, root_folder, quality_profile, metadata_profile,
                monitored=args.monitor_artist
            )
            result = lidarr.add_artist(payload)
            print(f"Artist {result}: {artist_name}")
        else:
            print("Warning: could not extract artist name/MBID from search result")
        print()

    print("Adding secondary releases as albums...")
    print()

    added = skipped = failed = 0

    for i, release in enumerate(releases_to_add, 1):
        release_id = release.get('id')
        title = release.get('title', 'Unknown')
        print(f"[{i}/{len(releases_to_add)}] {title} ({release_id})")

        if args.dry_run:
            print(f"  Would add this release")
            added += 1
            print()
            continue

        result = lidarr.search_by_mbid(release_id)
        if not result:
            print(f"  Could not find release in Lidarr search")
            skipped += 1
            print()
            time.sleep(args.delay)
            continue

        album_data = result.get('album', result)
        search_artist_data = result.get('artist', {})

        payload = build_album_payload(album_data, search_artist_data, release_id,
                                       quality_profile, monitored=args.monitor_albums)
        outcome = lidarr.add_album(payload)
        if outcome == 'added':
            print(f"  Added")
            added += 1
        elif outcome == 'skipped':
            print(f"  Already in Lidarr")
            skipped += 1
        else:
            print(f"  Failed to add")
            failed += 1

        print()
        time.sleep(args.delay)

    print("=" * 50)
    print("Summary:")
    print(f"  Total secondary releases: {len(secondary_releases)}")
    print(f"  Processed: {len(releases_to_add)}")
    print(f"  Added: {added}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print("=" * 50)


if __name__ == '__main__':
    main()
