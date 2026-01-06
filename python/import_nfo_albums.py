#!/usr/bin/env python3
"""
Accelerate Lidarr album imports using MusicBrainz IDs from album.nfo files.

This script is useful when Lidarr has issues with text-based artist searches or when
you need to batch import many albums quickly. It scans a music directory for album.nfo
files, extracts MusicBrainz release group IDs, and adds those albums directly to Lidarr
using the API. This bypasses text search issues and provides more reliable imports.

Prerequisites:
    - Each album folder must contain an album.nfo file with MusicBrainz metadata
    - NFO files should include <musicbrainzreleasegroupid> or <musicbrainzalbumid> tags

Requires: requests
Install: pip install requests
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

# Configuration
LIDARR_URL = "http://localhost:8686"  # Your Lidarr URL
LIDARR_API_KEY = "your_api_key_here"  # Your Lidarr API key
MUSIC_FOLDER_PATH = "/path/to/music"  # Root folder containing album.nfo files
QUALITY_PROFILE_ID = 1  # Quality profile ID in Lidarr
METADATA_PROFILE_ID = 1  # Metadata profile ID in Lidarr
ROOT_FOLDER_PATH = "/music"  # Root folder path in Lidarr


def find_nfo_files(root_path: str) -> List[str]:
    """Find all album.nfo files in the directory tree.
    
    Args:
        root_path: Root directory to search for NFO files.
        
    Returns:
        List of absolute paths to album.nfo files found.
    """
    nfo_files = []
    for root, dirs, files in os.walk(root_path):
        for file in files:
            if file.lower() == "album.nfo":
                nfo_files.append(os.path.join(root, file))
    return nfo_files

def extract_musicbrainz_id(nfo_path: str) -> Optional[str]:
    """Extract MusicBrainz release group ID from NFO file.
    
    Attempts to parse the NFO file as XML (Kodi format) first, looking for
    musicbrainzreleasegroupid or musicbrainzalbumid tags. Falls back to
    regex pattern matching if XML parsing fails.
    
    Args:
        nfo_path: Path to the album.nfo file.
        
    Returns:
        MusicBrainz release group ID if found, None otherwise.
    """
    try:
        # Try parsing as XML first (Kodi format)
        tree = ET.parse(nfo_path)
        root = tree.getroot()
        
        # Look for musicbrainzreleasegroupid tag
        mb_id = root.find('.//musicbrainzreleasegroupid')
        if mb_id is not None and mb_id.text:
            return mb_id.text.strip()
        
        # Also check for musicbrainzalbumid as fallback
        mb_id = root.find('.//musicbrainzalbumid')
        if mb_id is not None and mb_id.text:
            return mb_id.text.strip()
            
    except ET.ParseError:
        # If XML parsing fails, try regex search
        try:
            with open(nfo_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for UUID format
                match = re.search(r'<musicbrainzreleasegroupid>([a-f0-9-]{36})</musicbrainzreleasegroupid>', content, re.IGNORECASE)
                if match:
                    return match.group(1)
                match = re.search(r'<musicbrainzalbumid>([a-f0-9-]{36})</musicbrainzalbumid>', content, re.IGNORECASE)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"Error reading {nfo_path}: {e}")
    
    return None

def check_album_exists(mb_id: str) -> bool:
    """Check if album already exists in Lidarr.
    
    Args:
        mb_id: MusicBrainz release group ID to check.
        
    Returns:
        True if album exists in Lidarr, False otherwise.
    """
    url = f"{LIDARR_URL}/api/v1/album"
    headers = {"X-Api-Key": LIDARR_API_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            albums = response.json()
            for album in albums:
                if album.get('foreignAlbumId') == mb_id:
                    return True
    except Exception as e:
        print(f"  Error checking if album exists: {e}")
    
    return False

def add_album_to_lidarr(mb_id: str, artist_mb_id: Optional[str] = None) -> Optional[bool]:
    """Add album to Lidarr using MusicBrainz release group ID.
    
    Searches for the album in Lidarr's database and adds it with the configured
    quality and metadata profiles. Checks for existing albums before attempting
    to add.
    
    Args:
        mb_id: MusicBrainz release group ID.
        artist_mb_id: Optional MusicBrainz artist ID (currently unused).
        
    Returns:
        True if album was successfully added.
        False if adding failed.
        None if album already exists in Lidarr.
    """
    # Check if album already exists
    if check_album_exists(mb_id):
        print(f"  ⊘ Album already exists in Lidarr, skipping")
        return None  # Return None to indicate "already exists"
    
    url = f"{LIDARR_URL}/api/v1/album"
    headers = {
        "X-Api-Key": LIDARR_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Search for the album first (using lidarr: prefix for MusicBrainz ID search)
    search_url = f"{LIDARR_URL}/api/v1/search"
    params = {"term": f"lidarr:{mb_id}"}
    
    try:
        response = requests.get(search_url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Failed to search for album {mb_id}")
            return False
        
        results = response.json()
        if not results:
            print(f"✗ No results found for {mb_id}")
            return False
        
        # Debug: Print what we got back
        print(f"  Found {len(results)} search result(s)")
        
        # Find the album in search results - handle different response structures
        album_data = None
        artist_data = None
        
        for i, result in enumerate(results):
            # Lidarr search can return: album objects directly, or nested in 'album' key
            if result.get('album'):
                current_album = result['album']
                current_artist = result.get('artist')
            else:
                current_album = result
                current_artist = result.get('artist')
            
            # Check if this is our album
            foreign_id = current_album.get('foreignAlbumId', '')
            if foreign_id == mb_id or foreign_id.endswith(mb_id):
                album_data = current_album
                artist_data = current_artist
                print(f"  Matched album: {current_album.get('title', 'Unknown')}")
                break
        
        if not album_data:
            print(f"✗ Album {mb_id} not found in search results")
            print(f"  Available IDs in results:")
            for result in results[:3]:  # Show first 3
                album = result.get('album', result)
                fid = album.get('foreignAlbumId', 'N/A')
                title = album.get('title', 'N/A')
                print(f"    - {fid}: {title}")
            return False
        
        # Get artist information
        artist_data = album_data.get('artist')
        if not artist_data:
            print(f"✗ No artist data found for album {mb_id}")
            return False
        
        # Ensure artist has required fields
        if not artist_data.get('qualityProfileId'):
            artist_data['qualityProfileId'] = QUALITY_PROFILE_ID
        if not artist_data.get('metadataProfileId'):
            artist_data['metadataProfileId'] = METADATA_PROFILE_ID
        if not artist_data.get('rootFolderPath'):
            artist_data['rootFolderPath'] = ROOT_FOLDER_PATH
        if not artist_data.get('monitored'):
            artist_data['monitored'] = True
        
        # Prepare the payload - include all necessary fields from search result
        payload = {
            "title": album_data.get('title'),
            "foreignAlbumId": mb_id,
            "monitored": True,
            "anyReleaseOk": True,
            "profileId": QUALITY_PROFILE_ID,
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
        
        # Add the album
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            album_title = album_data.get('title', mb_id)
            artist_name = artist_data.get('artistName', 'Unknown Artist')
            print(f"✓ Successfully added: {artist_name} - {album_title}")
            return True
        else:
            print(f"✗ Failed to add album {mb_id}: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"Error adding album {mb_id}: {e}")
        return False

def main() -> None:
    """Main function to process all album.nfo files and import to Lidarr.
    
    Scans the configured music folder for album.nfo files, extracts MusicBrainz
    IDs, and attempts to add each album to Lidarr. Prints a summary of results.
    """
    print(f"Scanning for album.nfo files in: {MUSIC_FOLDER_PATH}")
    nfo_files = find_nfo_files(MUSIC_FOLDER_PATH)
    print(f"Found {len(nfo_files)} album.nfo files\n")
    
    added = 0
    failed = 0
    skipped = 0
    already_exists = 0
    
    for nfo_path in nfo_files:
        print(f"Processing: {nfo_path}")
        mb_id = extract_musicbrainz_id(nfo_path)
        
        if not mb_id:
            print(f"  ✗ No MusicBrainz ID found")
            skipped += 1
            continue
        
        print(f"  Found ID: {mb_id}")
        
        result = add_album_to_lidarr(mb_id)
        if result is True:
            added += 1
        elif result is None:
            already_exists += 1
        else:
            failed += 1
        
        print()
    
    print("\n" + "="*50)
    print(f"Summary:")
    print(f"  Total NFO files: {len(nfo_files)}")
    print(f"  Successfully added: {added}")
    print(f"  Already in Lidarr: {already_exists}")
    print(f"  Failed: {failed}")
    print(f"  Skipped (no ID): {skipped}")
    print("="*50)

if __name__ == "__main__":
    main()
