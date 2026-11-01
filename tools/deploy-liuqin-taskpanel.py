#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 watermeko
# SPDX-License-Identifier: MIT
"""Build and install the patched Plasma Mobile task panel.

The tablet has no tray of its own (KDE bug 483089), so the task panel in
plasma-mobile carries a small StatusNotifierItem host: its icons are drawn to
the left of the task switcher, home and close buttons.  The patch lives in a
plasma-mobile fork (see plasma-mobile/source.json); this script builds that one
containment on the tablet and installs it.

Run it on the tablet, as the desktop user:

    python3 tools/deploy-liuqin-taskpanel.py
    python3 tools/deploy-liuqin-taskpanel.py --uninstall

The build needs build-essential, cmake, extra-cmake-modules, qt6-base-dev,
qt6-declarative-dev, qt6-sensors-dev, libplasma-dev, libkf6config-dev,
libkf6coreaddons-dev and libkf6windowsystem-dev.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path('/usr/lib/aarch64-linux-gnu/qt6/plugins/plasma/applets')
PLUGIN = PLUGIN_DIR / 'org.kde.plasma.mobile.taskpanel.so'
PACKAGE_DIR = Path('/usr/share/plasma/plasmoids/org.kde.plasma.mobile.taskpanel')
BACKUP_DIR = Path('/usr/local/share/liuqin/taskpanel')
SERVICE = 'plasma-plasmashell.service'


def run(command, **kwargs):
    print('+', ' '.join(str(part) for part in command))
    subprocess.run(command, check=True, **kwargs)


def sudo(*command):
    run(['sudo', '-n', *command])


def build(source, build_dir):
    build_dir.mkdir(parents=True, exist_ok=True)
    tools = Path(__file__).resolve().parent
    run(['cmake', '-S', str(tools / 'plasma-mobile'), '-B', str(build_dir),
         f'-DPLASMA_MOBILE_SOURCE={source}', '-DCMAKE_BUILD_TYPE=None'])
    run(['cmake', '--build', str(build_dir), '-j', str(len(list(Path('/sys/devices/system/cpu').glob('cpu[0-9]*'))))])
    plugin = build_dir / 'plasma/applets/org.kde.plasma.mobile.taskpanel.so'
    if not plugin.exists():
        sys.exit(f'the build did not produce {plugin}')
    return plugin


def restart_shell():
    run(['systemctl', '--user', 'restart', SERVICE])


def install(source, build_dir):
    # Keep the packaged plugin once, so --uninstall has something to restore.
    if not PLUGIN.exists():
        sys.exit(f'{PLUGIN} is missing: is plasma-mobile installed?')
    if not (BACKUP_DIR / PLUGIN.name).exists():
        sudo('mkdir', '-p', str(BACKUP_DIR))
        sudo('cp', '-a', str(PLUGIN), str(BACKUP_DIR / PLUGIN.name))
        print(f'kept the packaged plugin in {BACKUP_DIR}')

    plugin = build(source, build_dir)
    sudo('install', '-m', '0644', str(plugin), str(PLUGIN))

    # The applet's QML is installed as a package: Plasma looks for
    # Plasma/Applet packages first and falls back to the compiled-in one, and
    # the compiled-in copy cannot be replaced without rebuilding the whole
    # project (see tools/plasma-mobile/CMakeLists.txt).  Plasma needs the
    # package structure and a plugin id in the metadata to accept it.
    taskpanel = source / 'containments/taskpanel'
    metadata = json.loads((taskpanel / 'metadata.json').read_text())
    metadata['KPackageStructure'] = 'Plasma/Applet'
    metadata['KPlugin']['Id'] = 'org.kde.plasma.mobile.taskpanel'

    sudo('mkdir', '-p', str(PACKAGE_DIR / 'contents/ui'))
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
        json.dump(metadata, handle, indent=4, ensure_ascii=False)
        metadata_path = handle.name
    sudo('install', '-m', '0644', metadata_path, str(PACKAGE_DIR / 'metadata.json'))
    Path(metadata_path).unlink()
    for qml in sorted((taskpanel / 'qml').glob('*.qml')):
        sudo('install', '-m', '0644', str(qml), str(PACKAGE_DIR / 'contents/ui' / qml.name))

    restart_shell()


def uninstall():
    backup = BACKUP_DIR / PLUGIN.name
    if backup.exists():
        sudo('install', '-m', '0644', str(backup), str(PLUGIN))
        print(f'restored {backup}')
    sudo('rm', '-rf', str(PACKAGE_DIR))
    restart_shell()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', type=Path, default=Path.home() / 'plasma-mobile',
                        help='the plasma-mobile checkout (default: ~/plasma-mobile)')
    parser.add_argument('--build-dir', type=Path, default=Path('/tmp/taskpanel-build'))
    parser.add_argument('--uninstall', action='store_true', help='put the packaged task panel back')
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
        return

    source = args.source.expanduser().resolve()
    if not (source / 'containments/taskpanel/statusnotifierhost.cpp').exists():
        sys.exit(f'{source} does not look like the patched plasma-mobile checkout')
    if not shutil.which('cmake'):
        sys.exit('cmake is not installed: see the module docstring for the build packages')

    install(source, args.build_dir)
    print('the task panel now draws the session\'s tray icons next to the navigation buttons')


if __name__ == '__main__':
    main()
