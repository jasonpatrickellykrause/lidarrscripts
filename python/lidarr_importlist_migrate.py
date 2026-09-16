#!/usr/bin/env python3
"""
Export and import Lidarr's configured import lists (Settings > Import Lists).

lidarr_migrator explicitly does not migrate custom import lists. This script
closes that gap: export every configured import list from one instance to a
JSON file, then recreate them on another instance.

WARNING: Lidarr's API returns import list field values, including secrets
such as Spotify client IDs/secrets or Last.fm API keys, in plain text. The
exported JSON file will contain those values - store and share it as
carefully as you would any other credential file.

Requires: requests
Install: pip install requests
"""

import argparse
import json
import os
import sys

from lidarr_common import LidarrClient


def export_import_lists(client: LidarrClient, output_file: str):
    lists = client.get_json('importlist')
    if lists is None:
        print("Error: could not fetch import lists. Check your URL and API key.", file=sys.stderr)
        sys.exit(1)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({'import_lists': lists}, f, indent=2, ensure_ascii=False)

    print(f"Exported {len(lists)} import list(s) to {output_file}")
    print("Reminder: this file contains plaintext credentials for any list that needs them "
          "(Spotify, Last.fm, etc). Handle it like a secrets file.")


def import_import_lists(client: LidarrClient, input_file: str, dry_run: bool):
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    lists = data.get('import_lists', [])
    print(f"Found {len(lists)} import list(s) to import")

    quality_profile_id = client.get_quality_profile_id()
    metadata_profile_id = client.get_metadata_profile_id()
    root_folder = client.get_root_folder()

    if not all([quality_profile_id, metadata_profile_id, root_folder]):
        print("Error: could not get target quality/metadata profile or root folder.", file=sys.stderr)
        sys.exit(1)

    added = failed = 0
    for entry in lists:
        entry = dict(entry)
        entry.pop('id', None)
        entry['qualityProfileId'] = quality_profile_id
        entry['metadataProfileId'] = metadata_profile_id
        entry['rootFolderPath'] = root_folder

        name = entry.get('name', 'Unknown list')
        if dry_run:
            print(f"  Would import: {name}")
            added += 1
            continue

        resp = client.post_json('importlist', entry)
        if resp is not None and resp.ok:
            print(f"  Imported: {name}")
            added += 1
        else:
            body = resp.text if resp is not None else 'no response'
            print(f"  Failed to import {name}: {body}", file=sys.stderr)
            failed += 1

    print("\n" + "=" * 50)
    print(f"Imported: {added}  Failed: {failed}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description='Export or import Lidarr import list configuration between instances'
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--export', metavar='OUTPUT_FILE', help='Export import lists to this JSON file')
    mode.add_argument('--import-from', dest='import_from', metavar='INPUT_FILE',
                       help='Import list JSON file to load onto this instance')
    parser.add_argument('--dry-run', action='store_true', help='With --import-from, preview without making changes')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    client = LidarrClient(args.url, args.api_key)

    if args.export:
        export_import_lists(client, args.export)
    else:
        import_import_lists(client, args.import_from, args.dry_run)


if __name__ == '__main__':
    main()
