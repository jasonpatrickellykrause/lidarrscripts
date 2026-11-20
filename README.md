# lidarrscripts

A collection of scripts for managing a [Lidarr](https://lidarr.audio/) library: bulk imports, cleanup, migration between instances, and monitoring.

## Setup

```bash
git clone https://github.com/jasonpatrickellykrause/lidarrscripts.git
cd lidarrscripts
pip install -r requirements.txt
export LIDARR_API_KEY="your-api-key"   # Settings > General > Show Advanced > API Key
cd python
python3 lidarr_health_check.py --url http://localhost:8686
```

- **API key:** every Lidarr script takes `--api-key` but falls back to the `LIDARR_API_KEY` environment variable, which keeps the key out of shell history.
- **Run from `python/`:** most scripts import the shared client in `python/lidarr_common.py`, so run them from inside `python/` (or add it to `PYTHONPATH`).
- **Help:** every script has `--help` with its full options.

## Scripts

### Adding artists and albums

| Script | Purpose | Extra deps |
|---|---|---|
| [import_nfo_albums.py](python/import_nfo_albums.py) | Add albums straight from the MusicBrainz IDs in `album.nfo` files (release group or release ID), bypassing Lidarr's text search. | - |
| [mb_lidarr_import.py](python/mb_lidarr_import.py) | Add every artist credited on a MusicBrainz release (e.g. a compilation or soundtrack). | `musicbrainzngs` |
| [artist_secondary_releases.py](python/artist_secondary_releases.py) | Add every release where an artist appears as a featured/secondary credit (not primary artist). | `musicbrainzngs` |
| [lidarr_unmapped_import.py](python/lidarr_unmapped_import.py) | Resolve Lidarr's unmapped-files list via MusicBrainz and add the matching artists. | `musicbrainzngs` |
| [lidarr_wanted_search.py](python/lidarr_wanted_search.py) | List monitored-but-missing albums; with `--search`, trigger `AlbumSearch` in throttled batches. | - |

### Library maintenance

| Script | Purpose | Extra deps |
|---|---|---|
| [lidarr_cleanup.py](python/lidarr_cleanup.py) | Remove unmonitored (and optionally empty-and-released) albums; set artist monitoring to "no new albums". | - |
| [lidarr_bulk_artist_update.py](python/lidarr_bulk_artist_update.py) | Bulk-update artists matching a filter (tag, genre, name, monitored status): reassign profiles, add/remove tags, change monitor-new-items. | - |
| [lidarr_duplicate_releases.py](python/lidarr_duplicate_releases.py) | Find albums with more downloaded track files than expected tracks (likely duplicate rips), using Lidarr's own data. | - |
| [lidarr_orphaned_artists.py](python/lidarr_orphaned_artists.py) | Find artists whose folder no longer exists on disk; optionally unmonitor them. Must run with the same filesystem view as Lidarr. | - |
| [Find-EmptyAlbumFolder.ps1](powershell/Find-EmptyAlbumFolder.ps1) | PowerShell, filesystem only: find album folders (`Artist\AlbumType\Album`) with no audio files; optionally delete them. | - |
| [Find-MixedAudioDirectory.ps1](powershell/Find-MixedAudioDirectory.ps1) | PowerShell, filesystem only: find folders mixing audio formats (e.g. FLAC + MP3), a duplicate signal. | - |

The two PowerShell scripts look at the disk only; `lidarr_duplicate_releases.py` and `lidarr_orphaned_artists.py` are their Lidarr-database-side complements.

### Monitoring

Both exit non-zero when something needs attention, so they drop straight into cron or a monitoring tool.

| Script | Purpose | Extra deps |
|---|---|---|
| [lidarr_health_check.py](python/lidarr_health_check.py) | Lidarr health, indexer connectivity and download client connectivity. Exit 1 if anything fails. | - |
| [lidarr_plugin_updates.py](python/lidarr_plugin_updates.py) | Check installed plugins for updates (same check as **System > Plugins**). Optional Discord notification (once per new version) and `--install` to install and restart. Exit 2 when updates are available. Plugins branch only. | - |

### Migrating between instances

| Script | Purpose | Extra deps |
|---|---|---|
| [lidarr_migrator/](python/lidarr_migrator/) | Export/import a whole library (artists + albums) as JSON, CSV or a plain MBID list. Self-contained (doesn't use `lidarr_common`); see its [README](python/lidarr_migrator/README.md). | - |
| [lidarr_importlist_migrate.py](python/lidarr_importlist_migrate.py) | Export/import configured import lists (not covered by `lidarr_migrator`). Exported files contain plaintext credentials - handle like a secrets file. | - |

### Other

| Script | Purpose | Extra deps |
|---|---|---|
| [spotify_playlist_checker.py](python/spotify_playlist_checker.py) | Check which streaming services (Spotify/Tidal/Deezer) each artist in a Spotify playlist has linked on MusicBrainz. Doesn't talk to Lidarr; needs `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET`. | `spotipy` |

## Safety

Scripts that change Lidarr preview first:

- **`--dry-run`:** most of them support it, showing what would change without writing anything.
- **Opt-in flags:** a few only act when you ask, with a flag such as `--search` (`lidarr_wanted_search.py`) or `--install` (`lidarr_plugin_updates.py`).
- **`--delay`:** scripts that make many API calls take it to throttle themselves.

Export files can contain API keys and indexer/import-list credentials, so `.gitignore` excludes the default export names.

## Contributing

Contributions welcome. Keep new scripts consistent with the existing ones:

- `--url` plus `--api-key` with a `LIDARR_API_KEY` fallback;
- `--dry-run` (or an explicit opt-in flag) for anything that changes Lidarr;
- reuse `python/lidarr_common.py` for Lidarr API calls rather than re-implementing the client;
- add a row to the matching table above.
