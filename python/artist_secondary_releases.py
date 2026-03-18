#!/usr/bin/env python3
"""
Add all secondary/featured releases of a MusicBrainz artist to Lidarr.

This script finds all releases where a specified artist appears but is not the primary
artist credit, and adds them to Lidarr. This is useful for tracking featured appearances,
collaborations, and compilation appearances by artists.

Requires: requests, musicbrainzngs
Install: pip install requests musicbrainzngs

Created with assistance from Claude (Anthropic) - https://claude.ai
"""

import sys
import argparse
import musicbrainzngs
import requests
import time
from typing import List, Dict, Optional


# Configure MusicBrainz API
musicbrainzngs.set_useragent(
    "LidarrSecondaryReleasesImporter",
    "1.0",
    "https://github.com/yourusername/yourrepo"
)


class LidarrAPI:
    """Handle Lidarr API interactions.

    This class provides methods to interact with the Lidarr API for managing
    artists and albums, including searching, adding, and retrieving configuration.

    Attributes:
        url: Base URL of the Lidarr instance.
        api_key: API key for authentication.
        headers: HTTP headers used for API requests.
    """

    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        }

    def get_root_folder(self) -> Optional[str]:
        """Get the first root folder path from Lidarr.

        Returns:
            The path of the first configured root folder, or None if unavailable.
        """
        try:
            resp = requests.get(f'{self.url}/api/v1/rootfolder', headers=self.headers)
            resp.raise_for_status()
            folders = resp.json()
            return folders[0]['path'] if folders else None
        except Exception as e:
            print(f"Error getting root folder: {e}")
            return None

    def get_quality_profile_id(self, profile_id: Optional[int] = None) -> Optional[int]:
        """Get quality profile ID from Lidarr.

        Args:
            profile_id: If specified, return this ID. Otherwise return first profile ID.

        Returns:
            The ID of the quality profile, or None if unavailable.
        """
        if profile_id is not None:
            return profile_id

        try:
            resp = requests.get(f'{self.url}/api/v1/qualityprofile', headers=self.headers)
            resp.raise_for_status()
            profiles = resp.json()
            return profiles[0]['id'] if profiles else None
        except Exception as e:
            print(f"Error getting quality profile: {e}")
            return None

    def get_metadata_profile_id(self, profile_id: Optional[int] = None) -> Optional[int]:
        """Get metadata profile ID from Lidarr.

        Args:
            profile_id: If specified, return this ID. Otherwise return first profile ID.

        Returns:
            The ID of the metadata profile, or None if unavailable.
        """
        if profile_id is not None:
            return profile_id

        try:
            resp = requests.get(f'{self.url}/api/v1/metadataprofile', headers=self.headers)
            resp.raise_for_status()
            profiles = resp.json()
            return profiles[0]['id'] if profiles else None
        except Exception as e:
            print(f"Error getting metadata profile: {e}")
            return None

    def search_artist(self, mb_id: str) -> Optional[Dict]:
        """Search for an artist by MusicBrainz ID in Lidarr.

        Args:
            mb_id: The MusicBrainz ID of the artist.

        Returns:
            Artist data dictionary if found, or None if not found.
        """
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
                   monitor: bool = True) -> bool:
        """Add an artist to Lidarr.

        Args:
            artist_data: Dictionary containing artist information from search.
            root_folder: Root folder path where artist files will be stored.
            quality_profile: ID of the quality profile to use.
            metadata_profile: ID of the metadata profile to use.
            monitor: Whether to monitor the artist for new releases. Defaults to True.

        Returns:
            True if artist was added successfully, False otherwise.
        """
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
                'searchForMissingAlbums': False
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
                    if 'already exists' in str(error).lower():
                        return True  # Already exists counts as success
                except:
                    pass
            return False
        except Exception:
            return False

    def add_album(self, album_data: Dict, release_id: str, artist_data: Dict,
                  quality_profile: int, metadata_profile: int,
                  monitor: bool = True) -> bool:
        """Add an album/release to Lidarr.

        Args:
            album_data: Dictionary containing album information from search.
            release_id: MusicBrainz release ID.
            artist_data: Dictionary containing artist information.
            quality_profile: ID of the quality profile to use.
            metadata_profile: ID of the metadata profile to use.
            monitor: Whether to monitor the album. Defaults to True.

        Returns:
            True if album was added successfully, False otherwise.
        """
        payload = {
            "title": album_data.get('title', 'Unknown'),
            "foreignAlbumId": release_id,
            "monitored": monitor,
            "anyReleaseOk": True,
            "profileId": quality_profile,
            "duration": album_data.get('duration', 0),
            "albumType": album_data.get('albumType', ''),
            "secondaryTypes": album_data.get('secondaryTypes', []),
            "mediumCount": album_data.get('mediumCount', 0),
            "ratings": album_data.get('ratings', {'votes': 0, 'value': 0.0}),
            "releaseDate": album_data.get('releaseDate'),
            "releases": album_data.get('releases', []),
            "genres": album_data.get('genres', []),
            "media": album_data.get('media', []),
            "artist": artist_data,
            "images": album_data.get('images', []),
            "links": album_data.get('links', []),
            "addOptions": {
                "searchForNewAlbum": False
            }
        }

        try:
            resp = requests.post(
                f'{self.url}/api/v1/album',
                headers=self.headers,
                json=payload
            )
            resp.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                return True  # Probably already exists
            return False
        except Exception:
            return False


def get_artist_releases(artist_mbid: str) -> List[Dict]:
    """Get all releases for a MusicBrainz artist.

    Args:
        artist_mbid: The MusicBrainz artist ID.

    Returns:
        List of dictionaries containing release information.
        Returns empty list if an error occurs.
    """
    try:
        result = musicbrainzngs.get_artist_by_id(
            artist_mbid,
            includes=['release-rels', 'releases']
        )
        artist = result['artist']

        releases = []

        # Get releases from release relationships
        if 'release-rel-list' in artist:
            for rel in artist['release-rel-list']:
                if 'release' in rel:
                    release = rel['release']
                    releases.append({
                        'id': release.get('id'),
                        'title': release.get('title'),
                        'release-group': release.get('release-group', {})
                    })

        # Also get releases directly if available
        if 'release-list' in artist:
            for release in artist['release-list']:
                if release.get('id') not in [r['id'] for r in releases]:
                    releases.append({
                        'id': release.get('id'),
                        'title': release.get('title'),
                        'release-group': release.get('release-group', {})
                    })

        return releases

    except musicbrainzngs.WebServiceError as e:
        print(f"MusicBrainz error: {e}")
        return []
    except Exception as e:
        print(f"Error fetching artist releases: {e}")
        return []


def is_primary_artist(artist_mbid: str, release_id: str) -> bool:
    """Check if the artist is the primary/first artist credit on a release.

    Args:
        artist_mbid: The MusicBrainz artist ID to check.
        release_id: The MusicBrainz release ID.

    Returns:
        True if the artist is the primary artist, False otherwise.
    """
    try:
        result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=['artist-credits']
        )
        release = result['release']

        # Check if there are artist credits
        if 'artist-credit' not in release or not release['artist-credit']:
            return False

        # Get the first artist credit
        first_credit = release['artist-credit'][0]

        if isinstance(first_credit, dict) and 'artist' in first_credit:
            first_artist_id = first_credit['artist'].get('id')
            return first_artist_id == artist_mbid

        return False

    except Exception as e:
        print(f"Error checking primary artist for release {release_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Add all secondary/featured releases of a MusicBrainz artist to Lidarr'
    )
    parser.add_argument('artist_mbid', help='MusicBrainz artist ID')
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', required=True, help='Lidarr API key')
    parser.add_argument('--max-releases', type=int, default=None,
                       help='Maximum number of releases to add (default: unlimited)')
    parser.add_argument('--monitor-artist', dest='monitor_artist', action='store_true',
                       default=True, help='Monitor the artist (default: True)')
    parser.add_argument('--no-monitor-artist', dest='monitor_artist', action='store_false',
                       help='Do not monitor the artist')
    parser.add_argument('--monitor-albums', dest='monitor_albums', action='store_true',
                       default=True, help='Monitor the albums (default: True)')
    parser.add_argument('--no-monitor-albums', dest='monitor_albums', action='store_false',
                       help='Do not monitor the albums')
    parser.add_argument('--root-folder', type=str, default=None,
                       help='Root folder path (default: first available)')
    parser.add_argument('--quality-profile', type=int, default=None,
                       help='Quality profile ID (default: first available)')
    parser.add_argument('--metadata-profile', type=int, default=None,
                       help='Metadata profile ID (default: first available)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be added without making changes')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output')

    args = parser.parse_args()

    # Initialize Lidarr API
    lidarr = LidarrAPI(args.url, args.api_key)

    # Get Lidarr configuration
    print("🔍 Getting Lidarr configuration...")

    root_folder = args.root_folder or lidarr.get_root_folder()
    quality_profile = lidarr.get_quality_profile_id(args.quality_profile)
    metadata_profile = lidarr.get_metadata_profile_id(args.metadata_profile)

    if not all([root_folder, quality_profile, metadata_profile]):
        print("❌ Could not get Lidarr configuration. Check your URL and API key.")
        sys.exit(1)

    print(f"✓ Root folder: {root_folder}")
    print(f"✓ Quality profile ID: {quality_profile}")
    print(f"✓ Metadata profile ID: {metadata_profile}")
    print()

    # Fetch all releases for the artist
    print(f"🎵 Fetching releases for artist {args.artist_mbid}...")
    releases = get_artist_releases(args.artist_mbid)

    if not releases:
        print(f"❌ No releases found for this artist.")
        sys.exit(1)

    print(f"✓ Found {len(releases)} total release(s)")
    print()

    # Filter for secondary releases (artist is not primary)
    print("🔎 Filtering for secondary releases (artist not primary)...")
    secondary_releases = []

    for release in releases:
        release_id = release.get('id')
        if not release_id:
            continue

        if not is_primary_artist(args.artist_mbid, release_id):
            secondary_releases.append(release)

    print(f"✓ Found {len(secondary_releases)} secondary release(s)")
    print()

    if not secondary_releases:
        print("ℹ️  No secondary releases found for this artist.")
        sys.exit(0)

    # Limit to max-releases if specified
    releases_to_add = secondary_releases
    if args.max_releases and len(secondary_releases) > args.max_releases:
        releases_to_add = secondary_releases[:args.max_releases]
        print(f"⚠️  Limiting to {args.max_releases} release(s) (out of {len(secondary_releases)})")
        print()

    if args.dry_run:
        print("=" * 50)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 50)
        print()

    # Get artist data for adding to Lidarr
    print("🔍 Looking up artist in Lidarr...")
    artist_data = lidarr.search_artist(args.artist_mbid)

    if not artist_data:
        print(f"⚠️  Could not find artist in Lidarr search")
        print(f"    The artist may not exist in MusicBrainz or Lidarr's search is limited.")
        sys.exit(1)

    # Add artist to Lidarr if not already present
    if not args.dry_run:
        print("Adding artist to Lidarr...")
        if lidarr.add_artist(
            artist_data,
            root_folder,
            quality_profile,
            metadata_profile,
            monitor=args.monitor_artist
        ):
            print("✓ Artist added/verified")
        else:
            print("⚠️  Could not add artist to Lidarr")
        print()

    # Add releases as albums
    print("Adding secondary releases as albums...")
    print()

    added = 0
    skipped = 0
    failed = 0

    for i, release in enumerate(releases_to_add, 1):
        release_id = release.get('id')
        title = release.get('title', 'Unknown')

        print(f"[{i}/{len(releases_to_add)}] {title} ({release_id})")

        if args.dry_run:
            print(f"  ✓ Would add this release")
            added += 1
        else:
            # Search for album in Lidarr
            search_url = f"{args.url}/api/v1/search"
            headers = {
                'X-Api-Key': args.api_key,
                'Content-Type': 'application/json'
            }

            try:
                resp = requests.get(
                    search_url,
                    headers=headers,
                    params={'term': f'lidarr:{release_id}'}
                )
                resp.raise_for_status()
                results = resp.json()

                if not results:
                    print(f"  ⚠️  Could not find release in Lidarr search")
                    skipped += 1
                    print()
                    continue

                # Extract album data from first result
                result = results[0]
                if result.get('album'):
                    album_data = result['album']
                    search_artist_data = result.get('artist', {})
                else:
                    album_data = result
                    search_artist_data = result.get('artist', {})

                # Add album
                success = lidarr.add_album(
                    album_data,
                    release_id,
                    search_artist_data,
                    quality_profile,
                    metadata_profile,
                    monitor=args.monitor_albums
                )

                if success:
                    print(f"  ✓ Added")
                    added += 1
                else:
                    print(f"  ❌ Failed to add")
                    failed += 1

            except Exception as e:
                print(f"  ❌ Error: {e}")
                failed += 1

        print()

    # Summary
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
