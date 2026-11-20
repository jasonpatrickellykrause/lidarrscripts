#!/usr/bin/env python3
"""
Check a Lidarr instance for plugin updates, and optionally install them.

Lidarr (plugins branch) compares every installed plugin against its GitHub
releases whenever /api/v1/system/plugins is read, so this script only reports
what Lidarr itself sees in System > Plugins. By default it is check-only:
nothing is installed and Lidarr is not restarted.

  - Check and print:            lidarr_plugin_updates.py --url http://localhost:8686
  - Also post to Discord:       ... --discord-webhook https://discord.com/api/webhooks/...
  - Install updates + restart:  ... --install            (preview with --install --dry-run)

With --state-file, each new version is announced only once, so a daily cron
job doesn't repeat the same notification until you install it.

Example cron entry (daily at 07:15, check-only, Discord notification):

  15 7 * * * cd /path/to/lidarrscripts/python && LIDARR_API_KEY=... \\
      python3 lidarr_plugin_updates.py --url http://localhost:8686 \\
      --discord-webhook "$WEBHOOK" --state-file ~/.lidarr_plugin_updates.state

Daily is plenty: each check makes one unauthenticated GitHub API request per
plugin (GitHub allows 60/hour per IP), and plugins rarely release more often.

Exit codes: 0 = no updates (or all installed), 2 = updates available
(check-only), 1 = error (Lidarr unreachable, failed install).

Requires: requests
Install: pip install requests
"""

import argparse
import os
import sys
import time

import requests

from lidarr_common import LidarrClient

UNAVAILABLE_PREFIX = '0.0.0.0'  # Lidarr reports this when it can't find a compatible release


def notify_discord(webhook: str, message: str) -> None:
    try:
        resp = requests.post(webhook, json={'username': 'Lidarr plugin updates', 'content': message[:2000]},
                             timeout=15)
        if not resp.ok:
            print(f"Warning: Discord webhook returned HTTP {resp.status_code}", file=sys.stderr)
    except requests.exceptions.RequestException as e:
        print(f"Warning: Discord webhook failed: {e}", file=sys.stderr)


def load_state(path: str) -> set:
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}


def save_state(path: str, seen: set) -> None:
    if not path:
        return
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(seen)) + '\n')


def install_plugin(client: LidarrClient, github_url: str, timeout: int) -> str:
    """Queue Lidarr's InstallPlugin command and wait for it. Returns the final command status."""
    resp = client.post_json('command', {'name': 'InstallPlugin', 'githubUrl': github_url})
    if resp is None or not resp.ok:
        return 'failed to queue'
    command_id = resp.json().get('id')
    deadline = time.time() + timeout
    status = 'unknown'
    while time.time() < deadline:
        command = client.get_json(f'command/{command_id}') or {}
        status = command.get('status', 'unknown')
        if status in ('completed', 'failed', 'aborted', 'cancelled'):
            break
        time.sleep(5)
    return status


def main():
    parser = argparse.ArgumentParser(description='Check a Lidarr instance for plugin updates (and optionally install them)')
    parser.add_argument('--url', required=True, help='Lidarr URL (e.g., http://localhost:8686)')
    parser.add_argument('--api-key', default=os.environ.get('LIDARR_API_KEY'),
                        help='Lidarr API key (or set LIDARR_API_KEY)')
    parser.add_argument('--install', action='store_true',
                        help='Install available updates and restart Lidarr (default: check only)')
    parser.add_argument('--dry-run', action='store_true', help='With --install: show what would be installed')
    parser.add_argument('--skip-owner', action='append', default=[], metavar='OWNER',
                        help='Never install plugins from this GitHub owner (still reported). Repeatable.')
    parser.add_argument('--no-restart', action='store_true',
                        help='With --install: do not restart Lidarr afterwards (updates load on next restart)')
    parser.add_argument('--discord-webhook', default=os.environ.get('LIDARR_PLUGIN_WEBHOOK'),
                        help='Discord webhook URL for notifications (or set LIDARR_PLUGIN_WEBHOOK)')
    parser.add_argument('--state-file', help='Remember announced versions here so each is notified only once')
    parser.add_argument('--install-timeout', type=int, default=300, help='Seconds to wait per install (default 300)')

    args = parser.parse_args()

    if not args.api_key:
        parser.error("--api-key is required (or set the LIDARR_API_KEY environment variable)")

    client = LidarrClient(args.url, args.api_key)
    plugins = client.get_json('system/plugins')
    if plugins is None:
        msg = f"Lidarr plugin update check failed: could not read {args.url}/api/v1/system/plugins"
        print(f"FAIL: {msg}")
        if args.discord_webhook:
            notify_discord(args.discord_webhook, f"⚠️ {msg}")
        sys.exit(1)

    if not plugins:
        print("No plugins installed.")
        sys.exit(0)

    skip = {o.lower() for o in args.skip_owner}
    seen = load_state(args.state_file)
    available, to_announce, results = [], [], []

    for p in plugins:
        label = f"{p.get('owner')}/{p.get('name')}"
        installed, latest = p.get('installedVersion'), p.get('availableVersion') or ''
        if latest.startswith(UNAVAILABLE_PREFIX):
            print(f"  ?       {label} {installed}: no compatible release found (GitHub unreachable or none for this Lidarr)")
            continue
        if not p.get('updateAvailable'):
            print(f"  ok      {label} {installed}")
            continue
        print(f"  UPDATE  {label} {installed} -> {latest}")
        available.append(p)
        key = f"{label} {latest}"
        if key not in seen:
            to_announce.append(f"• {label} {installed} → {latest}  <{p.get('githubUrl')}/releases>")
            seen.add(key)

    if not available:
        print("\nAll plugins are up to date.")
        save_state(args.state_file, seen)
        sys.exit(0)

    if not args.install:
        if to_announce and args.discord_webhook:
            notify_discord(args.discord_webhook,
                           "📦 Lidarr plugin update available (System → Plugins to install):\n" + "\n".join(to_announce))
        save_state(args.state_file, seen)
        print(f"\n{len(available)} update(s) available. Re-run with --install to install them.")
        sys.exit(2)

    installed_any, failed = False, False
    for p in available:
        label = f"{p.get('owner')}/{p.get('name')}"
        if (p.get('owner') or '').lower() in skip:
            print(f"  skip    {label} (--skip-owner)")
            results.append(f"• {label} → {p.get('availableVersion')} (skipped, install manually)")
            continue
        if args.dry_run:
            print(f"  [dry run] would install {label} {p.get('availableVersion')}")
            continue
        status = install_plugin(client, p.get('githubUrl'), args.install_timeout)
        print(f"  install {label} {p.get('availableVersion')}: {status}")
        results.append(f"• {label} {p.get('installedVersion')} → {p.get('availableVersion')} ({status})")
        installed_any = installed_any or status == 'completed'
        failed = failed or status != 'completed'

    if args.dry_run:
        print("\nDry run: nothing installed, Lidarr not restarted.")
        sys.exit(0)

    restart = installed_any and not args.no_restart
    if restart:
        print("\nRestarting Lidarr so the new plugin versions load...")
        resp = client.post_json('system/restart', {})
        if resp is None or not resp.ok:
            print("Warning: restart request failed; restart Lidarr manually.", file=sys.stderr)
    elif installed_any:
        print("\nInstalled. Restart Lidarr for the new versions to load.")

    if results and args.discord_webhook:
        header = "🔄 Lidarr plugins updated" + (", Lidarr restarting:" if restart else ":")
        notify_discord(args.discord_webhook, header + "\n" + "\n".join(results))
    save_state(args.state_file, seen)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
