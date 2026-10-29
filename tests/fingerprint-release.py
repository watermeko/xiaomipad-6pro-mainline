#!/usr/bin/env python3
"""Offline firmware transaction/package staging tests; no hardware or host services."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


firmware = load("firmware", ROOT / "device/fingerprint/oem/src/fingerprint/deployment/provision_firmware.py")
package = load("release_package", ROOT / "tools/build-liuqin-fingerprint-deb.py")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.cache = self.base / "firmware"
        self.cache.mkdir(mode=0o700)
        self.data = {name: (name + " fixture").encode() for name in firmware.NAMES}
        self.hashes = {name: hashlib.sha256(data).hexdigest() for name, data in self.data.items()}
        self.write_manifest([("TEST-ROM", self.hashes)])
        self.mountpoint = self.base / "mountpoint"
        self.mountpoint.mkdir()

    def write_manifest(self, sets):
        """Write a schema-2 firmware manifest from [(rom, {name: digest})]."""
        (self.cache / "SHA256.json").write_text(json.dumps({
            "schema": 2,
            "sets": [{"rom": rom, "files": files} for rom, files in sets],
        }))

    def tearDown(self):
        self.temp.cleanup()

    def fake_command(self, argv, **kwargs):
        if argv[0] == "mount":
            self.assertEqual(argv[-2], "/dev/disk/by-partlabel/modem_a")
            self.assertEqual(argv[1:5], ["-t", "vfat", "-o",
                "ro,nodev,nosuid,noexec,codepage=437,iocharset=iso8859-1"])
            image = self.mountpoint / "image"
            image.mkdir()
            for name, value in self.data.items():
                (image / name).write_bytes(value)
        else:
            self.assertEqual(argv, ["umount", str(self.mountpoint)])
            for path in (self.mountpoint / "image").iterdir():
                path.unlink()
            (self.mountpoint / "image").rmdir()
        return SimpleNamespace(returncode=0)

    def provision(self):
        original = tempfile.mkdtemp

        def temporary(*args, **kwargs):
            if kwargs.get("dir") == "/run":
                return str(self.mountpoint)
            return original(*args, **kwargs)

        with patch.object(firmware.tempfile, "mkdtemp", side_effect=temporary), \
             patch.object(firmware.subprocess, "run", side_effect=self.fake_command) as command:
            firmware.provision(self.cache)
            return command.call_args_list

    def test_verified_cache_does_not_mount(self):
        for name, data in self.data.items():
            (self.cache / name).write_bytes(data)
        with patch.object(firmware.subprocess, "run") as command:
            firmware.provision(self.cache)
            command.assert_not_called()

    def test_first_boot_copies_fixed_members_read_only_and_unmounts(self):
        self.assertEqual(len(self.provision()), 2)
        self.assertFalse(self.mountpoint.exists())
        for name, value in self.data.items():
            self.assertEqual((self.cache / name).read_bytes(), value)
            self.assertEqual((self.cache / name).stat().st_mode & 0o777, 0o600)

    def test_bad_stock_leaves_existing_cache_unchanged_and_unmounts(self):
        prior = self.cache / firmware.NAMES[0]
        prior.write_bytes(b"existing-invalid-cache")
        self.data[firmware.NAMES[-1]] = b"wrong stock image"
        # The message names the mismatch as a whole-set decision and shows the
        # two files that distinguish a release, so a report says what to compare.
        with self.assertRaisesRegex(RuntimeError,
                                    "matches none of the 1 known ROM identities"):
            self.provision()
        self.assertFalse(self.mountpoint.exists())
        self.assertEqual(prior.read_bytes(), b"existing-invalid-cache")
        self.assertEqual({path.name for path in self.cache.iterdir()}, {prior.name, "SHA256.json"})

    def test_manifest_cannot_expand_extraction(self):
        # A set has to be exactly the ten known names; an extra entry that would
        # widen what gets copied out of modem_a is refused before any mount.
        self.hashes["../secret"] = "0" * 64
        self.write_manifest([("TEST-ROM", self.hashes)])
        with patch.object(firmware.subprocess, "run") as command:
            with self.assertRaises(ValueError):
                firmware.provision(self.cache)
            command.assert_not_called()

    def test_a_second_identity_is_accepted_as_a_whole_set(self):
        # Two releases, distinguishable only in two files.  A unit carrying the
        # second release must be accepted, and must be accepted as that set.
        other = dict(self.hashes)
        for name in ("fpcliu.mdt", "fpcliu.b08"):
            other[name] = hashlib.sha256(("second " + name).encode()).hexdigest()
        second = {name: ("second " + name).encode() if name in ("fpcliu.mdt", "fpcliu.b08")
                  else self.data[name] for name in firmware.NAMES}
        self.write_manifest([("ROM-1", self.hashes), ("ROM-2", other)])
        for name, data in second.items():
            (self.cache / name).write_bytes(data)
        with patch.object(firmware.subprocess, "run") as command:
            firmware.provision(self.cache)
            command.assert_not_called()          # cache already complete
        self.assertEqual(firmware.matching_identity(self.cache,
                         firmware.checked_hashes(self.cache))[0], "ROM-2")

    def test_a_unit_matching_no_identity_is_refused(self):
        # Newest header from ROM-2 with ROM-1's body: no set describes it.
        other = dict(self.hashes)
        other["fpcliu.mdt"] = hashlib.sha256(b"second fpcliu.mdt").hexdigest()
        other["fpcliu.b08"] = hashlib.sha256(b"second fpcliu.b08").hexdigest()
        self.write_manifest([("ROM-1", self.hashes), ("ROM-2", other)])
        for name, data in self.data.items():
            (self.cache / name).write_bytes(data)
        (self.cache / "fpcliu.mdt").write_bytes(b"second fpcliu.mdt")
        self.assertIsNone(firmware.matching_identity(self.cache,
                          firmware.checked_hashes(self.cache)))

    def test_duplicate_identities_are_refused(self):
        self.write_manifest([("ROM-1", self.hashes), ("ROM-1-copy", self.hashes)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            firmware.checked_hashes(self.cache)

    def test_root_staging_has_no_account_services_or_credentials(self):
        payload = self.base / "payload"
        (payload / "deployment").mkdir(parents=True)
        conf = ROOT / "device/fingerprint/oem/src/fingerprint/libfprint-tod/fprintd-fpc1264-oem.conf"
        (payload / "deployment/fprintd-fpc1264-oem.conf").write_text(conf.read_text())
        root = self.base / "root"
        with patch.object(package.subprocess, "run") as command:
            package.stage_root(payload, root, {"deployment_mode": "installed"})
            command.assert_not_called()
        self.assertFalse((root / "var").exists())
        self.assertFalse((root / "etc/passwd").exists())
        self.assertFalse((root / "usr/share/applications").exists())
        self.assertIn("UMask=0077", (root / "etc/systemd/system/fprintd.service.d/60-liuqin-fpc-oem.conf").read_text())
        unit = (root / "usr/lib/systemd/system/liuqin-fpc-stable-module.service").read_text()
        self.assertNotIn("ssh", unit)
        self.assertNotIn("NetworkManager", unit)
        self.assertTrue((root / "etc/systemd/system/multi-user.target.wants/liuqin-fpc-stable-module.service").is_symlink())


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Run as root in an isolated test container/user namespace")
    unittest.main()
