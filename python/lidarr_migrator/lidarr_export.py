#!/usr/bin/env python3
"""
Lidarr Export Script
Exports all artists and albums from a Lidarr instance for importing into another instance.
"""

import requests
import json
import argparse
import os
from typing import Dict, List, Any
from datetime import datetime
import sys


class LidarrExporter:
    """Exports artists and albums from a Lidarr instance."""
    def __init__(self, url: str, api_key: str):
        """
        Initialize the Lidarr exporter.
        
        Args:
            url: Lidarr instance URL (e.g., http://localhost:8686)
            api_key: Lidarr API key
        """
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {'X-Api-Key': api_key}
        
    def _make_request(self, endpoint: str) -> Any:
        """Make a request to the Lidarr API."""
        try:
            response = requests.get(
                f"{self.url}/api/v1/{endpoint}",
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {endpoint}: {e}", file=sys.stderr)
            sys.exit(1)
    
    def get_artists(self) -> List[Dict[str, Any]]:
        """Fetch all artists from Lidarr."""
        print("Fetching artists...")
        artists = self._make_request('artist')
        print(f"Found {len(artists)} artists")
        return artists
    
    def get_albums(self) -> List[Dict[str, Any]]:
        """Fetch all albums from Lidarr."""
        print("Fetching albums...")
        albums = self._make_request('album')
        print(f"Found {len(albums)} albums")
        return albums
    
    def export_data(self, output_file: str = None, format_type: str = 'json'):
        """
        Export artists and albums to a file.
        
        Args:
            output_file: Output file path. If None, generates timestamped filename.
            format_type: Export format ('json' or 'csv')
        """
        artists = self.get_artists()
        albums = self.get_albums()
        
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"lidarr_export_{timestamp}.{format_type}"
        
        if format_type == 'json':
            self._export_json(artists, albums, output_file)
        elif format_type == 'csv':
            self._export_csv(artists, albums, output_file)
        else:
            print(f"Unsupported format: {format_type}", file=sys.stderr)
            sys.exit(1)
    
    def _export_json(self, artists: List[Dict], albums: List[Dict], output_file: str):
        """Export data as JSON."""
        export_data = {
            'export_date': datetime.now().isoformat(),
            'lidarr_url': self.url,
            'total_artists': len(artists),
            'total_albums': len(albums),
            'artists': [self._format_artist_for_export(artist) for artist in artists],
            'albums': [self._format_album_for_export(album) for album in albums]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"\nExport complete: {output_file}")
        print(f"  - {len(artists)} artists")
        print(f"  - {len(albums)} albums")
    
    def _flatten_for_csv(self, data: Dict) -> Dict:
        """Flatten list/dict values into CSV-safe strings.

        DictWriter raises if a row has keys the header didn't declare, so the
        header must always be derived from the same formatting function as
        the rows (see _export_csv) rather than a hand-maintained list.
        """
        flat = {}
        for key, value in data.items():
            if isinstance(value, list):
                if value and isinstance(value[0], dict):
                    flat[key] = json.dumps(value, ensure_ascii=False)
                else:
                    flat[key] = ', '.join(str(item) for item in value)
            else:
                flat[key] = value
        return flat

    def _export_csv(self, artists: List[Dict], albums: List[Dict], output_file: str):
        """Export data as CSV (separate files for artists and albums)."""
        import csv

        # Export artists
        artists_file = output_file.replace('.csv', '_artists.csv')
        with open(artists_file, 'w', newline='', encoding='utf-8') as f:
            if artists:
                rows = [self._flatten_for_csv(self._format_artist_for_export(a)) for a in artists]
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

        # Export albums
        albums_file = output_file.replace('.csv', '_albums.csv')
        with open(albums_file, 'w', newline='', encoding='utf-8') as f:
            if albums:
                rows = [self._flatten_for_csv(self._format_album_for_export(a)) for a in albums]
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

        print(f"\nExport complete:")
        print(f"  - Artists: {artists_file} ({len(artists)} artists)")
        print(f"  - Albums: {albums_file} ({len(albums)} albums)")
    
    def _format_artist_for_export(self, artist: Dict) -> Dict:
        """Format artist data for export, keeping only importable fields."""
        return {
            'artistName': artist.get('artistName'),
            'foreignArtistId': artist.get('foreignArtistId'),
            'overview': artist.get('overview'),
            'artistType': artist.get('artistType'),
            'disambiguation': artist.get('disambiguation'),
            'links': artist.get('links', []),
            'genres': artist.get('genres', []),
            'status': artist.get('status'),
            'images': artist.get('images', []),
            'path': artist.get('path'),
            'qualityProfileId': artist.get('qualityProfileId'),
            'metadataProfileId': artist.get('metadataProfileId'),
            'monitored': artist.get('monitored'),
            'monitorNewItems': artist.get('monitorNewItems'),
            'tags': artist.get('tags', [])
        }
    
    def _format_album_for_export(self, album: Dict) -> Dict:
        """Format album data for export, keeping only importable fields."""
        return {
            'title': album.get('title'),
            'foreignAlbumId': album.get('foreignAlbumId'),
            'artistName': album.get('artist', {}).get('artistName') if album.get('artist') else None,
            'artistId': album.get('artistId'),
            'releaseDate': album.get('releaseDate'),
            'albumType': album.get('albumType'),
            'genres': album.get('genres', []),
            'overview': album.get('overview'),
            'disambiguation': album.get('disambiguation'),
            'monitored': album.get('monitored'),
            'anyReleaseOk': album.get('anyReleaseOk'),
            'images': album.get('images', [])
        }
    
    def export_musicbrainz_ids(self, output_file: str = None):
        """
        Export just MusicBrainz IDs for simple artist import.
        This creates a lightweight file that can be used with Lidarr's bulk import.
        """
        artists = self.get_artists()
        
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"lidarr_mbids_{timestamp}.txt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for artist in artists:
                mbid = artist.get('foreignArtistId')
                if mbid:
                    f.write(f"{mbid}\n")
        
        print(f"\nMusicBrainz IDs exported: {output_file}")
        print(f"  - {len(artists)} artist IDs")


def main():
    parser = argparse.ArgumentParser(
        description='Export artists and albums from Lidarr',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export to JSON (default)
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY
  
  # Export to CSV
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY --format csv
  
  # Export only MusicBrainz IDs for bulk import
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY --mbids-only
  
  # Specify output file
  %(prog)s --url http://localhost:8686 --api-key YOUR_API_KEY -o my_export.json
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
        '-o', '--output',
        help='Output file path (default: auto-generated with timestamp)'
    )
    
    parser.add_argument(
        '--format',
        choices=['json', 'csv'],
        default='json',
        help='Export format (default: json)'
    )
    
    parser.add_argument(
        '--mbids-only',
        action='store_true',
        help='Export only MusicBrainz IDs (lightweight, for bulk artist import)'
    )
    
    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    exporter = LidarrExporter(args.url, args.api_key)
    
    if args.mbids_only:
        exporter.export_musicbrainz_ids(args.output)
    else:
        exporter.export_data(args.output, args.format)


if __name__ == '__main__':
    main()
