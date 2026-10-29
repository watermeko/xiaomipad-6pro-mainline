#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Cache ten SHA-pinned FPC TA files from this tablet's read-only modem FAT.

No firmware bytes are distributed by liuqin-fingerprint. This runs once before
late module load, after the installer has repaired modem_a. Failure disables
fingerprint startup; it never repairs a partition or touches biometric state.

Two ROM releases have shipped a different fpcliu image on this device.  The
manifest therefore holds several identities and this script picks ONE set for
the whole ten-file image:

  * fpcliu.mdt is the ELF header and program headers of the image, and
    fpcliu.b08 carries its signature.  Those two are what changed between
    releases; the eight b00-b07 segments are byte-identical.  Selecting a set
    per file would let a unit that matches no release be assembled out of two,
    producing an image whose header and signature do not describe its body.
    That is why a set is matched wholesale and a partial match is refused
    rather than repaired.
  * A unit matching no set disables the service, as before.  Holding several
    identities widens which stock images are accepted; it does not make the
    check advisory.

Adding a release is a deliberate act: its ten hashes go in SHA256.json with the
ROM version and source they came from, and every hash must be reproduced from
that ROM's NON-HLOS.bin rather than copied from a device.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

NAMES = ("fpcliu.mdt", *(f"fpcliu.b{i:02d}" for i in range(9)))
MODEM = "/dev/disk/by-partlabel/modem_a"


def _valid_hashes(files):
    return (isinstance(files, dict) and set(files) == set(NAMES) and
            all(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value)
                for value in files.values()))


def checked_hashes(directory):
    """Return the accepted identities: [(label, {name: digest}), ...].

    Schema 1 (a single flat map) is still accepted so an already-installed
    package keeps working across an upgrade; it is simply one identity with no
    label.
    """
    raw = json.loads((directory / "SHA256.json").read_text())
    if isinstance(raw, dict) and set(raw) == set(NAMES):
        if not _valid_hashes(raw):
            raise ValueError("invalid fixed FPC firmware manifest")
        return [("schema1", raw)]
    if not isinstance(raw, dict) or raw.get("schema") != 2:
        raise ValueError("invalid fixed FPC firmware manifest")
    sets = raw.get("sets")
    if not isinstance(sets, list) or not sets:
        raise ValueError("invalid fixed FPC firmware manifest")
    identities = []
    seen = {}
    for entry in sets:
        if not isinstance(entry, dict):
            raise ValueError("invalid fixed FPC firmware manifest")
        label = entry.get("rom")
        if not isinstance(label, str) or not label:
            raise ValueError("invalid fixed FPC firmware manifest")
        files = entry.get("files")
        if not _valid_hashes(files):
            raise ValueError("invalid fixed FPC firmware manifest")
        # A set that repeats another set adds nothing and hides a mistake.
        key = tuple(sorted(files.items()))
        if key in seen:
            raise ValueError("duplicate FPC firmware identity: " + label)
        seen[key] = label
        identities.append((label, files))
    return identities


def matches(path, digest):
    if path.is_symlink():
        raise ValueError("refuse symlink in FPC firmware cache")
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def matching_identity(directory, identities):
    """The one identity `directory` matches in full, or None."""
    matched = [(label, files) for label, files in identities
               if all(matches(directory / name, digest) for name, digest in files.items())]
    return matched[0] if len(matched) == 1 else None


def provision(directory):
    if os.geteuid() != 0:
        raise RuntimeError("root required")
    directory = Path(directory)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or
            info.st_mode & 0o022):
        raise ValueError("untrusted FPC firmware cache")
    identities = checked_hashes(directory)
    cached = matching_identity(directory, identities)
    if cached is not None:
        print("fpc_firmware=READY source=verified_cache rom=" + cached[0])
        return
    mountpoint = Path(tempfile.mkdtemp(prefix="liuqin-fpc-modem-", dir="/run"))
    mounted = False
    try:
        subprocess.run(["mount", "-t", "vfat", "-o",
                        "ro,nodev,nosuid,noexec,codepage=437,iocharset=iso8859-1",
                        MODEM, str(mountpoint)], check=True, timeout=15)
        mounted = True
        image = mountpoint / "image"
        # Choose the identity from the mounted image, as a whole.  A unit that
        # matches none is refused with the two file names that identify a
        # release, so the diagnostic says what to compare rather than only that
        # something is wrong.
        identity = matching_identity(image, identities)
        if identity is None:
            present = {}
            for name in NAMES:
                source = image / name
                present[name] = (hashlib.sha256(source.read_bytes()).hexdigest()
                                 if source.is_file() and not source.is_symlink() else "-")
            known = {label: files for label, files in identities}
            hint = "; ".join("%s=%s" % (name, present[name][:12] + "…")
                             for name in ("fpcliu.mdt", "fpcliu.b08"))
            raise RuntimeError(
                "stock FPC firmware matches none of the %d known ROM identities "
                "(%s); this unit's %s, known: %s" % (
                    len(known), ", ".join(known), hint,
                    ", ".join("%s mdt=%s" % (label, files["fpcliu.mdt"][:12] + "…")
                              for label, files in identities)))
        label, hashes = identity
        with tempfile.TemporaryDirectory(prefix=".provision-", dir=directory) as staging:
            stage = Path(staging)
            for name in NAMES:
                source = image / name
                target = stage / name
                # Recheck the exact copied bytes before publishing any member.
                target.write_bytes(source.read_bytes())
                target.chmod(0o600)
                if not matches(target, hashes[name]):
                    raise RuntimeError("copied FPC firmware hash mismatch: " + name)
            for name in NAMES:
                if (directory / name).is_symlink():
                    raise ValueError("refuse symlink in FPC firmware cache")
            for name in NAMES:
                os.replace(stage / name, directory / name)
    finally:
        # Never recursively remove a mountpoint. A failed umount is an error,
        # leaving the read-only mount intact for diagnosis, with no retry loop.
        if mounted:
            subprocess.run(["umount", str(mountpoint)], check=True, timeout=15)
        mountpoint.rmdir()
    print("fpc_firmware=READY source=local_modem_read_only rom=" + label)


if __name__ == "__main__":
    provision(Path(__file__).resolve().parent / "firmware")
