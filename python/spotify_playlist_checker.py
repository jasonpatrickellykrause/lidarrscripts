#!/usr/bin/env python3
"""
Spotify Playlist Artist Streaming Service Checker

Takes a Spotify playlist URL and checks MusicBrainz for each artist's presence
on Spotify, Tidal, and Deezer.

Author: Jason (with assistance from Claude by Anthropic)
Created: January 2026

Usage:
    python spotify_playlist_checker.py <playlist_url> [options]

Requirements:
    - spotipy: pip install spotipy
    - requests: pip install requests
    - Spotify API credentials (SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET)

Example:
    export SPOTIPY_CLIENT_ID="your_client_id"
    export SPOTIPY_CLIENT_SECRET="your_client_secret"
    python spotify_playlist_checker.py "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
"""

import argparse
import os
import re
import sys
import time
from typing import Dict, List
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("Error: requests library not installed. Install with: pip install requests")
    sys.exit(1)

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
except ImportError:
    print("Error: spotipy library not installed. Install with: pip install spotipy")
    sys.exit(1)

# MusicBrainz API configuration
MB_API_URL = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "SpotifyPlaylistChecker/1.0 (https://github.com/yourusername/yourproject)"
MB_RATE_LIMIT = 1.0  # Seconds between requests (MusicBrainz requires 1 request per second)

# Streaming service URL patterns
SERVICE_PATTERNS = {
    "spotify": r"open\.spotify\.com/artist/",
    "tidal": r"tidal\.com/artist/",
    "deezer": r"deezer\.com/artist/",
}


class MusicBrainzClient:
    """Client for interacting with MusicBrainz API with rate limiting."""

    def __init__(self, user_agent: str):
        """
        Initialize MusicBrainz client.

        Args:
            user_agent: User agent string for API requests
        """
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )
        self.last_request_time = 0

    def _rate_limit(self) -> None:
        """Enforce rate limiting to comply with MusicBrainz API requirements."""
        elapsed = time.time() - self.last_request_time
        if elapsed < MB_RATE_LIMIT:
            time.sleep(MB_RATE_LIMIT - elapsed)
        self.last_request_time = time.time()

    def search_artist_by_spotify_id(self, spotify_id: str) -> Dict:
        """
        Search for artist in MusicBrainz by Spotify ID.

        Args:
            spotify_id: Spotify artist ID

        Returns:
            Dictionary containing search results or empty dict on error
        """
        self._rate_limit()

        params = {
            "query": f'url:"https://open.spotify.com/artist/{spotify_id}"',
            "fmt": "json",
        }

        try:
            response = self.session.get(f"{MB_API_URL}/artist", params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Warning: MusicBrainz API error: {e}", file=sys.stderr)
            return {}

    def get_artist_urls(self, mb_artist_id: str) -> List[Dict]:
        """
        Get all URLs for an artist from MusicBrainz.

        Args:
            mb_artist_id: MusicBrainz artist ID

        Returns:
            List of relation dictionaries containing URLs
        """
        self._rate_limit()

        params = {"inc": "url-rels", "fmt": "json"}

        try:
            response = self.session.get(
                f"{MB_API_URL}/artist/{mb_artist_id}", params=params
            )
            response.raise_for_status()
            data = response.json()
            return data.get("relations", [])
        except requests.RequestException as e:
            print(f"Warning: MusicBrainz API error: {e}", file=sys.stderr)
            return []


def extract_playlist_id(playlist_url: str) -> str:
    """
    Extract playlist ID from Spotify URL or URI.

    Args:
        playlist_url: Spotify playlist URL or URI

    Returns:
        Playlist ID

    Raises:
        ValueError: If URL format is invalid

    Examples:
        >>> extract_playlist_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        '37i9dQZF1DXcBWIGoYBM5M'
        >>> extract_playlist_id("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
        '37i9dQZF1DXcBWIGoYBM5M'
    """
    # Handle spotify: URI format
    if playlist_url.startswith("spotify:playlist:"):
        return playlist_url.split(":")[-1]

    # Handle https URL format
    parsed = urlparse(playlist_url)
    if "open.spotify.com" in parsed.netloc:
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "playlist":
            return path_parts[1].split("?")[0]

    raise ValueError(f"Invalid Spotify playlist URL: {playlist_url}")


def check_streaming_services(relations: List[Dict]) -> Dict[str, bool]:
    """
    Check which streaming services are linked in MusicBrainz relations.

    Args:
        relations: List of MusicBrainz relation dictionaries

    Returns:
        Dictionary with boolean values for each service
    """
    services = {"spotify": False, "tidal": False, "deezer": False}

    for relation in relations:
        if relation.get("type") == "streaming" and "url" in relation:
            url = relation["url"].get("resource", "")

            for service, pattern in SERVICE_PATTERNS.items():
                if re.search(pattern, url, re.IGNORECASE):
                    services[service] = True

    return services


def get_playlist_artists(spotify_client, playlist_id: str) -> List[Dict]:
    """
    Get unique artists from a Spotify playlist.

    Args:
        spotify_client: Initialized Spotipy client
        playlist_id: Spotify playlist ID

    Returns:
        List of dictionaries containing artist id and name
    """
    artists_dict = {}

    try:
        results = spotify_client.playlist_tracks(playlist_id)
        tracks = results["items"]

        # Handle pagination
        while results["next"]:
            results = spotify_client.next(results)
            tracks.extend(results["items"])

        # Extract unique artists
        for item in tracks:
            if item["track"] and item["track"]["artists"]:
                for artist in item["track"]["artists"]:
                    artist_id = artist["id"]
                    if artist_id not in artists_dict:
                        artists_dict[artist_id] = {
                            "id": artist_id,
                            "name": artist["name"],
                        }

        return list(artists_dict.values())

    except Exception as e:
        print(f"Error fetching playlist: {e}", file=sys.stderr)
        sys.exit(1)


def print_summary(results: List[Dict]) -> None:
    """
    Print summary statistics of streaming service coverage.

    Args:
        results: List of result dictionaries for each artist
    """
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total = len(results)
    in_mb = sum(1 for r in results if r["mb_found"])
    has_spotify = sum(1 for r in results if r["services"]["spotify"])
    has_tidal = sum(1 for r in results if r["services"]["tidal"])
    has_deezer = sum(1 for r in results if r["services"]["deezer"])
    has_all = sum(1 for r in results if all(r["services"].values()))

    print(f"\nTotal artists: {total}")
    print(f"Found in MusicBrainz: {in_mb} ({in_mb/total*100:.1f}%)")
    print(f"\nStreaming service coverage:")
    print(f"  Spotify: {has_spotify} ({has_spotify/total*100:.1f}%)")
    print(f"  Tidal: {has_tidal} ({has_tidal/total*100:.1f}%)")
    print(f"  Deezer: {has_deezer} ({has_deezer/total*100:.1f}%)")
    print(f"  All three: {has_all} ({has_all/total*100:.1f}%)")

    # Show artists missing from services
    missing_any = [
        r for r in results if r["mb_found"] and not all(r["services"].values())
    ]
    if missing_any:
        print(f"\n{len(missing_any)} artists missing from one or more services:")
        for r in missing_any[:10]:  # Show first 10
            missing = [s for s, v in r["services"].items() if not v]
            print(f"  • {r['name']} - missing: {', '.join(missing)}")

        if len(missing_any) > 10:
            print(f"  ... and {len(missing_any) - 10} more")
            print(f"\nUse --missing-only --output detailed for full list")


def print_detailed(results: List[Dict]) -> None:
    """
    Print detailed information for each artist.

    Args:
        results: List of result dictionaries for each artist
    """
    for r in results:
        print(f"\n{r['name']}")
        print(f"  Spotify ID: {r['spotify_id']}")
        print(f"  In MusicBrainz: {'Yes' if r['mb_found'] else 'No'}")
        if r["mb_found"]:
            print(f"  Has Spotify link: {'✓' if r['services']['spotify'] else '✗'}")
            print(f"  Has Tidal link: {'✓' if r['services']['tidal'] else '✗'}")
            print(f"  Has Deezer link: {'✓' if r['services']['deezer'] else '✗'}")


def print_csv(results: List[Dict]) -> None:
    """
    Print results in CSV format.

    Args:
        results: List of result dictionaries for each artist
    """
    print("Artist,Spotify ID,In MusicBrainz,Has Spotify,Has Tidal,Has Deezer")
    for r in results:
        print(
            f"{r['name']},{r['spotify_id']},{r['mb_found']},"
            f"{r['services']['spotify']},{r['services']['tidal']},{r['services']['deezer']}"
        )


def check_spotify_credentials() -> tuple:
    """
    Check for Spotify API credentials in environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        SystemExit: If credentials are not found
    """
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: Spotify API credentials not found.", file=sys.stderr)
        print(
            "Please set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET environment variables.",
            file=sys.stderr,
        )
        print("\nTo get credentials:", file=sys.stderr)
        print("1. Go to https://developer.spotify.com/dashboard", file=sys.stderr)
        print("2. Create an app", file=sys.stderr)
        print("3. Copy the Client ID and Client Secret", file=sys.stderr)
        sys.exit(1)

    return client_id, client_secret


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Check which streaming services artists from a Spotify playlist have on MusicBrainz",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
  %(prog)s "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M" --output csv
  %(prog)s "playlist_url" --missing-only --output detailed
        """,
    )
    parser.add_argument("playlist_url", help="Spotify playlist URL or URI")
    parser.add_argument(
        "--output",
        choices=["summary", "detailed", "csv"],
        default="summary",
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Only show artists missing from one or more services",
    )

    return parser.parse_args()


def main():
    """Main function to orchestrate the playlist checking process."""
    args = parse_arguments()

    # Check for Spotify credentials
    client_id, client_secret = check_spotify_credentials()

    # Initialize Spotify client
    try:
        spotify = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
        )
    except Exception as e:
        print(f"Error initializing Spotify client: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize MusicBrainz client
    mb_client = MusicBrainzClient(MB_USER_AGENT)

    # Extract playlist ID
    try:
        playlist_id = extract_playlist_id(args.playlist_url)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Get playlist info
    print(f"Fetching playlist information...")
    try:
        playlist = spotify.playlist(playlist_id)
        print(f"Playlist: {playlist['name']}")
        print(f"Owner: {playlist['owner']['display_name']}")
        print(f"Total tracks: {playlist['tracks']['total']}\n")
    except Exception as e:
        print(f"Error fetching playlist info: {e}", file=sys.stderr)
        sys.exit(1)

    # Get artists
    print("Fetching artists from playlist...")
    artists = get_playlist_artists(spotify, playlist_id)
    print(f"Found {len(artists)} unique artists\n")

    # Check each artist in MusicBrainz
    print("Checking MusicBrainz for streaming service links...")
    print("(This may take a while due to API rate limiting)\n")

    results = []

    for i, artist in enumerate(artists, 1):
        print(f"[{i}/{len(artists)}] Checking {artist['name']}...", end="\r")

        # Search MusicBrainz by Spotify ID
        mb_search = mb_client.search_artist_by_spotify_id(artist["id"])

        services = {"spotify": False, "tidal": False, "deezer": False}
        mb_found = False

        if mb_search.get("artists"):
            mb_artist = mb_search["artists"][0]
            mb_found = True

            # Get URLs for the artist
            relations = mb_client.get_artist_urls(mb_artist["id"])
            services = check_streaming_services(relations)

        results.append(
            {
                "name": artist["name"],
                "spotify_id": artist["id"],
                "mb_found": mb_found,
                "services": services,
            }
        )

    print()  # Clear the progress line

    # Filter results if requested
    if args.missing_only:
        results = [r for r in results if not all(r["services"].values())]

    # Output results based on format
    if args.output == "csv":
        print_csv(results)
    elif args.output == "detailed":
        print_detailed(results)
    else:  # summary
        print_summary(results)


if __name__ == "__main__":
    main()
