#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write a rebuilt kernel into the liuqin boot_a partition.

This is the loop for kernel work on an installed tablet: read the boot image
the tablet boots today, replace *only* the kernel bytes with a locally built
Image, and write the result to boot_a the same way liuqin-switch does (whole
partition, zero fill, sync, flush, read back, compare, read-only flags restored
on every exit path).

The base has to be the live boot_a rather than a release bundle's boot.img.
The ramdisk carries the admission contract that the installed root filesystem
is checked against, and the installer writes it into the boot image it installs;
a bundle's boot.img is the unpatched template.  Deploying a kernel on top of
the template makes the tablet boot the installer instead of the installed
system, which is exactly what happened once and cost an hour in the initramfs
shell.  `--base` still accepts a bundle directory for a tablet that really does
boot that bundle's own image.

Doing it this way keeps the change small enough to reason about: the ramdisk,
the device tree and the ABL overlay are the device-tested ones from the
bundle, so a boot failure is attributable to the kernel build.

    python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel-zram
    python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel-zram --dry-run
    python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel-zram --no-reboot

The kernel build must satisfy kernel/source.json: same commit, same generated
configuration, same fragment set.  A development build made with --revision is
accepted when its fragments are byte-identical to the lock's, which is exactly
the rule tools/build-liuqin-image.py applies to a product build.

Nothing here writes boot_b, the slot attributes, vbmeta or the store: boot_b
keeps the bootloader's fallback copy, which is the way back if this image does
not load.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
BOOT_LABEL = 'boot_a'
BOOT_BYTES = 201326592  # the pinned boot_a size on the known 256 GB layout
BACKUP_DIR = PROJECT / 'backups/liuqin-boot'

# The device-side writer.  POSIX sh, no arrays, no $((  )) above 2^31: it runs
# under the tablet's dash and is modelled on liuqin-switch's write_image.
WRITER = r'''
set -eu
LABEL=$1
IMG=$2
EXPECT=$3
B=/dev/disk/by-partlabel/$LABEL
[ -e "$B" ] || { echo "no such partition label: $LABEL" >&2; exit 1; }
DEV=$(readlink -f "$B")
[ -b "$DEV" ] || { echo "not a block device: $DEV" >&2; exit 1; }
PART_BYTES=$(blockdev --getsize64 "$DEV")
[ "$PART_BYTES" = "201326592" ] || {
	echo "unexpected partition size $PART_BYTES; refusing" >&2; exit 1; }
SZ=$(stat -c %s "$IMG")
[ "$SZ" -le "$PART_BYTES" ] || { echo "image larger than the partition" >&2; exit 1; }
DISK=/dev/$(basename "$(readlink -f "/sys/class/block/$(basename "$DEV")/..")")

PART_RO=$(blockdev --getro "$DEV")
DISK_RO=$(blockdev --getro "$DISK")
restore() {
	blockdev --setro "$DISK" 2>/dev/null || :
	[ "$PART_RO" = 1 ] && blockdev --setro "$DEV" 2>/dev/null || blockdev --setrw "$DEV" 2>/dev/null || :
	[ "$DISK_RO" = 1 ] || blockdev --setrw "$DISK" 2>/dev/null || :
}
trap restore EXIT HUP INT TERM
blockdev --setrw "$DISK"
blockdev --setrw "$DEV"

dd if="$IMG" of="$DEV" bs=1048576 conv=notrunc,fsync 2>/dev/null
sync
blockdev --flushbufs "$DEV" 2>/dev/null || :

GOT=$(head -c "$SZ" "$DEV" | sha256sum | cut -d' ' -f1)
if [ "$GOT" != "$EXPECT" ]; then
	echo "read-back mismatch: wrote $EXPECT, read $GOT" >&2
	exit 1
fi
echo "boot_a write verified: $GOT"
'''

UNPACK = 'tools/local/aosp-mkbootimg/unpack_bootimg.py'
MKBOOTIMG = 'tools/local/aosp-mkbootimg/mkbootimg.py'


def die(msg):
    raise SystemExit('deploy-liuqin-boot: ' + msg)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd, check=True, **kwargs):
    return subprocess.run(cmd, check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)


def adb(serial, *args, **kwargs):
    return run(['adb', '-s', serial, *args], **kwargs)


def adb_bytes(serial, *args):
    """adb exec-out, raw bytes: partition dumps are not text."""
    result = subprocess.run(['adb', '-s', serial, *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def check_kernel(kernel_out):
    """The kernel build has to be the one kernel/source.json describes."""
    lock = json.loads((PROJECT / 'kernel/source.json').read_text())
    info = json.loads((kernel_out / 'build-info.json').read_text())
    config = (kernel_out / '.config').read_bytes()
    if hashlib.sha256(config).hexdigest() != lock['config_sha256']:
        die('kernel .config differs from kernel/source.json; rebuild the kernel')
    if info['config_sha256'] != lock['config_sha256']:
        die('kernel build-info names another configuration')
    if info['commit'] != lock['commit']:
        die('kernel build is %s, the lock is %s; pass a build of the pinned commit'
            % (info['commit'][:12], lock['commit'][:12]))
    expected = {path: hashlib.sha256((PROJECT / path).read_bytes()).hexdigest()
                for path in lock['config_fragments']}
    if info['fragments'] != expected:
        die('kernel build used different config fragments than the lock')
    for name in ('arch/arm64/boot/Image',
                 'arch/arm64/boot/dts/' + lock['dtb']):
        if not (kernel_out / name).is_file():
            die('kernel build is missing ' + name)
    return lock


def repack(base_image, kernel_out, out, dtb=None):
    """Repack a boot image with only its kernel replaced."""
    unpack_dir = Path(tempfile.mkdtemp(prefix='liuqin-unpack-'))
    header_dir = Path(tempfile.mkdtemp(prefix='liuqin-header-'))
    try:
        run([sys.executable, str(PROJECT / UNPACK), '--boot_img', str(base_image),
             '--out', str(unpack_dir)])
        # unpack_bootimg writes the extracted parts as a side effect and defaults
        # --out to ./out/kernel, so the header pass needs a directory of its own.
        header = run([sys.executable, str(PROJECT / UNPACK),
                      '--boot_img', str(base_image),
                      '--out', str(header_dir)]).stdout
        fields = {}
        for line in header.splitlines():
            if ':' in line:
                key, _, value = line.partition(':')
                fields[key.strip()] = value.strip()
        if fields.get('boot magic') != 'ANDROID!':
            die('%s is not an Android boot image' % base_image)
        if fields.get('boot image header version') != '2':
            die('expected a header version 2 image, found %s'
                % fields.get('boot image header version'))
        if fields.get('page size') != '4096':
            die('expected 4096 byte pages')
        original = {'ramdisk': sha256(unpack_dir / 'ramdisk')}
        if dtb:
            # A rebuilt device tree is a legitimate thing to deploy: the sleep
            # state node this work needed lives in it, and the kernel alone
            # cannot carry it.  Everything else in the image still has to
            # survive byte for byte.
            shutil.copyfile(dtb, unpack_dir / 'dtb')
            original['dtb'] = sha256(dtb)
        else:
            original['dtb'] = sha256(unpack_dir / 'dtb')

        image = kernel_out / 'arch/arm64/boot/Image'
        kernel_gz = out / 'kernel.gz'
        # gzip -n -9: no timestamp, maximum compression.  build-bootimg.sh uses
        # exactly this, so the bytes are reproducible build over build.
        with open(kernel_gz, 'wb') as handle:
            subprocess.run(['gzip', '-n', '-9', '-c', str(image)],
                           check=True, stdout=handle)

        offsets = {
            'kernel_offset': fields.get('kernel load address', '0x00008000'),
            'ramdisk_offset': fields.get('ramdisk load address', '0x01000000'),
            'second_offset': fields.get('second bootloader load address', '0x00000000'),
            'tags_offset': fields.get('kernel tags load address', '0x00000100'),
            'dtb_offset': fields.get('dtb address', '0x01f00000'),
        }
        for key, value in offsets.items():
            try:
                int(value, 16)
            except ValueError:
                die('cannot read %s from the bundle header: %r' % (key, value))
        cmd = [sys.executable, str(PROJECT / MKBOOTIMG),
               '--kernel', str(kernel_gz),
               '--ramdisk', str(unpack_dir / 'ramdisk'),
               '--dtb', str(unpack_dir / 'dtb'),
               '--header_version', '2',
               '--pagesize', '4096',
               '--base', '0x00000000',
               '--cmdline', fields.get('command line args', '')]
        for key, value in offsets.items():
            cmd += ['--' + key, value]
        cmd += ['-o', str(out / 'boot.img')]
        run(cmd)

        # Re-unpack what we just built and prove the untouched parts survived.
        verify_dir = Path(tempfile.mkdtemp(prefix='liuqin-verify-'))
        try:
            run([sys.executable, str(PROJECT / UNPACK), '--boot_img',
                 str(out / 'boot.img'), '--out', str(verify_dir)])
            for part, digest in original.items():
                if sha256(verify_dir / part) != digest:
                    die('%s changed while repacking; the base image was not reused' % part)
        finally:
            shutil.rmtree(verify_dir, ignore_errors=True)
        return out / 'boot.img'
    finally:
        shutil.rmtree(unpack_dir, ignore_errors=True)
        shutil.rmtree(header_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--serial', default='liuqin', help='adb serial of the tablet')
    parser.add_argument('--kernel-out', type=Path, default=PROJECT / 'out/kernel',
                        help='kernel build directory (arch/arm64/boot/Image, .config)')
    parser.add_argument('--base', '--bundle', dest='base', type=Path,
                        help='boot image, or a release bundle directory holding '
                             'one, to take the ramdisk and DTB from.  The default '
                             'is the live boot_a, which is the only image whose '
                             'ramdisk carries the admission contract this root '
                             'filesystem was installed with: a bundle boot.img is '
                             'the unpatched template, and replacing the live one '
                             'with it makes the tablet boot the installer.')
    parser.add_argument('--out', type=Path, default=PROJECT / 'out/boot-deploy',
                        help='where the repacked image and its identity are written')
    parser.add_argument('--backup', type=Path, default=BACKUP_DIR,
                        help='where the current boot_a is saved before the write')
    parser.add_argument('--dtb', type=Path,
                        help='replace the base image\'s device tree with this one '
                             '(the kernel build\'s DTB, for changes that live in the '
                             'device tree); the ramdisk still comes from --base')
    parser.add_argument('--dry-run', action='store_true',
                        help='build and verify the image; write nothing, reboot nothing')
    parser.add_argument('--no-reboot', action='store_true', help='write, but do not reboot')
    args = parser.parse_args()

    kernel_out = args.kernel_out.resolve()
    out = args.out.resolve()
    if not (kernel_out / 'build-info.json').is_file():
        die('not a kernel build directory: %s (run tools/build-liuqin-kernel.py)' % kernel_out)
    lock = check_kernel(kernel_out)
    out.mkdir(parents=True, exist_ok=True)

    # The ramdisk carries the admission contract this root filesystem was
    # installed with, so the only safe base is the boot image the tablet boots
    # today.  It is read out first, and the same bytes become the backup.
    backup = None
    if args.base:
        base_image = args.base.resolve()
        if base_image.is_dir():
            base_image = base_image / 'boot.img'
        if not base_image.is_file():
            die('no boot image at %s' % base_image)
    else:
        adb(args.serial, 'shell', 'true')
        live = adb_bytes(args.serial, 'exec-out',
                         'dd if=/dev/disk/by-partlabel/%s bs=1M count=%d 2>/dev/null'
                         % (BOOT_LABEL, BOOT_BYTES // (1024 * 1024)))
        if len(live) != BOOT_BYTES:
            die('could not read the live %s (%d of %d bytes); nothing was written'
                % (BOOT_LABEL, len(live), BOOT_BYTES))
        base_image = out / 'live-boot_a.img'
        base_image.write_bytes(live)
        args.backup.mkdir(parents=True, exist_ok=True)
        backup = args.backup / ('%s-%s.img'
                                % (BOOT_LABEL, hashlib.sha256(live).hexdigest()[:12]))
        if not backup.exists():
            backup.write_bytes(live)
        print('backup: %s' % backup)

    boot = repack(base_image, kernel_out, out, args.dtb)
    boot_sha = sha256(boot)
    size = boot.stat().st_size
    print('base: %s' % base_image)
    print('image: %s (%d bytes)' % (boot, size))
    print('sha256: %s' % boot_sha)

    identity = out / 'deploy.identity'
    identity.write_text(''.join('%s=%s\n' % (key, value) for key, value in (
        ('kernel_commit', lock['commit']),
        ('kernel_config_sha256', lock['config_sha256']),
        ('kernel_image_sha256', sha256(kernel_out / 'arch/arm64/boot/Image')),
        ('base_image_sha256', sha256(base_image)),
        ('base_image', str(base_image)),
        ('boot_sha256', boot_sha),
        ('boot_bytes', size),
    )))
    print('identity: %s' % identity)

    if args.dry_run:
        print('dry run: nothing was written to the tablet')
        return

    (args.backup / 'README.md').write_text(
        '# boot_a before kernel deployments\n\n'
        'Each file is a byte-exact copy of boot_a taken by\n'
        '`tools/deploy-liuqin-boot.py` before it wrote a rebuilt kernel.  The\n'
        'filename suffix is the first twelve hex digits of the image hash.\n\n'
        'To restore one from the tablet:\n\n'
        '```sh\n'
        'adb -s liuqin push <file> /tmp/restore.img\n'
        'adb -s liuqin shell \'blockdev --setrw /dev/sde; blockdev --setrw /dev/sde14;\n'
        '  dd if=/tmp/restore.img of=/dev/disk/by-partlabel/boot_a bs=1M conv=notrunc,fsync\'\n'
        'adb -s liuqin reboot\n'
        '```\n\n'
        'These files are large; they are not committed.\n')

    remote = '/tmp/liuqin-deploy-boot.img'
    adb(args.serial, 'push', str(boot), remote)
    writer = '/tmp/liuqin-deploy-write.sh'
    with tempfile.NamedTemporaryFile('w', delete=False) as handle:
        handle.write(WRITER)
        local_writer = handle.name
    try:
        adb(args.serial, 'push', local_writer, writer)
    finally:
        os.unlink(local_writer)
    result = adb(args.serial, 'shell', 'sh', writer, BOOT_LABEL, remote, boot_sha)
    print(result.stdout.strip())
    adb(args.serial, 'shell', 'rm -f %s %s' % (remote, writer))

    if not args.no_reboot:
        print('rebooting; the new kernel should report the same release with zram present')
        adb(args.serial, 'shell', 'sync; systemctl reboot', check=False)


if __name__ == '__main__':
    main()
