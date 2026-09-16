# lidarrscripts

A collection of scripts for managing a [Lidarr](https://lidarr.audio/) library: bulk imports, cleanup, migration between instances, and library health checks.

## Setup

```bash
pip install -r requirements.txt
```

Every Python script accepts `--api-key`, but all of them also fall back to the `LIDARR_API_KEY` environment variable, which keeps the key out of shell history:

```bash
export LIDARR_API_KEY="your-api-key"
```

Get your API key from Lidarr's **Settings > General > Show Advanced > API Key**.

Most scripts share `python/lidarr_common.py` for Lidarr API access - run scripts from inside the `python/` directory (or add it to your `PYTHONPATH`) so that import resolves.

## Python scripts

| Script | Purpose | Extra deps |
|---|---|---|
| [lidarr_migrator/](python/lidarr_migrator/) | Export/import an entire library (artists + albums) between two Lidarr instances. See its own [README](python/lidarr_migrator/README.md). | - |
| [lidarr_cleanup.py](python/lidarr_cleanup.py) | Remove unmonitored (and optionally empty-and-released) albums; set artist monitoring to "no new albums". | - |
| [lidarr_bulk_artist_update.py](python/lidarr_bulk_artist_update.py) | Bulk-update artists matching a filter (tag, genre, name, monitored status): reassign profiles, add/remove tags, change monitor-new-items. | - |
| [lidarr_wanted_search.py](python/lidarr_wanted_search.py) | List monitored-but-missing albums and optionally trigger `AlbumSearch` in batches. | - |
| [lidarr_duplicate_releases.py](python/lidarr_duplicate_releases.py) | Find albums with more downloaded track files than expected tracks (likely duplicate rips), using Lidarr's own data. | - |
| [lidarr_orphaned_artists.py](python/lidarr_orphaned_artists.py) | Find artists whose folder no longer exists on disk; optionally unmonitor them. Must run with the same filesystem view as Lidarr. | - |
| [lidarr_health_check.py](python/lidarr_health_check.py) | Pre-flight/monitoring check: Lidarr health, indexer connectivity, download client connectivity. Exit code reflects health. | - |
| [lidarr_importlist_migrate.py](python/lidarr_importlist_migrate.py) | Export/import configured import lists between instances (not covered by `lidarr_migrator`). Exported files contain plaintext credentials - handle like a secrets file. | - |
| [artist_secondary_releases.py](python/artist_secondary_releases.py) | Add every release where an artist appears as a featured/secondary credit (not primary artist). | `musicbrainzngs` |
| [mb_lidarr_import.py](python/mb_lidarr_import.py) | Add every artist credited on a MusicBrainz release (e.g. a compilation or soundtrack) to Lidarr. | `musicbrainzngs` |
| [lidarr_unmapped_import.py](python/lidarr_unmapped_import.py) | Resolve Lidarr's unmapped-files list via MusicBrainz and add the matching artists. | `musicbrainzngs` |
| [import_nfo_albums.py](python/import_nfo_albums.py) | Import albums directly from `album.nfo` MusicBrainz IDs, bypassing Lidarr's text search. | - |
| [spotify_playlist_checker.py](python/spotify_playlist_checker.py) | Check which streaming services (Spotify/Tidal/Deezer) each artist in a Spotify playlist has linked on MusicBrainz. | `spotipy` |

Every mutating script supports `--dry-run` to preview changes first, and most support `--delay` to throttle API calls.

## PowerShell scripts

| Script | Purpose |
|---|---|
| [Find-EmptyAlbumFolder.ps1](powershell/Find-EmptyAlbumFolder.ps1) | Find Album-level folders (`Artist\AlbumType\Album`) containing no audio files; optionally delete them. |
| [Find-MixedAudioDirectory.ps1](powershell/Find-MixedAudioDirectory.ps1) | Find directories containing more than one audio format (e.g. FLAC + MP3), a filesystem-side duplicate signal. |

Both are filesystem-only (no Lidarr API calls) - `lidarr_duplicate_releases.py` and `lidarr_orphaned_artists.py` are the Lidarr-database-side complements to these.

## Contributing

Contributions welcome. Keep new scripts consistent with the existing ones: `--dry-run` for anything mutating, `LIDARR_API_KEY` env var fallback, and reuse `python/lidarr_common.py` for Lidarr API calls rather than re-implementing the client.
