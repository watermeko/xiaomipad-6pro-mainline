#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 watermeko
# SPDX-License-Identifier: MIT
"""Build and install the on-screen keyboard (mytouchinput).

The keyboard is a Go program under device/touchinput.  It is cross-compiled on
the host for the tablet, installed as /usr/local/bin/mytouchinput, and the user
service that runs it is restarted.  The keyboard is shown and hidden from its
tray icon, so the task panel has to host StatusNotifierItems (see
plasma-mobile/source.json and tools/deploy-liuqin-taskpanel.py).

    python3 tools/deploy-liuqin-touchinput.py
    python3 tools/deploy-liuqin-touchinput.py --uninstall
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# The tablet answers on the USB link (usb0, 192.168.7.2) when the cable is
# attached and on its Wi-Fi address otherwise; try both.
TABLET = 'watermeko@192.168.7.2'
FALLBACK = 'watermeko@10.25.51.69'
SERVICE = 'mytouchinput.service'
TARGET = '/usr/local/bin/mytouchinput'
BACKUP = '/usr/local/share/mytouchinput.orig'
SOURCE = Path(__file__).resolve().parent.parent / 'device/touchinput'


def run(command, **kwargs):
    print('+', ' '.join(str(part) for part in command))
    return subprocess.run(command, check=True, **kwargs)


def ssh(tablet, *command):
    return run(['ssh', '-o', 'BatchMode=yes', tablet, ' '.join(command)])


def reachable(candidates):
    for candidate in candidates:
        probe = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=4', candidate, 'true'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            return candidate
    sys.exit('the tablet does not answer on ' + ' or '.join(candidates))


def build(output):
    run(['go', 'build', '-trimpath', '-ldflags', '-s -w', '-o', str(output), './'],
        cwd=SOURCE,
        env={**os.environ, 'GOOS': 'linux', 'GOARCH': 'arm64', 'CGO_ENABLED': '0'})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--host', default='',
                        help=f'the tablet (default: {TABLET}, then {FALLBACK})')
    parser.add_argument('--uninstall', action='store_true', help='put the previous binary back')
    args = parser.parse_args()
    tablet = args.host or reachable([TABLET, FALLBACK])

    if args.uninstall:
        ssh(tablet, f'sudo -n install -m 0755 {BACKUP} {TARGET} && systemctl --user restart {SERVICE}')
        print('the previous binary is back')
        return

    binary = Path('/tmp/mytouchinput-arm64')
    build(binary)
    print(f'built {binary} ({binary.stat().st_size} bytes)')

    run(['scp', '-q', str(binary), f'{tablet}:/tmp/mytouchinput-arm64'])
    # keep the binary that was there the first time, not the one we deployed last
    ssh(tablet, f'sudo -n test -e {BACKUP} || sudo -n install -D -m 0755 {TARGET} {BACKUP}; '
        f'sudo -n install -m 0755 /tmp/mytouchinput-arm64 {TARGET} && '
        f'systemctl --user restart {SERVICE} && sleep 2 && '
        f'systemctl --user is-active {SERVICE}')
    print('the keyboard now toggles from its tray icon')


if __name__ == '__main__':
    sys.exit(main())
