#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replace the native-root admission files inside a device-tested boot image.

Stage 1 of the feature phones this project supports decides whether a root
filesystem may be handed over.  For the native profile that decision lives in
two files *inside the initramfs*:

    init                            the checks themselves
    etc/liuqin-native-root.contract hashes of the project-owned files

Changing the desktop (GNOME -> Plasma Mobile) changes both: the checks name
the session's binaries and the login manager, and the contract covers the new
project files.  Rebuilding the whole boot image needs the firmware pool and the
device-layer manifests; this tool does the smaller, attributable change -- it
reuses the kernel and device tree of an image the bootloader already accepts
and replaces exactly those two ramdisk entries.  Every other ramdisk entry is
copied byte for byte, and the tool proves it by re-reading the result.

    # build the image and check it, write nothing
    python3 tools/patch-native-admission.py --boot-img out/boot-deploy/boot.img \\
        --contract /tmp/native-root.contract --dry-run

    # write it to boot_a (boot_b keeps the bootloader's fallback copy)
    python3 tools/patch-native-admission.py --boot-img out/boot-deploy/boot.img \\
        --contract /tmp/native-root.contract

The contract is generated from the assembled (or installed) root:

    python3 tools/lib/build-root-contract.py --profile native \\
        --device-layer-manifest <manifest> --output /tmp/native-root.contract
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
DEPLOY = PROJECT / 'tools/deploy-liuqin-boot.py'
REPLACED = ('init', 'etc/liuqin-native-root.contract')


def load_deploy():
    """Reuse the flashing path (writer, backup, read-back) from the kernel tool."""
    spec = importlib.util.spec_from_file_location('deploy_boot', DEPLOY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_newc(blob):
    """Split a newc cpio archive into (name, header, data) entries plus trailer.

    newc headers are 110 ASCII bytes: magic, 13 eight-digit hex fields, then a
    NUL-terminated name padded to four bytes and data padded to four bytes.
    """
    entries = []
    offset = 0
    while True:
        header = blob[offset:offset + 110]
        if len(header) != 110 or header[:6] != b'070701':
            raise SystemExit('initramfs is not a newc cpio archive (offset %d)' % offset)
        fields = [int(header[6 + index * 8:14 + index * 8], 16) for index in range(13)]
        filesize, namesize = fields[6], fields[11]
        # 110 is not a multiple of four, so the name is padded to the next
        # four-byte boundary *from the header start*, not from the name start.
        name_start = offset + 110
        name = blob[name_start:name_start + namesize - 1].decode()
        data_start = name_start + namesize + (-(110 + namesize)) % 4
        data = blob[data_start:data_start + filesize]
        end = data_start + filesize + (-filesize) % 4
        entries.append({'name': name, 'header': header, 'data': data,
                        'start': offset, 'end': end})
        offset = end
        if name == 'TRAILER!!!':
            break
    return entries, blob[offset:]


def rewrite_archive(blob, replacements):
    """Replace named entries, keeping order, modes, owners and padding."""
    entries, tail = parse_newc(blob)
    seen = set()
    out = bytearray()
    for entry in entries:
        name = entry['name']
        if name in replacements:
            payload = replacements[name]
            header = bytearray(entry['header'])
            header[6 + 6 * 8:14 + 6 * 8] = b'%08x' % len(payload)
            out += bytes(header)
            out += name.encode() + b'\0'
            out += b'\0' * ((-(110 + len(name) + 1)) % 4)
            out += payload + b'\0' * ((-len(payload)) % 4)
            seen.add(name)
        else:
            out += blob[entry['start']:entry['end']]
    missing = set(replacements) - seen
    if missing:
        raise SystemExit('initramfs has no entry for: ' + ', '.join(sorted(missing)))
    out += tail
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--boot-img', type=Path,
                        default=PROJECT / 'out/boot-deploy/boot.img',
                        help='device-tested boot image to patch (kernel/dtb are reused)')
    parser.add_argument('--init', type=Path, default=PROJECT / 'initramfs/init',
                        help='stage-1 init to embed')
    parser.add_argument('--contract', type=Path, required=True,
                        help='native-root.contract for the root this image must admit')
    parser.add_argument('--out', type=Path, default=PROJECT / 'out/boot-admission',
                        help='output directory for the patched image')
    parser.add_argument('--serial', default='liuqin')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='build and verify, write nothing')
    parser.add_argument('--no-reboot', action='store_true')
    args = parser.parse_args()

    deploy = load_deploy()
    boot_in = args.boot_img.resolve()
    for path in (boot_in, args.init, args.contract):
        if not path.is_file():
            raise SystemExit('missing input: %s' % path)

    work = Path(tempfile.mkdtemp(prefix='liuqin-admission-'))
    try:
        # -- the original image, and the header fields it must keep ----------
        original = work / 'original'
        header_dir = work / 'header'
        deploy.run([sys.executable, str(deploy.UNPACK), '--boot_img', str(boot_in),
                    '--out', str(original)])
        header = deploy.run([sys.executable, str(deploy.UNPACK), '--boot_img',
                             str(boot_in), '--out', str(header_dir)]).stdout
        fields = {}
        for line in header.splitlines():
            if ':' in line:
                key, _, value = line.partition(':')
                fields[key.strip()] = value.strip()
        if fields.get('boot image header version') != '2':
            raise SystemExit('expected header version 2, found %r'
                             % fields.get('boot image header version'))

        # -- the ramdisk, entry by entry ------------------------------------
        ramdisk = (original / 'ramdisk').read_bytes()
        if ramdisk[:2] != b'\x1f\x8b':
            raise SystemExit('the ramdisk is not gzip-compressed')
        payload = gzip.decompress(ramdisk)
        replacements = {
            'init': args.init.read_bytes(),
            'etc/liuqin-native-root.contract': args.contract.read_bytes(),
        }
        patched = rewrite_archive(payload, replacements)
        # Prove that nothing but the two payloads changed.
        before, _ = parse_newc(payload)
        after, _ = parse_newc(patched)
        if [entry['name'] for entry in before] != [entry['name'] for entry in after]:
            raise SystemExit('the entry list changed while patching')
        for first, second in zip(before, after):
            if first['name'] in replacements:
                if second['data'] != replacements[first['name']]:
                    raise SystemExit('replacement did not land: %s' % first['name'])
            elif first['data'] != second['data'] or first['header'] != second['header']:
                raise SystemExit('untouched entry changed: %s' % first['name'])
        new_ramdisk = gzip.compress(patched, compresslevel=1, mtime=0)
        (work / 'ramdisk').write_bytes(new_ramdisk)

        # -- repack with the same header fields -----------------------------
        offsets = {
            'kernel_offset': fields.get('kernel load address', '0x00008000'),
            'ramdisk_offset': fields.get('ramdisk load address', '0x01000000'),
            'second_offset': fields.get('second bootloader load address', '0x00000000'),
            'tags_offset': fields.get('kernel tags load address', '0x00000100'),
            'dtb_offset': fields.get('dtb address', '0x01f00000'),
        }
        for key, value in offsets.items():
            int(value, 16)
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=True)
        image = out / 'boot.img'
        cmd = [sys.executable, str(deploy.MKBOOTIMG),
               '--kernel', str(original / 'kernel'),
               '--ramdisk', str(work / 'ramdisk'),
               '--dtb', str(original / 'dtb'),
               '--header_version', '2',
               '--pagesize', '4096',
               '--base', '0x00000000',
               '--cmdline', fields.get('command line args', '')]
        for key, value in offsets.items():
            cmd += ['--' + key, value]
        cmd += ['-o', str(image)]
        deploy.run(cmd)

        # -- re-read the result: kernel and DTB must be byte-identical ------
        verify = work / 'verify'
        deploy.run([sys.executable, str(deploy.UNPACK), '--boot_img', str(image),
                    '--out', str(verify)])
        for part in ('kernel', 'dtb'):
            if sha256(verify / part) != sha256(original / part):
                raise SystemExit('%s changed while repacking' % part)
        if gzip.decompress((verify / 'ramdisk').read_bytes()) != patched:
            raise SystemExit('the repacked ramdisk is not the patched archive')

        image_sha = sha256(image)
        print('image: %s (%d bytes)' % (image, image.stat().st_size))
        print('sha256: %s' % image_sha)
        print('init sha256: %s' % sha256(args.init))
        print('contract sha256: %s' % sha256(args.contract))

        if args.dry_run:
            print('dry run: nothing was written to the tablet')
            return

        # -- write boot_a exactly the way the kernel deploy does ------------
        backup_dir = args.backup or deploy.BACKUP_DIR
        live = deploy.adb_bytes(args.serial, 'exec-out',
                                'dd if=/dev/disk/by-partlabel/%s bs=1M count=%d 2>/dev/null'
                                % (deploy.BOOT_LABEL, deploy.BOOT_BYTES // (1024 * 1024)))
        if len(live) != deploy.BOOT_BYTES:
            raise SystemExit('could not read the live %s (%d of %d bytes); nothing was written'
                             % (deploy.BOOT_LABEL, len(live), deploy.BOOT_BYTES))
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / ('%s-%s.img' % (deploy.BOOT_LABEL,
                                              hashlib.sha256(live).hexdigest()[:12]))
        if not backup.exists():
            backup.write_bytes(live)
        print('backup: %s' % backup)

        remote = '/tmp/liuqin-admission-boot.img'
        writer = '/tmp/liuqin-admission-write.sh'
        deploy.adb(args.serial, 'push', str(image), remote)
        with tempfile.NamedTemporaryFile('w', delete=False) as handle:
            handle.write(deploy.WRITER)
            local_writer = handle.name
        try:
            deploy.adb(args.serial, 'push', local_writer, writer)
        finally:
            os.unlink(local_writer)
        result = deploy.adb(args.serial, 'shell', 'sh', writer, deploy.BOOT_LABEL,
                            remote, image_sha)
        print(result.stdout.strip())
        deploy.adb(args.serial, 'shell', 'rm -f %s %s' % (remote, writer))
        (out / 'admission.identity').write_text(''.join(
            '%s=%s\n' % (key, value) for key, value in (
                ('boot_img_in', str(boot_in)),
                ('boot_img_in_sha256', sha256(boot_in)),
                ('boot_sha256', image_sha),
                ('init_sha256', sha256(args.init)),
                ('contract_sha256', sha256(args.contract)),
            )))
        if not args.no_reboot:
            print('rebooting; the tablet should reach Plasma Mobile with sddm')
            # deploy.run() always passes check=True, and the reboot tears the
            # adb transport down before it can report, so do not reuse it here.
            subprocess.run(['adb', '-s', args.serial, 'shell', 'sync; systemctl reboot'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
