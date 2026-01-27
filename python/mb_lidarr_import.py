#!/usr/bin/env python3
"""
Add all artists from a "Various Artists" MusicBrainz release to Lidarr.

This script is useful when you want to add all contributing artists from compilation
albums, soundtracks, or other various artists releases to your Lidarr library.
It fetches all artist credits from a MusicBrainz release and adds them individually.

Requires: requests, musicbrainzngs
Install: pip install requests musicbrainzngs

Created with assistance from Claude (Anthropic) - https://claude.ai
"""

import sys
import argparse
import musicbrainzngs
import requests
from typing import List, Dict, Optional


# Configure MusicBrainz API
musicbrainzngs.set_useragent(
    "LidarrMusicBrainzImporter",
    "1.0",
    "https://github.com/yourusername/yourrepo"
)


class LidarrAPI:
    """Handle Lidarr API interactions.
    
    This class provides methods to interact with the Lidarr API for managing
    artists, including searching, adding, and retrieving configuration.
    
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
    
    def get_quality_profile_id(self) -> Optional[int]:
        """Get the first quality profile ID from Lidarr.
        
        Returns:
            The ID of the first configured quality profile, or None if unavailable.
        """
        try:
            resp = requests.get(f'{self.url}/api/v1/qualityprofile', headers=self.headers)
            resp.raise_for_status()
            profiles = resp.json()
            return profiles[0]['id'] if profiles else None
        except Exception as e:
            print(f"Error getting quality profile: {e}")
            return None
    
    def get_metadata_profile_id(self) -> Optional[int]:
        """Get the first metadata profile ID from Lidarr.
        
        Returns:
            The ID of the first configured metadata profile, or None if unavailable.
        """
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
                   monitor: bool = True, search: bool = False) -> bool:
        """Add an artist to Lidarr.

        Args:
            artist_data: Dictionary containing artist information from search.
            root_folder: Root folder path where artist files will be stored.
            quality_profile: ID of the quality profile to use.
            metadata_profile: ID of the metadata profile to use.
            monitor: Whether to monitor the artist for new releases. Defaults to True.
            search: Whether to search for missing albums after adding. Defaults to False.

        Returns:
            True if artist was added successfully, False otherwise.
        """
        # Check for required fields and handle different possible field names
        # Lidarr search API returns: foreignId, artist (nested object), id
        foreign_artist_id = (artist_data.get('foreignArtistId') or
                            artist_data.get('foreignId') or
                            artist_data.get('mbId'))

        # Artist name might be in different places depending on API response
        if 'artist' in artist_data and isinstance(artist_data['artist'], dict):
            # Nested artist object from search API
            artist_name = artist_data['artist'].get('artistName') or artist_data['artist'].get('name')
        else:
            artist_name = artist_data.get('artistName') or artist_data.get('name')

        if not foreign_artist_id or not artist_name:
            print(f"  ❌ Missing required fields in artist data")
            print(f"     Available fields: {list(artist_data.keys())}")
            if 'artist' in artist_data:
                print(f"     Nested artist fields: {list(artist_data['artist'].keys()) if isinstance(artist_data['artist'], dict) else type(artist_data['artist'])}")
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
                    if 'Artist already exists' in error_msg or 'already exists' in error_msg.lower():
                        print(f"  ⚠️  Artist already in Lidarr")
                        return False
                    # Show the actual error message from Lidarr
                    print(f"  ❌ Lidarr error: {error}")
                except:
                    print(f"  ❌ Error adding artist: {e}")
                return False
            print(f"  ❌ Error adding artist: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error adding artist: {e}")
            return False


def resolve_release_id(id_input: str) -> Optional[str]:
    """Resolve a release ID or release group ID to a release ID.

    If the input is a release group ID, returns the first release in that group.
    If the input is already a release ID, returns it as-is.

    Args:
        id_input: Either a release ID or release group ID.

    Returns:
        A release ID, or None if resolution fails.
    """
    # First try to see if it's a release group
    try:
        result = musicbrainzngs.get_release_group_by_id(
            id_input,
            includes=['releases']
        )
        release_group = result['release-group']

        # Check if there are releases in this group
        if 'release-list' in release_group and release_group['release-list']:
            first_release = release_group['release-list'][0]
            release_id = first_release['id']
            print(f"📀 Release group detected: {release_group.get('title', 'Unknown')}")
            print(f"   Using first release: {first_release.get('title', 'Unknown')} ({release_id})")
            return release_id
        else:
            print(f"⚠️  Release group found but has no releases")
            return None

    except musicbrainzngs.WebServiceError:
        # Not a release group, assume it's a release ID
        return id_input
    except Exception as e:
        print(f"Error resolving ID: {e}")
        return id_input


def get_release_artists(release_id: str) -> List[Dict]:
    """Get all artists from a MusicBrainz release.

    Retrieves all artist credits from a MusicBrainz release, including both
    release-level and track-level artist credits. This is essential for
    various artists compilations to get all contributing artists.

    Args:
        release_id: The MusicBrainz release ID.

    Returns:
        List of dictionaries containing artist information (id, name, sort_name).
        Returns empty list if an error occurs.
    """
    try:
        result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=['artists', 'artist-credits', 'recordings']
        )
        release = result['release']

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
                        # Check recording artist credits
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

                        # Also check track-level artist credits
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

    except musicbrainzngs.WebServiceError as e:
        print(f"MusicBrainz error: {e}")
        return []
    except Exception as e:
        print(f"Error fetching release: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(
        description='Add all artists from a MusicBrainz release to Lidarr'
    )
    parser.add_argument('release_id', help='MusicBrainz release ID or release group ID')
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', required=True, help='Lidarr API key')
    parser.add_argument('--monitor', action='store_true', default=True, help='Monitor artists (default: True)')
    parser.add_argument('--no-monitor', dest='monitor', action='store_false', help='Do not monitor artists')
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

    # Resolve release ID (handles both release IDs and release group IDs)
    print(f"🔍 Resolving ID {args.release_id}...")
    resolved_release_id = resolve_release_id(args.release_id)

    if not resolved_release_id:
        print("❌ Could not resolve to a valid release ID.")
        sys.exit(1)

    print()

    # Get artists from MusicBrainz release
    print(f"🎵 Fetching release {resolved_release_id} from MusicBrainz...")
    artists = get_release_artists(resolved_release_id)
    
    if not artists:
        print("❌ No artists found for this release.")
        sys.exit(1)
    
    print(f"✓ Found {len(artists)} artist(s)")
    print()
    
    # Add each artist to Lidarr
    added = 0
    skipped = 0
    
    for artist in artists:
        print(f"Processing: {artist['name']} ({artist['id']})")

        # Skip "Various Artists" - it's a placeholder, not a real artist
        if artist['id'] == '89ad4ac3-39f7-470e-963a-56509c546377':
            print(f"  ⏭️  Skipping Various Artists")
            skipped += 1
            print()
            continue

        # Search for artist in Lidarr
        artist_data = lidarr.search_artist(artist['id'])

        if not artist_data:
            print(f"  ⚠️  Could not find artist in Lidarr search")
            skipped += 1
            continue

        # Check if artist is already in Lidarr (has an 'id' in the nested object)
        if 'artist' in artist_data and isinstance(artist_data['artist'], dict):
            if 'id' in artist_data['artist']:
                print(f"  ⚠️  Artist already in Lidarr")
                skipped += 1
                print()
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
            print(f"  ✓ Added successfully")
            added += 1
        else:
            skipped += 1
        
        print()
    
    # Summary
    print("=" * 50)
    print(f"Summary:")
    print(f"  Added: {added}")
    print(f"  Skipped: {skipped}")
    print(f"  Total: {len(artists)}")


if __name__ == '__main__':
    main()
