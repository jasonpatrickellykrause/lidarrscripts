#!/usr/bin/env python3
"""
Process unmapped files in Lidarr by finding MusicBrainz release groups and adding artists.

This script fetches unmapped files from Lidarr, searches MusicBrainz for the release group
based on artist and release names, and then adds all artists from that release group to Lidarr.

Requires: requests, musicbrainzngs
Install: pip install requests musicbrainzngs

Created with assistance from Claude (Anthropic) - https://claude.ai
"""

import sys
import argparse
import musicbrainzngs
import requests
from typing import List, Dict, Optional
import time


# Configure MusicBrainz API
musicbrainzngs.set_useragent(
    "LidarrUnmappedImporter",
    "1.0",
    "https://github.com/yourusername/yourrepo"
)


class LidarrAPI:
    """Handle Lidarr API interactions."""

    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        }

    def get_unmapped_files(self) -> Optional[List[Dict]]:
        """Get list of unmapped files from Lidarr.

        Returns:
            List of unmapped file dictionaries with relative paths and metadata.
        """
        try:
            resp = requests.get(
                f'{self.url}/api/v1/trackimport/unmapped',
                headers=self.headers,
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Error fetching unmapped files: {e}")
            return None

    def get_root_folder(self) -> Optional[str]:
        """Get the first root folder path from Lidarr."""
        try:
            resp = requests.get(f'{self.url}/api/v1/rootfolder', headers=self.headers)
            resp.raise_for_status()
            folders = resp.json()
            return folders[0]['path'] if folders else None
        except Exception as e:
            print(f"Error getting root folder: {e}")
            return None

    def get_quality_profile_id(self) -> Optional[int]:
        """Get the first quality profile ID from Lidarr."""
        try:
            resp = requests.get(f'{self.url}/api/v1/qualityprofile', headers=self.headers)
            resp.raise_for_status()
            profiles = resp.json()
            return profiles[0]['id'] if profiles else None
        except Exception as e:
            print(f"Error getting quality profile: {e}")
            return None

    def get_metadata_profile_id(self) -> Optional[int]:
        """Get the first metadata profile ID from Lidarr."""
        try:
            resp = requests.get(f'{self.url}/api/v1/metadataprofile', headers=self.headers)
            resp.raise_for_status()
            profiles = resp.json()
            return profiles[0]['id'] if profiles else None
        except Exception as e:
            print(f"Error getting metadata profile: {e}")
            return None

    def search_artist(self, mb_id: str) -> Optional[Dict]:
        """Search for an artist by MusicBrainz ID in Lidarr."""
        try:
            resp = requests.get(
                f'{self.url}/api/v1/search',
                headers=self.headers,
                params={'term': f'lidarr:{mb_id}'}
            )
            resp.raise_for_status()
            results = resp.json()
            return results[0] if results else None
        except Exception as e:
            print(f"Error searching for artist {mb_id}: {e}")
            return None

    def add_artist(self, artist_data: Dict, root_folder: str,
                   quality_profile: int, metadata_profile: int,
                   monitor: bool = True, search: bool = False) -> bool:
        """Add an artist to Lidarr."""
        foreign_artist_id = (artist_data.get('foreignArtistId') or
                            artist_data.get('foreignId') or
                            artist_data.get('mbId'))

        if 'artist' in artist_data and isinstance(artist_data['artist'], dict):
            artist_name = artist_data['artist'].get('artistName') or artist_data['artist'].get('name')
        else:
            artist_name = artist_data.get('artistName') or artist_data.get('name')

        if not foreign_artist_id or not artist_name:
            return False

        payload = {
            'foreignArtistId': foreign_artist_id,
            'artistName': artist_name,
            'qualityProfileId': quality_profile,
            'metadataProfileId': metadata_profile,
            'rootFolderPath': root_folder,
            'monitored': monitor,
            'addOptions': {
                'monitor': 'all' if monitor else 'none',
                'searchForMissingAlbums': search
            }
        }

        try:
            resp = requests.post(
                f'{self.url}/api/v1/artist',
                headers=self.headers,
                json=payload
            )
            resp.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                try:
                    error = e.response.json()
                    error_msg = str(error)
                    if 'already exists' in error_msg.lower():
                        return False
                except:
                    pass
            return False
        except Exception:
            return False


def search_musicbrainz_release(artist_name: str, release_name: str) -> Optional[str]:
    """Search MusicBrainz for a release and return its release group ID.

    Args:
        artist_name: Artist name to search for.
        release_name: Release/album name to search for.

    Returns:
        Release group ID if found, None otherwise.
    """
    try:
        query = f'artist:"{artist_name}" release:"{release_name}"'
        results = musicbrainzngs.search_releases(query, limit=1)

        if results.get('release-list'):
            release = results['release-list'][0]
            release_group_id = release.get('release-group', {}).get('id')
            if release_group_id:
                return release_group_id

        return None

    except Exception as e:
        print(f"  Error searching MusicBrainz: {e}")
        return None


def get_release_artists(release_group_id: str) -> List[Dict]:
    """Get all artists from a MusicBrainz release group."""
    try:
        result = musicbrainzngs.get_release_group_by_id(
            release_group_id,
            includes=['releases', 'artists']
        )
        release_group = result['release-group']

        # Get first release in the group
        if not release_group.get('release-list'):
            return []

        first_release = release_group['release-list'][0]
        release_id = first_release['id']

        # Fetch the full release with artist credits
        release_result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=['artists', 'artist-credits', 'recordings']
        )
        release = release_result['release']

        artists = []
        seen_ids = set()

        # Get release-level artist credits
        if 'artist-credit' in release:
            for credit in release['artist-credit']:
                if isinstance(credit, dict) and 'artist' in credit:
                    artist = credit['artist']
                    mb_id = artist['id']
                    if mb_id not in seen_ids:
                        artists.append({
                            'id': mb_id,
                            'name': artist['name'],
                            'sort_name': artist.get('sort-name', artist['name'])
                        })
                        seen_ids.add(mb_id)

        # Get track-level artist credits from all mediums
        if 'medium-list' in release:
            for medium in release['medium-list']:
                if 'track-list' in medium:
                    for track in medium['track-list']:
                        if 'recording' in track and 'artist-credit' in track['recording']:
                            for credit in track['recording']['artist-credit']:
                                if isinstance(credit, dict) and 'artist' in credit:
                                    artist = credit['artist']
                                    mb_id = artist['id']
                                    if mb_id not in seen_ids:
                                        artists.append({
                                            'id': mb_id,
                                            'name': artist['name'],
                                            'sort_name': artist.get('sort-name', artist['name'])
                                        })
                                        seen_ids.add(mb_id)

                        if 'artist-credit' in track:
                            for credit in track['artist-credit']:
                                if isinstance(credit, dict) and 'artist' in credit:
                                    artist = credit['artist']
                                    mb_id = artist['id']
                                    if mb_id not in seen_ids:
                                        artists.append({
                                            'id': mb_id,
                                            'name': artist['name'],
                                            'sort_name': artist.get('sort-name', artist['name'])
                                        })
                                        seen_ids.add(mb_id)

        return artists

    except Exception as e:
        print(f"  Error fetching release group: {e}")
        return []


def extract_artist_and_release(file_path: str) -> Optional[tuple]:
    """Extract artist and release names from file path.

    Assumes standard Lidarr format: Artist Name/Album Name/TrackFile

    Args:
        file_path: File path string from Lidarr.

    Returns:
        Tuple of (artist_name, release_name) or None if parsing fails.
    """
    try:
        parts = file_path.split('/')
        if len(parts) >= 3:
            artist_name = parts[0]
            release_name = parts[1]
            return (artist_name, release_name)
        return None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Process unmapped Lidarr files by adding artists from MusicBrainz release groups'
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', required=True, help='Lidarr API key')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of files to process')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between API calls in seconds')
    parser.add_argument('--no-monitor', dest='monitor', action='store_false', default=True,
                       help='Do not monitor artists')
    parser.add_argument('--search', action='store_true', help='Search for missing albums after adding')

    args = parser.parse_args()

    # Initialize Lidarr API
    lidarr = LidarrAPI(args.url, args.api_key)

    # Get Lidarr configuration
    print("🔍 Getting Lidarr configuration...")
    root_folder = lidarr.get_root_folder()
    quality_profile = lidarr.get_quality_profile_id()
    metadata_profile = lidarr.get_metadata_profile_id()

    if not all([root_folder, quality_profile, metadata_profile]):
        print("❌ Could not get Lidarr configuration. Check your URL and API key.")
        sys.exit(1)

    print(f"✓ Root folder: {root_folder}")
    print(f"✓ Quality profile ID: {quality_profile}")
    print(f"✓ Metadata profile ID: {metadata_profile}")
    print()

    # Get unmapped files
    print("📂 Fetching unmapped files...")
    unmapped = lidarr.get_unmapped_files()

    if not unmapped:
        print("❌ Could not fetch unmapped files or no unmapped files found.")
        sys.exit(1)

    print(f"✓ Found {len(unmapped)} unmapped file(s)")
    print()

    # Limit files if requested
    files_to_process = unmapped
    if args.limit and len(unmapped) > args.limit:
        files_to_process = unmapped[:args.limit]
        print(f"⚠️  Limiting to {args.limit} file(s)")
        print()

    # Process each file
    stats = {
        'processed': 0,
        'added': 0,
        'skipped': 0,
        'failed': 0
    }

    for i, file_info in enumerate(files_to_process, 1):
        # Extract relative path - different Lidarr versions may structure this differently
        rel_path = file_info.get('relativePath') or file_info.get('path') or str(file_info)

        print(f"[{i}/{len(files_to_process)}] Processing: {rel_path}")

        # Extract artist and release names
        extracted = extract_artist_and_release(rel_path)
        if not extracted:
            print(f"  ⚠️  Could not parse artist/release from path")
            stats['skipped'] += 1
            stats['processed'] += 1
            print()
            continue

        artist_name, release_name = extracted
        print(f"  Artist: {artist_name}")
        print(f"  Release: {release_name}")

        # Search MusicBrainz
        print(f"  🔍 Searching MusicBrainz...")
        release_group_id = search_musicbrainz_release(artist_name, release_name)

        if not release_group_id:
            print(f"  ⚠️  Could not find release group on MusicBrainz")
            stats['skipped'] += 1
            stats['processed'] += 1
            print()
            time.sleep(args.delay)
            continue

        print(f"  ✓ Found release group: {release_group_id}")

        # Get artists from release group
        artists = get_release_artists(release_group_id)

        if not artists:
            print(f"  ⚠️  No artists found in release group")
            stats['skipped'] += 1
            stats['processed'] += 1
            print()
            time.sleep(args.delay)
            continue

        print(f"  ✓ Found {len(artists)} artist(s)")

        # Add artists to Lidarr
        added_count = 0
        for artist in artists:
            # Skip Various Artists
            if artist['id'] == '89ad4ac3-39f7-470e-963a-56509c546377':
                continue

            # Search for artist in Lidarr
            artist_data = lidarr.search_artist(artist['id'])

            if not artist_data:
                print(f"    - {artist['name']}: not found in search")
                continue

            # Check if already in Lidarr
            if 'artist' in artist_data and isinstance(artist_data['artist'], dict):
                if 'id' in artist_data['artist']:
                    print(f"    - {artist['name']}: already in Lidarr")
                    continue

            # Add artist
            success = lidarr.add_artist(
                artist_data,
                root_folder,
                quality_profile,
                metadata_profile,
                monitor=args.monitor,
                search=args.search
            )

            if success:
                print(f"    ✓ {artist['name']}: added")
                added_count += 1
            else:
                print(f"    ✗ {artist['name']}: failed to add")

        if added_count > 0:
            stats['added'] += 1
        else:
            stats['failed'] += 1

        stats['processed'] += 1
        print()
        time.sleep(args.delay)

    # Summary
    print("=" * 50)
    print(f"Summary:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Added: {stats['added']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Failed: {stats['failed']}")
    print("=" * 50)


if __name__ == '__main__':
    main()
