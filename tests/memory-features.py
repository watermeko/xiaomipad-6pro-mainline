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
                  '/usr/local/sbin/liuqin-root-trim': None,
                  # The applier that both the installer and the incremental
                  # package use.  Its absence is what makes a hand-trimmed
                  # system differ from a built one.
                  '/usr/lib/liuqin/apply-root-tweaks.sh': None},
        'absent': ['/snap', '/var/lib/snapd', '/usr/lib/snapd/snap-confine'],
        'packages_absent': ['snapd', 'firefox', 'thunderbird', 'unattended-upgrades',
                            'update-notifier', 'fwupd', 'cups', 'cups-browsed',
                            'modemmanager', 'rsyslog', 'networkd-dispatcher',
                            'switcheroo-control', 'evolution-data-server',
                            'gnome-calendar',
                            # The GNOME/Phosh session this product replaced.
                            'gdm3', 'gnome-shell', 'ubuntu-session',
                            'gnome-session-bin', 'gnome-settings-daemon',
                            'gnome-initial-setup', 'gnome-control-center',
                            'gnome-snapshot', 'nautilus', 'localsearch',
                            'xdg-desktop-portal-gnome', 'ibus',
                            'phosh', 'phoc', 'squeekboard', 'phosh-osk-stevia',
                            'xdg-desktop-portal-phosh'],
        'packages_present': ['sddm', 'plasma-mobile', 'plasma-workspace',
                             'kwin-wayland', 'powerdevil', 'dolphin',
                             'plasma-camera', 'fcitx5',
                             'pipewire', 'wireplumber', 'fprintd',
                             'iio-sensor-proxy', 'libqmi-glib5', 'libqrtr-glib0'],
    },
    'fingerprint': {
        'why': 'the FPC1264 module only loads after its ten trusted-application '
               'files are cached from modem_a, and a stock ROM re-signed between '
               'releases is what made the shipped hash list refuse this unit',
        # The cache holds one ROM's ten files.  The names are checked here and
        # the identity is checked by the runtime itself; what this gate proves
        # is that provisioning ran at all, which is what silently stopped.
        'paths': {('/usr/local/lib/liuqin-fpc-oem/firmware/' + name): None
                  for name in ('fpcliu.mdt', *(f'fpcliu.b{i:02d}' for i in range(9)))},
        'content': {'/usr/local/lib/liuqin-fpc-oem/firmware/SHA256.json': '"schema": 2'},
        'packages_present': ['fprintd'],
    },
    'volume-hiding': {
        'why': 'the stock layout leaves twelve filesystem-bearing Android '
               'partitions on the internal UFS, so udisks2 offered each of them '
               'as a mountable volume and the dock and Files filled up with '
               'anonymous "31 MB Volume" entries',
        'paths': {'/etc/udev/rules.d/90-liuqin-hide-android-volumes.rules': None},
        'content': {'/etc/udev/rules.d/90-liuqin-hide-android-volumes.rules':
                    'ENV{UDISKS_IGNORE}="1"'},
        # Live-system only: a rule file proves intent, the udev database proves
        # it took effect.  linux_root and linux_home must NOT be ignored, which
        # is what keeps the system's own partitions visible.
        'udev_ignored': ['persist', 'metadata', 'persistbak', 'dsp_a', 'dsp_b',
                         'vm-bootsys_a', 'vm-bootsys_b', 'logfs', 'cust', 'qmcs',
                         'modem_a', 'modem_b', 'bluetooth_a', 'bluetooth_b'],
        'udev_visible': ['linux_root', 'linux_home'],
    },
    'session-defaults': {
        'why': 'the login manager and the Plasma session defaults are what make '
               'a fresh install boot into Plasma Mobile with the idle, lock and '
               'power-button policy this product measured; they are files, not '
               'package defaults, so nothing else proves they landed',
        'paths': {'/etc/sddm.conf.d/10-liuqin.conf': None,
                  '/etc/xdg/kwinrc': None,
                  '/etc/xdg/kscreenlockerrc': None,
                  '/etc/xdg/powerdevilrc': None,
                  '/usr/local/bin/liuqin-power-policy': None,
                  '/usr/local/sbin/liuqin-storage-guard': None,
                  '/usr/local/sbin/liuqin-usb-rescue': None,
                  '/etc/systemd/system/display-manager.service':
                      '/lib/systemd/system/sddm.service'},
        'content': {'/etc/xdg/powerdevilrc': 'PowerButtonAction=0',
                    '/etc/xdg/kscreenlockerrc': 'Autolock=true',
                    '/etc/xdg/kwinrc': 'InputMethod=',
                    '/etc/sddm.conf.d/10-liuqin.conf': 'DisplayServer=wayland'},
        'packages_present': ['sddm'],
    },
    'unit-masks': {
        'why': 'the update notifiers belong to packages the trim removes, but '
               'an installed tablet can still have them for the length of one '
               'boot, and a masked timer cannot fire in that window',
        # Conditional by design: a mask is only required while the unit is still
        # shipped in /usr/lib.  Masking a unit whose package was purged proves
        # nothing, and asserting it would make the gate fail on a correct system.
        'masked': ['system/apt-daily.timer', 'system/apt-daily-upgrade.timer',
                   'system/unattended-upgrades.service',
                   'system/update-notifier-download.timer'],
    },
    'session-trim': {
        'why': 'the Plasma migration replaced the GNOME session and dropped the '
               'per-account trim that went with it, so the image ran X11 tray '
               'proxies, the activity database, four gvfs backends it cannot '
               'host, two ssh agents, a SPICE guest agent and the wallet unlock '
               'again: 265 MB of resident memory measured on the 8 GiB unit',
        # The list carries the entries, and a live system must show them applied.
        # The list half runs everywhere because a built image cannot have an
        # account yet (the installer passes --no-user) while the tablet does.
        'paths': {'/usr/share/liuqin/root-trim.txt': None},
        'trim_units': ['plasma-xembedsniproxy.service',
                       'plasma-gmenudbusmenuproxy.service',
                       'gvfs-afc-volume-monitor.service',
                       'gvfs-gphoto2-volume-monitor.service',
                       'gvfs-goa-volume-monitor.service',
                       'gvfs-mtp-volume-monitor.service',
                       'obex.service', 'ssh-agent.service', 'ssh-agent.socket',
                       'spice-vdagent.service', 'plasma-kwallet-pam.service',
                       'ubuntu-insights-collect.timer',
                       'ubuntu-insights-upload.timer'],
        # kactivitymanagerd is absent on purpose: masking it stops plasmashell
        # from loading the shell at all, see the trim list.
        'trim_unit_absent': ['plasma-kactivitymanagerd.service'],
        'trim_autostarts': ['xembedsniproxy.desktop', 'gmenudbusmenuproxy.desktop',
                            'geoclue-demo-agent.desktop', 'pam_kwallet_init.desktop',
                            'spice-vdagent.desktop',
                            'ubuntu-report-on-upgrade.desktop'],
    },
    'hugepage-policy': {
        'why': 'the pinned kernel is built CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS=y, '
               'which rounds every anonymous allocation up to 2 MiB on a device '
               'that has 6.3 GiB of MemTotal; 1360 MB of the measured session was '
               'huge-page backed, and madvise keeps the feature while removing '
               'the padding',
        'paths': {'/etc/tmpfiles.d/90-liuqin-thp.conf': None},
        'content': {'/etc/tmpfiles.d/90-liuqin-thp.conf':
                    'w /sys/kernel/mm/transparent_hugepage/enabled - - - - madvise',
                    # Live-system half: the sysfs file reports the active policy
                    # in brackets, so this needle only matches when madvise is
                    # the one in effect.  On an extracted tree /sys is empty and
                    # the check is skipped.
                    '/sys/kernel/mm/transparent_hugepage/enabled': 'madvise]'},
    },
    'kded-modules': {
        'why': 'kded6 loads ~18 modules at login and most of them serve hardware '
               'or behaviour this image does not have (an APN autodetect for a '
               'modem the trim list removes, a donation nag, a look-and-feel '
               'switcher that reacts to distro upgrades).  This is not a memory '
               'win -- the daemon is mostly the Qt/KIO libraries it shares -- but '
               'it is the difference between a daemon that does nothing and one '
               'that keeps trying',
        'paths': {'/etc/xdg/kdedrc': None},
        'content': {'/etc/xdg/kdedrc':
                    '[Module-kded_plasma_mobile_autodetect_apn]\nautoload=false'},
    },
    'idle-reclaim': {
        'why': 'an idle session hands nothing back to the kernel: zram held zero '
               'stored bytes for an entire boot, because handing pages to swap is '
               'a reaction to memory pressure and an idle tablet has none.  One '
               'cgroup write moved 548 MB of cold session pages into 47 MB of '
               'zram and the pages that are touched come back on demand',
        'paths': {'/usr/local/libexec/liuqin-memory-reclaim': None,
                  '/etc/systemd/system/liuqin-memory-reclaim.service': None,
                  '/etc/systemd/system/liuqin-memory-reclaim.timer': None,
                  # A timer that is merely installed never runs: the wants link
                  # is what schedules it, and the native-root build creates it.
                  '/etc/systemd/system/timers.target.wants/liuqin-memory-reclaim.timer':
                      None},
        'content': {'/etc/systemd/system/liuqin-memory-reclaim.timer': 'OnBootSec=180s',
                    '/usr/local/libexec/liuqin-memory-reclaim': 'memory.reclaim',
                    '/etc/systemd/system/liuqin-memory-reclaim.service':
                    'ExecStart=/usr/local/libexec/liuqin-memory-reclaim'},
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


def probe(path):
    """Existence of a path, telling "missing" apart from "cannot look".

    The fingerprint cache is root-only (0600 files inside a 0700 directory), so
    running this gate as an ordinary account made every file look absent and
    turned a permission problem into a fake regression.  Say which one it is.
    """
    try:
        os.stat(path)
        return 'present'
    except PermissionError:
        return 'denied'
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'missing'


def accounts():
    """Every human account on this machine, by uid range.

    apply-root-tweaks.sh applies [mask-user] per account and is told the name;
    this is the same set.  /home also holds directories that are not accounts
    (lost+found on an ext4 home), and those must not read as a failure.
    """
    homes = []
    try:
        entries = Path('/etc/passwd').read_text().splitlines()
    except OSError:
        return homes
    for line in entries:
        fields = line.split(':')
        if len(fields) < 6:
            continue
        try:
            uid = int(fields[2])
        except ValueError:
            continue
        home = Path(fields[5])
        if 1000 <= uid < 60000 and home.is_dir():
            homes.append(home)
    return homes


def udev_properties(label):
    """Read one partition's udev database entry, or None if it does not exist."""
    node = Path('/dev/disk/by-partlabel') / label
    if not os.path.lexists(node):
        return None
    try:
        out = subprocess.run(['udevadm', 'info', '--query=property', '--name',
                              str(node)], capture_output=True, text=True).stdout
    except OSError:
        return None
    properties = {}
    for line in out.splitlines():
        key, _, value = line.partition('=')
        properties[key] = value
    return properties or None


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
            state = probe(path)
            if state == 'denied':
                failures.append('%s cannot be inspected without root' % rel)
                continue
            if state == 'missing':
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
        # The per-account half of the trim: the list is checked everywhere, the
        # accounts only on the machine itself, because a built image has none.
        trim = tree / 'usr/share/liuqin/root-trim.txt'
        live = os.path.realpath(tree) == '/'
        homes = accounts() if live else []
        if spec.get('trim_units') or spec.get('trim_autostarts'):
            listing = trim.read_text(errors='replace') if trim.is_file() else ''
            for unit in spec.get('trim_units', []):
                if ('unit:' + unit) not in listing:
                    failures.append('the trim list does not mask %s' % unit)
                for home in homes:
                    mask = home / '.config/systemd/user' / unit
                    if mask.is_symlink() and os.readlink(mask) == '/dev/null':
                        continue
                    failures.append('%s is not masked for %s' % (unit, home.name))
            for entry in spec.get('trim_autostarts', []):
                if ('autostart:' + entry) not in listing:
                    failures.append('the trim list does not hide %s' % entry)
                for home in homes:
                    hidden = home / '.config/autostart' / entry
                    if hidden.is_file() and 'Hidden=true' in hidden.read_text(errors='replace'):
                        continue
                    failures.append('%s is still an autostart entry for %s'
                                    % (entry, home.name))
            # The other direction: a unit that must NOT be masked, because
            # masking it breaks the session (kactivitymanagerd).
            for unit in spec.get('trim_unit_absent', []):
                if ('unit:' + unit) in listing:
                    failures.append('the trim list masks %s, which the session needs' % unit)
                for home in homes:
                    mask = home / '.config/systemd/user' / unit
                    if mask.is_symlink() and os.readlink(mask) == '/dev/null':
                        failures.append('%s is masked for %s and the shell will not load'
                                        % (unit, home.name))
        # /dev/disk/by-partlabel describes the machine this runs on, so the
        # udev side is only meaningful when the root tree is that machine.
        # An extracted image tree has no devices to inspect.
        if os.path.realpath(tree) == '/':
            for label in spec.get('udev_ignored', []):
                properties = udev_properties(label)
                if properties is None:
                    failures.append('partition %s is absent, so hiding it proves '
                                    'nothing' % label)
                elif properties.get('UDISKS_IGNORE') != '1':
                    failures.append('%s is still offered to udisks2' % label)
            for label in spec.get('udev_visible', []):
                properties = udev_properties(label)
                if properties is None:
                    failures.append('partition %s is absent' % label)
                elif properties.get('UDISKS_IGNORE') == '1':
                    failures.append('%s was hidden but is the system itself' % label)
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
