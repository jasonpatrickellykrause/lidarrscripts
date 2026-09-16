#!/usr/bin/env python3
"""
Lidarr Import Script
Imports artists and albums into a Lidarr instance from an export file.
"""

import requests
import json
import argparse
import os
from typing import Dict, List, Any
import sys
import time


class LidarrImporter:
    """Imports artists into a Lidarr instance from an export file."""
    def __init__(self, url: str, api_key: str, root_folder: str):
        """
        Initialize the Lidarr importer.
        
        Args:
            url: Lidarr instance URL (e.g., http://localhost:8686)
            api_key: Lidarr API key
            root_folder: Root folder path for music library
        """
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.root_folder = root_folder
        self.headers = {'X-Api-Key': api_key}
        self.quality_profile_id = None
        self.metadata_profile_id = None
        
    def _make_request(self, endpoint: str, method: str = 'GET', data: Dict = None,
                       max_retries: int = 3) -> Any:
        """Make a request to the Lidarr API.

        Retries transient failures (connection errors, timeouts, 429, 5xx)
        with exponential backoff, since imports can run against a
        MusicBrainz-backed lookup that rate-limits under load.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                if method == 'GET':
                    response = requests.get(
                        f"{self.url}/api/v1/{endpoint}",
                        headers=self.headers,
                        timeout=30
                    )
                elif method == 'POST':
                    response = requests.post(
                        f"{self.url}/api/v1/{endpoint}",
                        headers=self.headers,
                        json=data,
                        timeout=30
                    )
                else:
                    raise ValueError(f"Unsupported method: {method}")

                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    print(f"Error making {method} request to {endpoint}: {last_error}", file=sys.stderr)
                    return None

                response.raise_for_status()
                return response.json() if response.text else None
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                print(f"Error making {method} request to {endpoint}: {e}", file=sys.stderr)
                if hasattr(e, 'response') and e.response is not None:
                    print(f"Response: {e.response.text}", file=sys.stderr)
                return None
        return None

    def _post_raw(self, endpoint: str, data: Dict):
        """POST and return the raw response (status + body) instead of raising.

        Used where the caller needs to distinguish "artist already exists"
        (a 400 with a specific message) from a genuine failure.
        """
        try:
            return requests.post(
                f"{self.url}/api/v1/{endpoint}",
                headers=self.headers,
                json=data,
                timeout=30
            )
        except requests.exceptions.RequestException as e:
            print(f"Error making POST request to {endpoint}: {e}", file=sys.stderr)
            return None
    
    def get_profiles(self):
        """Fetch quality and metadata profiles, or exit if none are configured.

        Every artist add depends on a valid profile ID; continuing with None
        just defers the same failure to every artist in the batch instead of
        catching it once, up front.
        """
        print("Fetching quality profiles...")
        quality_profiles = self._make_request('qualityprofile')
        if not quality_profiles:
            print("Error: no quality profiles found on the target instance "
                  "(or the request failed). Create one in Settings > Profiles "
                  "before importing.", file=sys.stderr)
            sys.exit(1)
        self.quality_profile_id = quality_profiles[0]['id']
        print(f"Using quality profile: {quality_profiles[0]['name']} (ID: {self.quality_profile_id})")

        print("Fetching metadata profiles...")
        metadata_profiles = self._make_request('metadataprofile')
        if not metadata_profiles:
            print("Error: no metadata profiles found on the target instance "
                  "(or the request failed). Create one in Settings > Profiles "
                  "before importing.", file=sys.stderr)
            sys.exit(1)
        self.metadata_profile_id = metadata_profiles[0]['id']
        print(f"Using metadata profile: {metadata_profiles[0]['name']} (ID: {self.metadata_profile_id})")

    def validate_root_folder(self):
        """Check that root_folder is registered on the target instance, or exit.

        Without this, a typo'd path fails silently on every single artist
        add after the (possibly long) lookup phase has already run.
        """
        root_folders = self._make_request('rootfolder')
        if root_folders is None:
            print("Error: could not fetch root folders from the target instance.", file=sys.stderr)
            sys.exit(1)

        known_paths = {rf['path'] for rf in root_folders}
        if self.root_folder not in known_paths:
            print(f"Error: '{self.root_folder}' is not a configured root folder on the target instance.", file=sys.stderr)
            print(f"Known root folders: {', '.join(sorted(known_paths)) or '(none)'}", file=sys.stderr)
            print("Add it under Settings > Media Management > Root Folders first.", file=sys.stderr)
            sys.exit(1)

    def lookup_artist(self, mbid: str) -> Dict:
        """Look up an artist by MusicBrainz ID."""
        return self._make_request(f'artist/lookup?term=lidarr:{mbid}')

    def add_artist(self, artist_data: Dict, monitored: bool = True) -> str:
        """
        Add an artist to Lidarr.

        Args:
            artist_data: Artist data from export or lookup
            monitored: Whether to monitor the artist

        Returns:
            'added', 'skipped' (already exists), or 'failed'
        """
        # Prepare artist payload
        payload = {
            'artistName': artist_data.get('artistName'),
            'foreignArtistId': artist_data.get('foreignArtistId'),
            'qualityProfileId': artist_data.get('qualityProfileId', self.quality_profile_id),
            'metadataProfileId': artist_data.get('metadataProfileId', self.metadata_profile_id),
            'monitored': monitored,
            'monitorNewItems': artist_data.get('monitorNewItems', 'all'),
            'rootFolderPath': self.root_folder,
            'addOptions': {
                'monitor': 'all' if monitored else 'none',
                'searchForMissingAlbums': False
            }
        }

        # Add optional fields if present
        if 'tags' in artist_data:
            payload['tags'] = artist_data['tags']

        response = self._post_raw('artist', payload)
        if response is None:
            return 'failed'
        if response.ok:
            return 'added'
        if response.status_code == 400 and 'already been added' in response.text.lower():
            return 'skipped'
        print(f"Response: {response.text}", file=sys.stderr)
        return 'failed'
    
    def import_from_export(self, export_file: str, dry_run: bool = False, 
                          delay: float = 0.5, monitored: bool = True):
        """
        Import artists from an export file.
        
        Args:
            export_file: Path to the export JSON file
            dry_run: If True, only simulate the import
            delay: Delay between API calls in seconds
            monitored: Whether to monitor imported artists
        """
        print(f"Loading export file: {export_file}")
        
        try:
            with open(export_file, 'r', encoding='utf-8') as f:
                export_data = json.load(f)
        except Exception as e:
            print(f"Error loading export file: {e}", file=sys.stderr)
            sys.exit(1)
        
        artists = export_data.get('artists', [])
        print(f"Found {len(artists)} artists to import")
        
        if dry_run:
            print("\n=== DRY RUN MODE - No changes will be made ===\n")

        # Get profiles and validate the root folder before starting the run,
        # so a bad config fails fast instead of after every artist lookup.
        self.get_profiles()
        if not dry_run:
            self.validate_root_folder()

        # Track statistics
        stats = {
            'total': len(artists),
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }

        # Import artists
        for i, artist in enumerate(artists, 1):
            artist_name = artist.get('artistName', 'Unknown')
            mbid = artist.get('foreignArtistId')

            print(f"\n[{i}/{len(artists)}] Processing: {artist_name}")

            if not mbid:
                print(f"  Skipping: no MusicBrainz ID")
                stats['skipped'] += 1
                continue

            if dry_run:
                print(f"  Would import: {artist_name} ({mbid})")
                stats['successful'] += 1
            else:
                # Look up artist to get current metadata
                print(f"  Looking up artist...")
                lookup_result = self.lookup_artist(mbid)

                if not lookup_result or (isinstance(lookup_result, list) and len(lookup_result) == 0):
                    print(f"  Failed: artist not found in MusicBrainz")
                    stats['failed'] += 1
                    continue

                # Handle list response
                if isinstance(lookup_result, list):
                    lookup_result = lookup_result[0]

                # Merge export data with lookup data
                import_data = lookup_result.copy()
                import_data.update({
                    'qualityProfileId': artist.get('qualityProfileId', self.quality_profile_id),
                    'metadataProfileId': artist.get('metadataProfileId', self.metadata_profile_id),
                    'monitored': artist.get('monitored', monitored),
                    'monitorNewItems': artist.get('monitorNewItems', 'all'),
                    'tags': artist.get('tags', [])
                })

                # Add artist
                result = self.add_artist(import_data, monitored)
                if result == 'added':
                    print(f"  Added: {artist_name}")
                    stats['successful'] += 1
                elif result == 'skipped':
                    print(f"  Skipped: {artist_name} already exists")
                    stats['skipped'] += 1
                else:
                    print(f"  Failed to add: {artist_name}")
                    stats['failed'] += 1

                # Rate limiting
                time.sleep(delay)
        
        # Print summary
        print("\n" + "="*50)
        print("IMPORT SUMMARY")
        print("="*50)
        print(f"Total artists: {stats['total']}")
        print(f"Successfully imported: {stats['successful']}")
        print(f"Failed: {stats['failed']}")
        print(f"Skipped: {stats['skipped']}")
        print("="*50)
    
    def import_from_mbid_list(self, mbid_file: str, dry_run: bool = False,
                             delay: float = 0.5, monitored: bool = True):
        """
        Import artists from a MusicBrainz ID list.
        
        Args:
            mbid_file: Path to file with one MBID per line
            dry_run: If True, only simulate the import
            delay: Delay between API calls in seconds
            monitored: Whether to monitor imported artists
        """
        print(f"Loading MusicBrainz ID list: {mbid_file}")
        
        try:
            with open(mbid_file, 'r', encoding='utf-8') as f:
                mbids = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"Error loading MBID file: {e}", file=sys.stderr)
            sys.exit(1)
        
        print(f"Found {len(mbids)} MusicBrainz IDs to import")
        
        if dry_run:
            print("\n=== DRY RUN MODE - No changes will be made ===\n")

        # Get profiles and validate the root folder before starting the run.
        self.get_profiles()
        if not dry_run:
            self.validate_root_folder()

        # Track statistics
        stats = {
            'total': len(mbids),
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }

        # Import artists
        for i, mbid in enumerate(mbids, 1):
            print(f"\n[{i}/{len(mbids)}] Processing MBID: {mbid}")

            if dry_run:
                print(f"  Would import artist with MBID: {mbid}")
                stats['successful'] += 1
            else:
                # Look up artist
                print(f"  Looking up artist...")
                lookup_result = self.lookup_artist(mbid)

                if not lookup_result or (isinstance(lookup_result, list) and len(lookup_result) == 0):
                    print(f"  Failed: artist not found")
                    stats['failed'] += 1
                    continue

                # Handle list response
                if isinstance(lookup_result, list):
                    lookup_result = lookup_result[0]

                artist_name = lookup_result.get('artistName', 'Unknown')

                # Add artist
                result = self.add_artist(lookup_result, monitored)
                if result == 'added':
                    print(f"  Added: {artist_name}")
                    stats['successful'] += 1
                elif result == 'skipped':
                    print(f"  Skipped: {artist_name} already exists")
                    stats['skipped'] += 1
                else:
                    print(f"  Failed to add: {artist_name}")
                    stats['failed'] += 1

                # Rate limiting
                time.sleep(delay)

        # Print summary
        print("\n" + "="*50)
        print("IMPORT SUMMARY")
        print("="*50)
        print(f"Total MBIDs: {stats['total']}")
        print(f"Successfully imported: {stats['successful']}")
        print(f"Failed: {stats['failed']}")
        print(f"Skipped: {stats['skipped']}")
        print("="*50)


def main():
    parser = argparse.ArgumentParser(
        description='Import artists into Lidarr from an export file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import from JSON export (dry run first)
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY \\
           --root-folder /music --file lidarr_export.json --dry-run
  
  # Actual import from JSON
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY \\
           --root-folder /music --file lidarr_export.json
  
  # Import from MusicBrainz ID list
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY \\
           --root-folder /music --mbid-file lidarr_mbids.txt
  
  # Import without monitoring (for manual management)
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY \\
           --root-folder /music --file lidarr_export.json --no-monitor
        """
    )
    
    parser.add_argument(
        '--url',
        required=True,
        help='Lidarr instance URL (e.g., http://localhost:8686)'
    )
    
    parser.add_argument(
        '--api-key',
        default=os.environ.get('LIDARR_API_KEY'),
        help='Lidarr API key (found in Settings > General). Falls back to the '
             'LIDARR_API_KEY environment variable, which avoids leaving the '
             'key in shell history.'
    )
    
    parser.add_argument(
        '--root-folder',
        required=True,
        help='Root folder path for music library (e.g., /music)'
    )
    
    parser.add_argument(
        '--file',
        help='Path to export JSON file'
    )
    
    parser.add_argument(
        '--mbid-file',
        help='Path to MusicBrainz ID list file (one per line)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate import without making changes'
    )
    
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay between API calls in seconds (default: 0.5)'
    )
    
    parser.add_argument(
        '--no-monitor',
        action='store_true',
        help='Do not monitor imported artists'
    )
    
    args = parser.parse_args()
    
    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    if not args.file and not args.mbid_file:
        parser.error("Either --file or --mbid-file must be specified")

    if args.file and args.mbid_file:
        parser.error("Specify only one of --file or --mbid-file")
    
    importer = LidarrImporter(args.url, args.api_key, args.root_folder)
    
    monitored = not args.no_monitor
    
    if args.file:
        importer.import_from_export(args.file, args.dry_run, args.delay, monitored)
    else:
        importer.import_from_mbid_list(args.mbid_file, args.dry_run, args.delay, monitored)


if __name__ == '__main__':
    main()
