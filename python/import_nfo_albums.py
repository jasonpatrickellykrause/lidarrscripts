#!/usr/bin/env python3
"""
Accelerate Lidarr album imports using MusicBrainz IDs from album.nfo files.

This script is useful when Lidarr has issues with text-based artist searches or when
you need to batch import many albums quickly. It scans a music directory for album.nfo
files, extracts MusicBrainz IDs, and adds those albums directly to Lidarr using the
API. This bypasses text search issues and provides more reliable imports.

Prerequisites:
    - Each album folder must contain an album.nfo file with MusicBrainz metadata
    - NFO files should include <musicbrainzreleasegroupid> (preferred) or
      <musicbrainzalbumid> (a release ID; resolved to its release group via Lidarr)

Requires: requests
Install: pip install requests
"""

import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple

from lidarr_common import LidarrClient, build_album_payload

UUID = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import albums into Lidarr using MusicBrainz IDs from album.nfo files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python import_nfo_albums.py --url http://localhost:8686 --api-key YOUR_KEY \\
                              --music-folder /mnt/media/music --dry-run

  LIDARR_URL=https://lidarr.example.com \\
  LIDARR_API_KEY=YOUR_KEY \\
  MUSIC_FOLDER_PATH=/mnt/media/music \\
  python import_nfo_albums.py
        """
    )
    parser.add_argument('--url', '--lidarr-url', dest='url',
                        default=os.getenv('LIDARR_URL', 'http://localhost:8686'),
                        help='Lidarr URL (default: http://localhost:8686, env: LIDARR_URL)')
    parser.add_argument('--api-key', default=os.getenv('LIDARR_API_KEY'),
                        help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--music-folder', default=os.getenv('MUSIC_FOLDER_PATH'),
                        help='Root folder containing album.nfo files (env: MUSIC_FOLDER_PATH)')
    parser.add_argument('--quality-profile-id', type=int, default=int(os.getenv('QUALITY_PROFILE_ID', '1')),
                        help='Quality profile ID for new artists/albums (default: 1, env: QUALITY_PROFILE_ID)')
    parser.add_argument('--metadata-profile-id', type=int, default=int(os.getenv('METADATA_PROFILE_ID', '1')),
                        help='Metadata profile ID for new artists (default: 1, env: METADATA_PROFILE_ID)')
    parser.add_argument('--root-folder-path', default=os.getenv('ROOT_FOLDER_PATH', '/music'),
                        help='Lidarr root folder for new artists (default: /music, env: ROOT_FOLDER_PATH)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--delay', type=float, default=0.5,
                        help='Delay between Lidarr API calls in seconds (default: 0.5)')

    args = parser.parse_args()
    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")
    if not args.music_folder:
        parser.error("--music-folder is required (or set the MUSIC_FOLDER_PATH environment variable)")
    return args


def find_nfo_files(root_path: str) -> List[str]:
    """All album.nfo files under root_path."""
    nfo_files = []
    for root, _dirs, files in os.walk(root_path):
        for file in files:
            if file.lower() == 'album.nfo':
                nfo_files.append(os.path.join(root, file))
    return nfo_files


def extract_musicbrainz_id(nfo_path: str) -> Optional[Tuple[str, str]]:
    """Return (kind, mbid) from a Kodi-style album.nfo, where kind is
    'releasegroup' or 'release'. Falls back to a regex if the XML is malformed.
    """
    tags = (('musicbrainzreleasegroupid', 'releasegroup'), ('musicbrainzalbumid', 'release'))
    try:
        root = ET.parse(nfo_path).getroot()
        for tag, kind in tags:
            node = root.find(f'.//{tag}')
            if node is not None and node.text and re.fullmatch(UUID, node.text.strip(), re.IGNORECASE):
                return kind, node.text.strip().lower()
    except ET.ParseError:
        try:
            with open(nfo_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            for tag, kind in tags:
                match = re.search(rf'<{tag}>\s*({UUID})\s*</{tag}>', content, re.IGNORECASE)
                if match:
                    return kind, match.group(1).lower()
        except OSError as e:
            print(f"  Error reading {nfo_path}: {e}")
    return None


def find_album(results: List[Dict], kind: str, mb_id: str) -> Optional[Dict]:
    """Pick the album matching mb_id out of Lidarr search results. A release ID
    matches the album whose releases include it."""
    for result in results or []:
        album = result.get('album') or result
        if kind == 'releasegroup' and album.get('foreignAlbumId') == mb_id:
            return album
        if kind == 'release' and any(r.get('foreignReleaseId') == mb_id for r in album.get('releases') or []):
            return album
    return None


def resolve_album(client: LidarrClient, kind: str, mb_id: str) -> Optional[Dict]:
    """Look the ID up through Lidarr's search (read-only). None if not found."""
    results = client.search(f'lidarr:{mb_id}')
    if results is None:
        print("  Lidarr search failed")
        return None
    album = find_album(results, kind, mb_id)
    if not album:
        print(f"  {kind} {mb_id} not found in Lidarr search results")
    return album


def add_album(client: LidarrClient, args, kind: str, mb_id: str, existing: Set[str]) -> str:
    """Returns 'added', 'would add', 'exists' or 'failed'. With --dry-run nothing is written."""
    if kind == 'releasegroup' and mb_id in existing:
        return 'exists'

    album = resolve_album(client, kind, mb_id)
    if not album:
        return 'failed'

    group_id = album.get('foreignAlbumId')
    if group_id in existing:
        return 'exists'
    if args.dry_run:
        print(f"  [DRY RUN] Would add: {(album.get('artist') or {}).get('artistName', '?')} - {album.get('title', group_id)}")
        return 'would add'

    artist = album.get('artist')
    if not artist:
        print(f"  No artist data for {album.get('title', mb_id)}")
        return 'failed'
    # Search results for artists not yet in Lidarr carry 0/empty here, so fill falsy values, not just missing keys.
    for key, value in (('qualityProfileId', args.quality_profile_id),
                       ('metadataProfileId', args.metadata_profile_id),
                       ('rootFolderPath', args.root_folder_path)):
        if not artist.get(key):
            artist[key] = value
    artist['monitored'] = True

    payload = build_album_payload(album, artist, group_id, args.quality_profile_id, monitored=True)
    outcome = client.add_album(payload)
    if outcome == 'added':
        existing.add(group_id)
        print(f"  Added: {artist.get('artistName', 'Unknown Artist')} - {album.get('title', group_id)}")
        return 'added'
    if outcome == 'skipped':
        existing.add(group_id)
        return 'exists'
    return 'failed'


def main() -> None:
    args = parse_arguments()

    print("Configuration:")
    print(f"  Lidarr URL: {args.url}")
    print(f"  Music Folder: {args.music_folder}")
    print(f"  Quality Profile ID: {args.quality_profile_id}")
    print(f"  Metadata Profile ID: {args.metadata_profile_id}")
    print(f"  Root Folder Path: {args.root_folder_path}")
    if args.dry_run:
        print("  DRY RUN MODE: No changes will be made")
    print()

    if not os.path.isdir(args.music_folder):
        print(f"Error: Music folder does not exist: {args.music_folder}")
        sys.exit(1)

    print(f"Scanning for album.nfo files in: {args.music_folder}")
    nfo_files = find_nfo_files(args.music_folder)
    print(f"Found {len(nfo_files)} album.nfo files\n")
    if not nfo_files:
        sys.exit(0)

    client = LidarrClient(args.url, args.api_key)
    albums = client.get_json('album')
    if albums is None:
        print("Error: could not read albums from Lidarr (check URL and API key)")
        sys.exit(1)
    existing = {a.get('foreignAlbumId') for a in albums}  # fetched once, kept up to date as we add

    counts = {'added': 0, 'would add': 0, 'exists': 0, 'failed': 0, 'no id': 0}
    for nfo_path in nfo_files:
        print(f"Processing: {nfo_path}")
        found = extract_musicbrainz_id(nfo_path)
        if not found:
            print("  No MusicBrainz ID found")
            counts['no id'] += 1
            continue
        kind, mb_id = found
        print(f"  Found {kind} ID: {mb_id}")

        outcome = add_album(client, args, kind, mb_id, existing)
        if outcome == 'exists':
            print("  Already in Lidarr, skipping")
        counts[outcome] += 1
        time.sleep(args.delay)

    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Total NFO files: {len(nfo_files)}")
    print(f"  {'Would add' if args.dry_run else 'Added'}: {counts['would add' if args.dry_run else 'added']}")
    print(f"  Already in Lidarr: {counts['exists']}")
    print(f"  Failed: {counts['failed']}")
    print(f"  Skipped (no ID): {counts['no id']}")
    print("=" * 50)
    sys.exit(1 if counts['failed'] else 0)


if __name__ == '__main__':
    main()
