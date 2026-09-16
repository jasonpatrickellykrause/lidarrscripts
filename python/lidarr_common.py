#!/usr/bin/env python3
"""
Shared helpers for the Lidarr scripts in this repo.

A small Lidarr v1 API client and a couple of MusicBrainz helpers that were
previously copy-pasted (with drifting bugs) across several scripts. Import
this module rather than re-implementing artist/album add logic.
"""

import sys
import time
from typing import Any, Dict, List, Optional

import requests

# MusicBrainz requires a real contact URL in the user agent, not a placeholder.
MB_USER_AGENT_CONTACT = "https://github.com/jasonpatrickellykrause/lidarrscripts"

# MusicBrainz's "Various Artists" placeholder - never a real artist to add.
VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"


class LidarrClient:
    """Thin wrapper around the Lidarr v1 API used by the scripts in this repo."""

    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}

    def _request(self, method: str, endpoint: str, params: Dict = None,
                 json_body: Dict = None, max_retries: int = 3) -> Optional[requests.Response]:
        """Issue a request, retrying transient failures (429/5xx/connection
        errors) with exponential backoff. Returns the raw Response (or None
        if every attempt failed) so callers can inspect status codes/bodies
        themselves, e.g. to detect an "already exists" 400.
        """
        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, f'{self.url}/api/v1/{endpoint}',
                    headers=self.headers, params=params, json=json_body, timeout=30
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    print(f"Error: {method} {endpoint} returned HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
                    return resp
                return resp
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                print(f"Error making {method} request to {endpoint}: {e}", file=sys.stderr)
                return None
        return None

    def get_json(self, endpoint: str, params: Dict = None) -> Any:
        """GET and return parsed JSON, or None on failure."""
        resp = self._request('GET', endpoint, params=params)
        if resp is None or not resp.ok:
            return None
        return resp.json() if resp.text else None

    def post_json(self, endpoint: str, json_body: Dict) -> Optional[requests.Response]:
        """POST arbitrary data to an endpoint not covered by a dedicated method.
        Returns the raw Response (or None on total failure) so callers can
        inspect status/body themselves.
        """
        return self._request('POST', endpoint, json_body=json_body)

    def get_root_folders(self) -> List[Dict]:
        return self.get_json('rootfolder') or []

    def get_root_folder(self) -> Optional[str]:
        """First configured root folder path, or None."""
        folders = self.get_root_folders()
        return folders[0]['path'] if folders else None

    def get_quality_profiles(self) -> List[Dict]:
        return self.get_json('qualityprofile') or []

    def get_quality_profile_id(self) -> Optional[int]:
        """First configured quality profile ID, or None."""
        profiles = self.get_quality_profiles()
        return profiles[0]['id'] if profiles else None

    def get_metadata_profiles(self) -> List[Dict]:
        return self.get_json('metadataprofile') or []

    def get_metadata_profile_id(self, name: Optional[str] = None) -> Optional[int]:
        """Metadata profile ID matching `name`, or the first available profile."""
        profiles = self.get_metadata_profiles()
        if not profiles:
            return None
        if name:
            for profile in profiles:
                if profile.get('name') == name:
                    return profile.get('id')
        return profiles[0].get('id')

    def get_tags(self) -> List[Dict]:
        return self.get_json('tag') or []

    def resolve_tag_id(self, name_or_id: str) -> Optional[int]:
        """Resolve a tag given either its numeric ID or its label."""
        if name_or_id.isdigit():
            return int(name_or_id)
        for tag in self.get_tags():
            if tag.get('label', '').lower() == name_or_id.lower():
                return tag.get('id')
        return None

    def search(self, term: str) -> Optional[List[Dict]]:
        return self.get_json('search', params={'term': term})

    def search_by_mbid(self, mbid: str) -> Optional[Dict]:
        """Search Lidarr's lookup for a MusicBrainz artist/album/release ID.
        Returns the first result dict, or None if nothing matched.
        """
        results = self.search(f'lidarr:{mbid}')
        return results[0] if results else None

    def get_artists(self) -> List[Dict]:
        return self.get_json('artist') or []

    def get_albums(self, artist_id: Optional[int] = None) -> List[Dict]:
        """All albums, or albums for a single artist if artist_id is given.

        Passing artist_id avoids downloading the whole library's album list
        just to filter it client-side.
        """
        params = {'artistId': artist_id} if artist_id is not None else None
        return self.get_json('album', params=params) or []

    def add_artist(self, payload: Dict) -> str:
        """POST a new artist. Returns 'added', 'skipped' (already exists), or 'failed'."""
        resp = self._request('POST', 'artist', json_body=payload)
        if resp is None:
            return 'failed'
        if resp.ok:
            return 'added'
        if resp.status_code == 400 and 'already been added' in resp.text.lower():
            return 'skipped'
        print(f"Response: {resp.text}", file=sys.stderr)
        return 'failed'

    def add_album(self, payload: Dict) -> str:
        """POST a standalone album. Returns 'added', 'skipped' (already exists), or 'failed'."""
        resp = self._request('POST', 'album', json_body=payload)
        if resp is None:
            return 'failed'
        if resp.ok:
            return 'added'
        if resp.status_code == 400 and 'already' in resp.text.lower():
            return 'skipped'
        print(f"Response: {resp.text}", file=sys.stderr)
        return 'failed'

    def update_artist(self, artist: Dict) -> bool:
        """PUT an updated artist record (pass the full record with your changes merged in)."""
        resp = self._request('PUT', f'artist/{artist["id"]}', json_body=artist)
        return resp is not None and resp.ok

    def delete_album(self, album_id: int) -> bool:
        resp = self._request('DELETE', f'album/{album_id}')
        return resp is not None and resp.ok

    def run_command(self, name: str, **params) -> bool:
        """Issue a Lidarr command (e.g. AlbumSearch, ArtistSearch, RescanFolders)."""
        resp = self._request('POST', 'command', json_body={'name': name, **params})
        return resp is not None and resp.ok

    def test_all_indexers(self) -> Any:
        """POST /indexer/testall - tests every configured indexer at once."""
        resp = self._request('POST', 'indexer/testall')
        if resp is None:
            return None
        return resp.json() if resp.text else None

    def test_all_download_clients(self) -> Any:
        """POST /downloadclient/testall - tests every configured download client at once."""
        resp = self._request('POST', 'downloadclient/testall')
        if resp is None:
            return None
        return resp.json() if resp.text else None


def build_artist_payload(foreign_artist_id: str, artist_name: str, root_folder: str,
                          quality_profile_id: int, metadata_profile_id: int,
                          monitored: bool = True, search_for_missing: bool = False,
                          tags: Optional[List[int]] = None) -> Dict:
    """Build the POST body Lidarr expects to add a new artist."""
    payload = {
        'foreignArtistId': foreign_artist_id,
        'artistName': artist_name,
        'qualityProfileId': quality_profile_id,
        'metadataProfileId': metadata_profile_id,
        'rootFolderPath': root_folder,
        'monitored': monitored,
        'addOptions': {
            'monitor': 'all' if monitored else 'none',
            'searchForMissingAlbums': search_for_missing
        }
    }
    if tags:
        payload['tags'] = tags
    return payload


def build_album_payload(album_data: Dict, artist_data: Dict, release_id: str,
                         quality_profile_id: int, monitored: bool = True) -> Dict:
    """Build the POST body Lidarr expects to add a standalone album.

    `album_data` and `artist_data` are typically the dicts Lidarr's own
    /api/v1/search endpoint returns for a `lidarr:<mbid>` lookup.
    """
    return {
        'title': album_data.get('title', 'Unknown'),
        'foreignAlbumId': release_id,
        'monitored': monitored,
        'anyReleaseOk': True,
        'profileId': quality_profile_id,
        'duration': album_data.get('duration', 0),
        'albumType': album_data.get('albumType', ''),
        'secondaryTypes': album_data.get('secondaryTypes', []),
        'mediumCount': album_data.get('mediumCount', 0),
        'ratings': album_data.get('ratings', {'votes': 0, 'value': 0.0}),
        'releaseDate': album_data.get('releaseDate'),
        'releases': album_data.get('releases', []),
        'genres': album_data.get('genres', []),
        'media': album_data.get('media', []),
        'artist': artist_data,
        'images': album_data.get('images', []),
        'links': album_data.get('links', []),
        'addOptions': {
            'searchForNewAlbum': False
        }
    }


def extract_foreign_artist_id(artist_data: Dict) -> Optional[str]:
    """Pull the MusicBrainz artist ID out of a Lidarr search-result shape,
    which varies depending on whether the artist is nested under 'artist'.
    """
    return (artist_data.get('foreignArtistId') or
            artist_data.get('foreignId') or
            (artist_data.get('artist') or {}).get('foreignArtistId'))


def extract_artist_name(artist_data: Dict) -> Optional[str]:
    """Pull the artist name out of a Lidarr search-result shape."""
    if isinstance(artist_data.get('artist'), dict):
        return artist_data['artist'].get('artistName') or artist_data['artist'].get('name')
    return artist_data.get('artistName') or artist_data.get('name')


def mb_get_release_artists(musicbrainzngs, release_id: str) -> List[Dict]:
    """Get every distinct artist credited on a MusicBrainz release, at both
    the release level and the track level (needed for "Various Artists"
    compilations where each track has its own credited artist).

    Takes the musicbrainzngs module as a parameter so this helper has no
    hard import dependency for scripts that don't need it.

    Returns a list of {'id', 'name', 'sort_name'} dicts, deduplicated by id.
    """
    try:
        result = musicbrainzngs.get_release_by_id(
            release_id, includes=['artists', 'artist-credits', 'recordings']
        )
        release = result['release']
    except Exception as e:
        print(f"  Error fetching release: {e}", file=sys.stderr)
        return []

    artists = []
    seen_ids = set()

    def add_credit(credit):
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

    for credit in release.get('artist-credit', []):
        add_credit(credit)

    for medium in release.get('medium-list', []):
        for track in medium.get('track-list', []):
            for credit in track.get('recording', {}).get('artist-credit', []):
                add_credit(credit)
            for credit in track.get('artist-credit', []):
                add_credit(credit)

    return artists
