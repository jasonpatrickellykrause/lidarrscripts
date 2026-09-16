#!/usr/bin/env python3
"""
Bulk-update Lidarr artists matching a filter: reassign quality/metadata
profile, add/remove a tag, or change monitor-new-items behavior.

lidarr_cleanup.py only ever sets the metadata profile to "None" for every
artist. This script generalizes that to any profile/tag change against a
filtered subset of your library, so you don't need a new one-off script
every time you want to bulk-edit a slice of artists.

Requires: requests
Install: pip install requests
"""

import argparse
import os
import sys
import time

from lidarr_common import LidarrClient


def artist_matches(artist, args, tag_id):
    if args.tag and tag_id not in (artist.get('tags') or []):
        return False
    if args.monitored is not None and bool(artist.get('monitored')) != args.monitored:
        return False
    if args.name_contains and args.name_contains.lower() not in artist.get('artistName', '').lower():
        return False
    if args.genre and not any(args.genre.lower() in g.lower() for g in artist.get('genres', [])):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Bulk-update Lidarr artists matching a filter (profile, tags, monitoring)'
    )
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                         help='Lidarr API key (or set LIDARR_API_KEY)')

    filters = parser.add_argument_group('filters (an artist must match all given filters)')
    filters.add_argument('--tag', help='Only artists with this tag (name or numeric ID)')
    filters.add_argument('--name-contains', help='Only artists whose name contains this substring')
    filters.add_argument('--genre', help='Only artists with a genre containing this substring')
    monitor_group = filters.add_mutually_exclusive_group()
    monitor_group.add_argument('--only-monitored', dest='monitored', action='store_true', default=None,
                                help='Only monitored artists')
    monitor_group.add_argument('--only-unmonitored', dest='monitored', action='store_false',
                                help='Only unmonitored artists')

    actions = parser.add_argument_group('actions (at least one is required)')
    actions.add_argument('--set-metadata-profile', help='Metadata profile name to apply')
    actions.add_argument('--set-quality-profile', help='Quality profile name to apply')
    actions.add_argument('--set-monitor-new-items', choices=['all', 'none', 'new'],
                          help="Set the artist's monitorNewItems behavior")
    actions.add_argument('--add-tag', help='Tag (name or numeric ID) to add to matching artists')
    actions.add_argument('--remove-tag', help='Tag (name or numeric ID) to remove from matching artists')

    parser.add_argument('--dry-run', action='store_true', help='Preview changes without making them')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between updates in seconds (default: 0.5)')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    if not any([args.set_metadata_profile, args.set_quality_profile, args.set_monitor_new_items,
                args.add_tag, args.remove_tag]):
        parser.error("At least one action is required (--set-metadata-profile, --set-quality-profile, "
                      "--set-monitor-new-items, --add-tag, or --remove-tag)")

    client = LidarrClient(args.url, args.api_key)

    metadata_profile_id = None
    if args.set_metadata_profile:
        metadata_profile_id = client.get_metadata_profile_id(name=args.set_metadata_profile)
        if metadata_profile_id is None:
            print(f"Error: metadata profile '{args.set_metadata_profile}' not found", file=sys.stderr)
            sys.exit(1)

    quality_profile_id = None
    if args.set_quality_profile:
        for p in client.get_quality_profiles():
            if p.get('name') == args.set_quality_profile:
                quality_profile_id = p['id']
                break
        if quality_profile_id is None:
            print(f"Error: quality profile '{args.set_quality_profile}' not found", file=sys.stderr)
            sys.exit(1)

    add_tag_id = client.resolve_tag_id(args.add_tag) if args.add_tag else None
    if args.add_tag and add_tag_id is None:
        print(f"Error: tag '{args.add_tag}' not found", file=sys.stderr)
        sys.exit(1)

    remove_tag_id = client.resolve_tag_id(args.remove_tag) if args.remove_tag else None
    if args.remove_tag and remove_tag_id is None:
        print(f"Error: tag '{args.remove_tag}' not found", file=sys.stderr)
        sys.exit(1)

    filter_tag_id = client.resolve_tag_id(args.tag) if args.tag else None
    if args.tag and filter_tag_id is None:
        print(f"Error: filter tag '{args.tag}' not found", file=sys.stderr)
        sys.exit(1)

    print("Fetching artists...")
    artists = client.get_artists()
    matching = [a for a in artists if artist_matches(a, args, filter_tag_id)]

    print(f"{len(matching)}/{len(artists)} artist(s) match the filter\n")
    if not matching:
        return

    if args.dry_run:
        print("=" * 50)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 50)

    updated = failed = 0
    for artist in matching:
        name = artist.get('artistName', 'Unknown')
        print(f"{name}")

        payload = dict(artist)
        if metadata_profile_id is not None:
            payload['metadataProfileId'] = metadata_profile_id
        if quality_profile_id is not None:
            payload['qualityProfileId'] = quality_profile_id
        if args.set_monitor_new_items:
            payload['monitorNewItems'] = args.set_monitor_new_items
        tags = set(payload.get('tags') or [])
        if add_tag_id is not None:
            tags.add(add_tag_id)
        if remove_tag_id is not None:
            tags.discard(remove_tag_id)
        payload['tags'] = sorted(tags)

        if args.dry_run:
            print(f"  Would update")
            updated += 1
            continue

        if client.update_artist(payload):
            print(f"  Updated")
            updated += 1
        else:
            print(f"  Failed to update")
            failed += 1
        time.sleep(args.delay)

    print("\n" + "=" * 50)
    print(f"Updated: {updated}  Failed: {failed}")
    print("=" * 50)


if __name__ == '__main__':
    main()
