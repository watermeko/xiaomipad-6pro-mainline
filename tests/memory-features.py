#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assert that one of this repository's customisations is really installed.

A feature is only "shipped" if a built image can prove it, so every entry in
FEATURES below is a check rather than a sentence.  Three surfaces are inspected
because the customisations are split across them:

  kernel   the generated .config, from a kernel build directory
  rootfs   a filesystem tree: the assembled root, or the tablet itself
  package  dpkg state inside that tree (only possible on a live system)

    # what the image builder is about to pack
    python3 tests/memory-features.py --config out/kernel/.config \\
        --root out/root/rootfs --packages

    # an installed tablet: copy this file over and run it there, because the
    # checks read the live tree and the live dpkg database
    adb -s liuqin push tests/memory-features.py /tmp/
    adb -s liuqin shell 'python3 /tmp/memory-features.py \
        --config /proc/config.gz --root / --packages'

Exits non-zero and names the failing feature, so it can be a release gate.
"""

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

# Each feature: the reason it exists, and the checks that prove it.
#   config: kernel symbol -> expected value ('' means "not set")
#   paths:  path in the root tree -> expected symlink target (None for any file)
#   packages_present / packages_absent: dpkg selections (live system only)
#   content: path -> substring that must appear in the file
FEATURES = {
    'zram-swap': {
        'why': 'no swap partition exists on this layout and systemd-oomd could '
               'only kill; zram is the reclaim target',
        'config': {'CONFIG_ZRAM': 'y', 'CONFIG_ZSMALLOC': 'y',
                   'CONFIG_ZRAM_BACKEND_ZSTD': 'y', 'CONFIG_ZRAM_DEF_COMP_ZSTD': 'y',
                   'CONFIG_ZSWAP': ''},
        'paths': {'/etc/systemd/zram-generator.conf': None},
        'content': {'/etc/systemd/zram-generator.conf': 'compression-algorithm = zstd'},
        'packages_present': ['systemd-zram-generator'],
    },
    'rootfs-trim': {
        'why': 'snap, the update notifiers, fwupd, printing and the Evolution '
               'daemons were 580 MB of the idle baseline',
        'paths': {'/usr/share/liuqin/root-trim.txt': None,
                  '/usr/local/sbin/liuqin-root-trim': None},
        'absent': ['/snap', '/var/lib/snapd', '/usr/lib/snapd/snap-confine'],
        'packages_absent': ['snapd', 'firefox', 'thunderbird', 'unattended-upgrades',
                            'update-notifier', 'fwupd', 'cups', 'cups-browsed',
                            'modemmanager', 'rsyslog', 'networkd-dispatcher',
                            'switcheroo-control', 'evolution-data-server',
                            'gnome-calendar'],
        'packages_present': ['gdm3', 'gnome-shell', 'nautilus', 'localsearch',
                             'pipewire', 'wireplumber', 'fprintd',
                             'iio-sensor-proxy', 'libqmi-glib5', 'libqrtr-glib0'],
    },
    'unit-masks': {
        'why': 'colord cannot be purged (it takes gnome-control-center with it) '
               'and localsearch is a Depends of nautilus, so their daemons are '
               'masked instead; the update notifiers get the same treatment for '
               'the window before the trim removes their packages',
        # Conditional by design: a mask is only required while the unit is still
        # shipped in /usr/lib.  Masking a unit whose package was purged proves
        # nothing, and asserting it would make the gate fail on a correct system.
        'masked': ['system/colord.service', 'user/localsearch-3.service',
                   'system/apt-daily.timer', 'system/apt-daily-upgrade.timer',
                   'system/unattended-upgrades.service',
                   'system/update-notifier-download.timer'],
    },
}


def read_dpkg_field(root, package, field):
    """Read one dpkg field for a package from a root tree's status database."""
    status = Path(root) / 'var/lib/dpkg/status'
    if not status.is_file():
        return None
    want, seen = field.lower(), None
    for line in status.read_text(errors='replace').splitlines():
        if line.startswith('Package: '):
            seen = line[9:].strip()
        elif line.startswith(('Description', ' ')):
            continue
        elif line.lower().startswith(want + ':'):
            if seen == package:
                return line.split(':', 1)[1].strip()
    return None


def package_installed(root, package):
    """installed = the selection dpkg has, based on the Package/Status pair."""
    status = Path(root) / 'var/lib/dpkg/status'
    if not status.is_file():
        return None
    current, answer = None, False
    for line in status.read_text(errors='replace').splitlines():
        if line.startswith('Package: '):
            current = line[9:].strip()
        elif line.startswith('Status: ') and current == package:
            answer = line[8:].strip().endswith(' installed')
    return answer


def read_section(text, want):
    """Package names of one trim-list section, headers anchored to their own line.

    The list's own comments mention `[keep]` and `[purge]` in prose, so a
    substring search would read the wrong text; the shell readers in
    build-liuqin-native-root.sh use the same anchored rule.
    """
    names, inside = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('['):
            inside = stripped == want
            continue
        if inside and stripped and not stripped.startswith('#'):
            names.append(stripped.split()[0])
    return names


def parse_config(path):
    path = Path(path)
    if path.suffix == '.gz' or path.name.endswith('config.gz'):
        text = gzip.decompress(path.read_bytes()).decode()
    else:
        text = path.read_text()
    symbols = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('# CONFIG_') and line.endswith(' is not set'):
            symbols[line[2:].split(' is not set')[0]] = ''
        elif line.startswith('CONFIG_') and '=' in line:
            key, _, value = line.partition('=')
            symbols[key] = value.strip('"')
    return symbols


def check(feature, spec, config, root, use_packages):
    failures = []
    if config is not None:
        for symbol, want in spec.get('config', {}).items():
            got = config.get(symbol)
            if got is None:
                failures.append('%s is absent from the kernel configuration' % symbol)
            elif got != want:
                failures.append('%s is %r, expected %r' % (symbol, got, want))
    elif spec.get('config'):
        failures.append('no --config given, so the kernel side is unproven')

    if root is not None:
        tree = Path(root)
        for rel, target in spec.get('paths', {}).items():
            path = tree / rel.lstrip('/')
            if not os.path.lexists(path):
                failures.append('%s is missing' % rel)
                continue
            if target is not None:
                if not path.is_symlink():
                    failures.append('%s is not a symlink (expected -> %s)' % (rel, target))
                elif os.readlink(path) != target:
                    failures.append('%s -> %s, expected -> %s'
                                    % (rel, os.readlink(path), target))
        for rel in spec.get('absent', []):
            if os.path.lexists(tree / rel.lstrip('/')):
                failures.append('%s survived and should not be present' % rel)
        for unit in spec.get('masked', []):
            shipped = tree / 'usr/lib/systemd' / unit
            if not os.path.lexists(shipped):
                continue  # the package that carried it is gone; nothing to mask
            link = tree / 'etc/systemd' / unit
            if not os.path.lexists(link):
                failures.append('/etc/systemd/%s is not masked although /usr/lib '
                                'still ships it' % unit)
            elif not link.is_symlink() or os.readlink(link) != '/dev/null':
                failures.append('/etc/systemd/%s does not point at /dev/null' % unit)
        for rel, needle in spec.get('content', {}).items():
            path = tree / rel.lstrip('/')
            if path.is_file() and needle not in path.read_text(errors='replace'):
                failures.append('%s does not contain %r' % (rel, needle))
        if use_packages:
            for package in spec.get('packages_present', []):
                got = package_installed(tree, package)
                if got is None:
                    failures.append('cannot read the dpkg database under %s' % tree)
                    break
                if not got:
                    failures.append('%s is not installed' % package)
            for package in spec.get('packages_absent', []):
                if package_installed(tree, package):
                    failures.append('%s is still installed' % package)

    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, help='kernel .config of the build')
    parser.add_argument('--root', type=Path,
                        help='root filesystem tree (assembled root, or / on the tablet)')
    parser.add_argument('--packages', action='store_true',
                        help='also assert the dpkg selections (needs the real database)')
    parser.add_argument('--feature', action='append', choices=sorted(FEATURES),
                        help='check only this feature (repeatable)')
    parser.add_argument('--list', action='store_true', help='print the feature set')
    parser.add_argument('--json', action='store_true', help='machine-readable result')
    args = parser.parse_args()

    if args.list:
        for name, spec in sorted(FEATURES.items()):
            print('%s: %s' % (name, spec['why']))
        return

    if not args.config and not args.root:
        parser.error('give at least one of --config or --root')

    config = parse_config(args.config) if args.config else None
    root = args.root

    selected = args.feature or sorted(FEATURES)
    result, failed = {}, 0
    for name in selected:
        failures = check(name, FEATURES[name], config, root, args.packages)
        result[name] = {'ok': not failures, 'failures': failures}
        if failures:
            failed += 1
        if not args.json:
            print('%s %s' % ('PASS' if not failures else 'FAIL', name))
            for failure in failures:
                print('     ' + failure)
    if args.json:
        print(json.dumps(result, indent=2))
    if failed:
        print('%d of %d features are not proven present' % (failed, len(selected)),
              file=sys.stderr)
        raise SystemExit(1)
    print('all %d features are present' % len(selected))


if __name__ == '__main__':
    main()
