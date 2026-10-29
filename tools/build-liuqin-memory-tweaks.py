#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the incremental memory-tweaks package for an installed tablet.

The full image needs inputs that only the release pipeline has (a pinned Ubuntu
casco rootfs, the audioreach topology checkout, an arm64 chroot).  This package
is the part that can be assembled from what is verified here, so a tablet
installed from the 0.6.0 bundle can gain the same behaviour without waiting for
a new bundle:

  memory-tweaks_<version>_arm64.deb
      the zram geometry, the reviewed trim list, liuqin-root-trim and the unit
      masks, applied by the same script the installer now runs
  boot-<kernel-release>-zram.img
      a boot image whose only difference from the 0.6.0 one is the kernel, so
      CONFIG_ZRAM exists at all

Nothing here decides a policy; it packages the files under device/configs,
device/gnome-overlay and device/tweaks, and copies the kernel that
tools/build-liuqin-kernel.py produced from the pinned commit.

    python3 tools/build-liuqin-memory-tweaks.py --kernel-out out/kernel-zram
    python3 tools/build-liuqin-memory-tweaks.py --kernel-out out/kernel-zram --no-deb

The output is written under out/memory-tweaks/ and is not a release verdict:
device validation is a separate step, the same rule the other builders follow.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / 'out/memory-tweaks'
BUNDLE = PROJECT / 'tools/local/bundles/v0.6.0'


def die(msg):
    raise SystemExit('build-liuqin-memory-tweaks: ' + msg)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def build_deb(out):
    """Assemble the deb from the staged payload, never from ad-hoc copies."""
    work = Path(tempfile.mkdtemp(prefix='liuqin-tweaks-deb-'))
    try:
        root = work / 'root'
        run(['sh', str(PROJECT / 'device/tweaks/stage-payload.sh'), str(work)])
        payload = work / 'payload'
        # data.tar: the payload files, plus the applier and its README.
        for rel in ('etc/systemd/zram-generator.conf',
                    'usr/share/liuqin/root-trim.txt',
                    'usr/local/sbin/liuqin-root-trim'):
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(payload / rel, dst)
            os.chmod(dst, 0o755 if rel.startswith('usr/local/sbin') else 0o644)
        # apply-root-tweaks.sh expects payload/ next to itself.  The deb carries
        # the script under /usr/lib/liuqin/ and its payload beside it, which is
        # the same layout the installer image uses.
        libdir = root / 'usr/lib/liuqin'
        libdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / 'device/tweaks/apply-root-tweaks.sh',
                        libdir / 'apply-root-tweaks.sh')
        os.chmod(libdir / 'apply-root-tweaks.sh', 0o755)
        shutil.copytree(payload, libdir / 'payload')

        # The per-account half.  postinst covers the accounts that exist at
        # install time; this unit covers the first login after a fresh install,
        # when gnome-initial-setup has just created one.
        bindir = root / 'usr/local/libexec'
        bindir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / 'device/tweaks/liuqin-session-tweaks.sh',
                        bindir / 'liuqin-session-tweaks')
        os.chmod(bindir / 'liuqin-session-tweaks', 0o755)
        unitdir = root / 'usr/lib/systemd/user'
        unitdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / 'device/tweaks/liuqin-session-tweaks.service',
                        unitdir / 'liuqin-session-tweaks.service')
        os.chmod(unitdir / 'liuqin-session-tweaks.service', 0o644)
        wanted = root / 'usr/lib/systemd/user/default.target.wants'
        wanted.mkdir(parents=True, exist_ok=True)
        os.symlink('../../../lib/systemd/user/liuqin-session-tweaks.service',
                   wanted / 'liuqin-session-tweaks.service')

        # dpkg-deb builds one tree whose DEBIAN/ directory is the control area.
        control = root / 'DEBIAN'
        control.mkdir()
        version = (PROJECT / 'device/tweaks/version').read_text().strip()
        (control / 'control').write_text(
            'Package: liuqin-memory-tweaks\n'
            'Version: %s\n'
            'Architecture: arm64\n'
            'Maintainer: liuqin project <noreply@example.invalid>\n'
            'Section: misc\n'
            'Priority: optional\n'
            'Depends: systemd-zram-generator\n'
            'Description: zram swap geometry, package trim and unit masks for liuqin\n'
            ' The install layout has no swap partition, so the product kernel\n'
            ' needs zram and systemd-oomd needs something to reclaim.  This\n'
            ' package also ships the reviewed trim list, the command that applies\n'
            ' it, and the masks for the two daemons whose packages must stay.\n'
            ' The kernel side (CONFIG_ZRAM) is a boot image, not a package.\n'
            % version)
        (control / 'conffiles').write_text(
            '/etc/systemd/zram-generator.conf\n/usr/share/liuqin/root-trim.txt\n')

        # postinst applies the files to the live root.  The purge is skipped:
        # this package's job is to make the tree correct, and removing packages
        # from under a running session belongs to an explicit liuqin-root-trim.
        postinst = control / 'postinst'
        postinst.write_text(
            '#!/bin/sh\n'
            'set -e\n'
            '# The [mask-user] section applies per account, so it is applied here for\n'
            '# every human account that already exists.  An account created later\n'
            '# (gnome-initial-setup on a fresh install) gets it from\n'
            '# liuqin-session-tweaks, which runs in that session.\n'
            'apply_user() {\n'
            '\tacct=$1\n'
            '\t[ -n "$acct" ] || return 0\n'
            '\tsh /usr/lib/liuqin/apply-root-tweaks.sh / --no-purge --user "$acct" || {\n'
            '\t\techo "liuqin-memory-tweaks: per-user tweaks failed for $acct" >&2\n'
            '\t\treturn 1\n'
            '\t}\n'
            '}\n'
            'case $1 in\n'
            'configure)\n'
            '\tsh /usr/lib/liuqin/apply-root-tweaks.sh / --no-purge --no-user || exit 1\n'
            '\t# Every human account, by uid range, so a system account can never be\n'
            '\t# picked up by accident.\n'
            '\tawk -F: \'$3 >= 1000 && $3 < 60000 { print $1 }\' /etc/passwd |\n'
            '\t\twhile read -r account; do apply_user "$account" || exit 1; done\n'
            '\tif [ -d /run/systemd/system ]; then systemctl daemon-reload || :; fi\n'
            '\tcommand -v dconf >/dev/null && dconf update || :\n'
            '\t;;\n'
            'esac\n'
            'exit 0\n')
        os.chmod(postinst, 0o755)

        # Reproducible: dpkg-deb copies filesystem timestamps into the
        # archive, so without this two runs of an unchanged tree produced two
        # different bytes.  0 is the epoch the release archives already use.
        for path in [root, *root.rglob('*')]:
            os.utime(path, (0, 0), follow_symlinks=False)

        deb = out / ('liuqin-memory-tweaks_%s_arm64.deb' % version)
        env = dict(os.environ, SOURCE_DATE_EPOCH='0', TZ='UTC')
        run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(deb)],
            stdout=subprocess.DEVNULL, env=env)
        return deb
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kernel-out', type=Path, default=PROJECT / 'out/kernel',
                        help='kernel build with CONFIG_ZRAM (see liuqin-memory.config)')
    parser.add_argument('--bundle', type=Path, default=BUNDLE,
                        help='release bundle whose ramdisk and DTB are device-tested')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--no-deb', action='store_true')
    parser.add_argument('--no-boot', action='store_true')
    args = parser.parse_args()

    out = args.out.resolve()
    if out.exists():
        die('output already exists; use a fresh directory: %s' % out)
    out.mkdir(parents=True)

    lock = json.loads((PROJECT / 'kernel/source.json').read_text())
    kernel_out = args.kernel_out.resolve()
    if not (kernel_out / '.config').is_file():
        die('not a kernel build: %s' % kernel_out)
    if sha256(kernel_out / '.config') != lock['config_sha256']:
        die('the kernel build does not match kernel/source.json')

    identity = {
        'kernel_commit': lock['commit'],
        'kernel_config_sha256': lock['config_sha256'],
        'kernel_image_sha256': sha256(kernel_out / 'arch/arm64/boot/Image'),
    }
    files = []

    if not args.no_boot:
        # deploy-liuqin-boot.py already does this correctly and refuses a kernel
        # that does not match the lock; reuse it instead of a second repacker.
        stage = out / 'boot'
        stage.mkdir()
        run([sys.executable, str(PROJECT / 'tools/deploy-liuqin-boot.py'),
             '--kernel-out', str(kernel_out), '--bundle', str(args.bundle),
             '--out', str(stage), '--dry-run'])
        boot = stage / 'boot.img'
        if not boot.is_file():
            die('the boot image was not produced')
        release = (kernel_out / 'include/config/kernel.release').read_text().strip()
        named = out / ('boot-%s-zram.img' % release)
        boot.rename(named)
        identity['boot_sha256'] = sha256(named)
        identity['boot_bytes'] = named.stat().st_size
        identity['bundle_boot_sha256'] = sha256(args.bundle / 'boot.img')
        files.append(named)

    if not args.no_deb:
        deb = build_deb(out)
        identity['deb_sha256'] = sha256(deb)
        files.append(deb)

    (out / 'memory-tweaks.identity').write_text(
        ''.join('%s=%s\n' % (k, v) for k, v in sorted(identity.items())))
    (out / 'SHA256SUMS').write_text(
        ''.join('%s  %s\n' % (sha256(f), f.name) for f in files))
    (out / 'README.md').write_text(
        '# liuqin memory tweaks, incremental\n\n'
        'For a tablet already installed from the v0.6.0 bundle. A bundle built\n'
        'after this change carries all of it natively: `install-root.sh` runs\n'
        '`apply-root-tweaks.sh` on the extracted tree, and the kernel comes from\n'
        '`kernel/source.json` with `liuqin-memory.config` in its fragment list.\n\n'
        '## What is in here\n\n'
        '| File | Purpose |\n|---|---|\n'
        '| `boot-*-zram.img` | the 0.6.0 boot image with only its kernel replaced; '
        'adds `CONFIG_ZRAM` |\n'
        '| `liuqin-memory-tweaks_*.deb` | zram geometry, trim list, '
        '`liuqin-root-trim` and the unit masks |\n\n'
        '## Applying it\n\n'
        '```sh\n'
        '# 1. the kernel, or zram has no driver to bind\n'
        'sudo blockdev --setrw /dev/sde\n'
        'sudo blockdev --setrw /dev/sde14\n'
        'sudo dd if=boot-*-zram.img of=/dev/disk/by-partlabel/boot_a bs=1M '
        'conv=notrunc,fsync\n'
        'sync && sudo reboot\n\n'
        '# 2. the root filesystem side\n'
        'sudo apt-get install -y ./liuqin-memory-tweaks_*_arm64.deb\n'
        'sudo liuqin-root-trim --dry-run   # what the trim would remove\n'
        'sudo liuqin-root-trim             # remove it, then reboot\n'
        '```\n\n'
        '`tools/deploy-liuqin-boot.py` does step 1 with a read-back check, the\n'
        'read-only flags restored, and the live partition saved first; prefer it\n'
        'over the dd above. `liuqin-root-trim` is idempotent and refuses to run\n'
        'if a `[keep]` package is missing.\n\n'
        '## Verifying\n\n'
        '```sh\n'
        'adb -s liuqin push tests/memory-features.py /tmp/\n'
        'adb -s liuqin shell \'python3 /tmp/memory-features.py \\\n'
        '  --config /proc/config.gz --root / --packages\'\n'
        '```\n')

    print('wrote %s' % out)
    for f in files:
        print('  %-52s %s' % (f.name, sha256(f)[:16]))


if __name__ == '__main__':
    main()
