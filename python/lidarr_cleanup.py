#!/usr/bin/env python3
"""
Clean up Lidarr library by removing missing albums and adjusting artist settings.

This script processes all artists in your Lidarr library to:
1. Remove missing albums (unmonitored albums or albums with no files/tracks)
2. Set artist monitoring to "no new albums" (monitorNewItems = 'none')
3. Set artist metadata profile to "None"

This is useful for cleaning up after bulk imports or reducing active monitoring load.

Requires: requests
Install: pip install requests

Created with assistance from Claude (Anthropic) - https://claude.ai
"""

import sys
import argparse
import requests
import time
from typing import List, Dict, Optional


class LidarrCleanup:
    """Handle Lidarr cleanup operations including missing album removal and artist configuration.

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
        self.none_profile_id = None

    def _make_request(self, endpoint: str, method: str = 'GET', data: Dict = None) -> Optional[Dict]:
        """Make a request to the Lidarr API.

        Args:
            endpoint: API endpoint (without /api/v1/ prefix).
            method: HTTP method (GET, POST, DELETE, PUT).
            data: Request body for POST/PUT requests.

        Returns:
            Response JSON or None if request failed.
        """
        try:
            url = f"{self.url}/api/v1/{endpoint}"

            if method == 'GET':
                resp = requests.get(url, headers=self.headers, timeout=30)
            elif method == 'POST':
                resp = requests.post(url, headers=self.headers, json=data, timeout=30)
            elif method == 'PUT':
                resp = requests.put(url, headers=self.headers, json=data, timeout=30)
            elif method == 'DELETE':
                resp = requests.delete(url, headers=self.headers, timeout=30)
            else:
                print(f"Unsupported method: {method}")
                return None

            resp.raise_for_status()
            return resp.json() if resp.text else None

        except requests.exceptions.RequestException as e:
            print(f"Error ({method} {endpoint}): {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None

    def get_none_metadata_profile_id(self) -> Optional[int]:
        """Get the metadata profile ID for "None" profile.

        Returns:
            Profile ID for "None" profile, or first profile ID if "None" doesn't exist.
        """
        try:
            profiles = self._make_request('metadataprofile')
            if not profiles:
                return None

            # Look for "None" profile
            for profile in profiles:
                if profile.get('name') == 'None':
                    self.none_profile_id = profile.get('id')
                    return self.none_profile_id

            # Fallback to first profile
            self.none_profile_id = profiles[0].get('id')
            return self.none_profile_id

        except Exception as e:
            print(f"Error getting metadata profiles: {e}")
            return None

    def get_all_artists(self) -> List[Dict]:
        """Fetch all artists from Lidarr.

        Returns:
            List of artist dictionaries.
        """
        try:
            artists = self._make_request('artist')
            return artists if artists else []
        except Exception as e:
            print(f"Error fetching artists: {e}")
            return []

    def get_albums_for_artist(self, artist_id: int) -> List[Dict]:
        """Fetch all albums for a specific artist.

        Args:
            artist_id: Lidarr artist ID.

        Returns:
            List of album dictionaries for the artist.
        """
        try:
            albums = self._make_request('album')
            if not albums:
                return []

            # Filter to this artist's albums
            return [a for a in albums if a.get('artistId') == artist_id]

        except Exception as e:
            print(f"Error fetching albums for artist {artist_id}: {e}")
            return []

    def is_missing_album(self, album: Dict) -> bool:
        """Check if an album is considered "missing".

        An album is missing if:
        - It is unmonitored (monitored=false), OR
        - It has no tracks found (statistics.totalTrackCount=0)

        Args:
            album: Album dictionary from Lidarr API.

        Returns:
            True if album is missing, False otherwise.
        """
        # Check if unmonitored
        if not album.get('monitored'):
            return True

        # Check if no tracks found
        stats = album.get('statistics', {})
        total_tracks = stats.get('totalTrackCount', 0)
        if total_tracks == 0:
            return True

        return False

    def delete_album(self, album_id: int) -> bool:
        """Delete an album from Lidarr.

        Args:
            album_id: Lidarr album ID.

        Returns:
            True if deletion was successful, False otherwise.
        """
        try:
            self._make_request(f'album/{album_id}', method='DELETE')
            return True
        except Exception as e:
            print(f"Error deleting album {album_id}: {e}")
            return False

    def update_artist(self, artist: Dict) -> bool:
        """Update artist settings (monitoring and metadata profile).

        Args:
            artist: Artist dictionary to update.

        Returns:
            True if update was successful, False otherwise.
        """
        try:
            # Prepare update payload - keep all original fields and update specific ones
            # This ensures we don't accidentally omit required fields that Lidarr expects
            payload = artist.copy()

            # Update only the fields we need to change
            payload['metadataProfileId'] = self.none_profile_id
            payload['monitorNewItems'] = 'none'  # "no new albums"

            # Use PUT to update existing artist
            result = self._make_request(f'artist/{artist.get("id")}', method='PUT', data=payload)
            return result is not None

        except Exception as e:
            print(f"Error updating artist {artist.get('artistName')}: {e}")
            return False

    def cleanup_artist(self, artist: Dict, dry_run: bool = False, delay: float = 0.5) -> Dict:
        """Clean up a single artist (remove missing albums, update settings).

        Args:
            artist: Artist dictionary to process.
            dry_run: If True, don't make actual changes.
            delay: Delay in seconds between API calls.

        Returns:
            Dictionary with stats from processing this artist.
        """
        artist_name = artist.get('artistName', 'Unknown')
        artist_id = artist.get('id')

        stats = {
            'deleted': 0,
            'failed_delete': 0,
            'updated': False,
            'failed_update': False
        }

        # Get all albums for this artist
        albums = self.get_albums_for_artist(artist_id)
        missing_albums = [a for a in albums if self.is_missing_album(a)]

        # Delete missing albums
        for album in missing_albums:
            album_title = album.get('title', 'Unknown')
            album_id = album.get('id')

            if dry_run:
                print(f"    Would delete: {album_title}")
                stats['deleted'] += 1
            else:
                if self.delete_album(album_id):
                    print(f"    Deleted: {album_title}")
                    stats['deleted'] += 1
                    time.sleep(delay)
                else:
                    print(f"    Failed to delete: {album_title}")
                    stats['failed_delete'] += 1

        # Update artist settings
        if dry_run:
            print(f"    Would update monitoring and metadata profile")
            stats['updated'] = True
        else:
            if self.update_artist(artist):
                print(f"    Updated monitoring to 'no new albums' and metadata profile to 'None'")
                stats['updated'] = True
                time.sleep(delay)
            else:
                print(f"    Failed to update artist settings")
                stats['failed_update'] = True

        return stats

    def run(self, max_artists: Optional[int] = None, dry_run: bool = False, delay: float = 0.5) -> Dict:
        """Run the cleanup operation on all artists.

        Args:
            max_artists: Maximum number of artists to process (None = all).
            dry_run: If True, preview changes without making them.
            delay: Delay in seconds between API calls.

        Returns:
            Dictionary with overall statistics.
        """
        print("🔍 Getting Lidarr configuration...")

        # Get the "None" metadata profile ID
        if not self.get_none_metadata_profile_id():
            print("❌ Could not find metadata profiles")
            return {}

        print(f"✓ Using metadata profile ID: {self.none_profile_id}")
        print()

        # Get all artists
        print("🎵 Fetching all artists...")
        artists = self.get_all_artists()

        if not artists:
            print("❌ No artists found in Lidarr")
            return {}

        print(f"✓ Found {len(artists)} artist(s)")
        print()

        # Limit artists if requested
        artists_to_process = artists
        if max_artists and len(artists) > max_artists:
            artists_to_process = artists[:max_artists]
            print(f"⚠️  Limiting to {max_artists} artist(s) (out of {len(artists)})")
            print()

        if dry_run:
            print("=" * 50)
            print("DRY RUN MODE - No changes will be made")
            print("=" * 50)
            print()

        # Process each artist
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

            stats = self.cleanup_artist(artist, dry_run=dry_run, delay=delay)

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
        description='Clean up Lidarr library by removing missing albums and updating artist settings'
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', required=True, help='Lidarr API key')
    parser.add_argument('--max-artists', type=int, default=None,
                       help='Maximum number of artists to process (default: all)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be changed without making changes')
    parser.add_argument('--delay', type=float, default=0.5,
                       help='Delay between API calls in seconds (default: 0.5)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output')

    args = parser.parse_args()

    # Initialize cleanup
    cleanup = LidarrCleanup(args.url, args.api_key)

    # Run cleanup
    stats = cleanup.run(max_artists=args.max_artists, dry_run=args.dry_run, delay=args.delay)

    # Print summary
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
