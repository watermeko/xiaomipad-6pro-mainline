# Root filesystem tweaks

This directory owns the *application* of this project's root filesystem
customisations.  The policy itself lives in one place each:

| File | Owner |
|---|---|
| `device/configs/liuqin-root-trim.txt` | which packages the product removes and which it may not lose |
| `device/root-overlay/etc/systemd/zram-generator.conf` | the zram geometry |
| `device/root-overlay/usr/local/sbin/liuqin-root-trim` | the command that applies the trim on an installed system |
| `device/configs/liuqin-memory.config` | the kernel fragment that gives the kernel zram at all |

`apply-root-tweaks.sh` is the single implementation that installs them, and it
has two callers:

- **the installer.**  `tools/lib/install-root.sh` runs it against
  `/mnt/install/native-root` immediately after untarring the root archive, so a
  fresh install carries the zram configuration and the masks before it first
  boots.  It passes `--no-purge`: the installer's BusyBox userland has no dpkg,
  and the archive is already trimmed by the image build.
- **the incremental package.**  `liuqin-memory-tweaks` runs it with
  `--no-purge` on `/` from its postinst, which is how a tablet installed from an
  older bundle gets the same files without a reflash.

The per-account section (`[mask-user]`) speaks two entry kinds:

| Entry | Effect |
|---|---|
| `unit:<unit>` | symlink the unit to `/dev/null` in the account's `systemd --user` instance |
| `autostart:<file>` | write `~/.config/autostart/<file>` with `Hidden=true` |

Both are idempotent and both are applied by `liuqin-session-tweaks.service`,
which runs once per login.  The GNOME-era kinds (`gsd:`, `gvfs:`,
`extension:`, and the `[mask-user-phosh]` section) were removed with the session:
a mask is only useful for a unit the desktop actually starts.

`stage-payload.sh` copies the three policy files into a payload directory
beside the script, verifying each staged copy is byte-identical to its source.
Both callers stage from it, so there is no second copy of the policy to drift.

`tools/build-liuqin-memory-tweaks.py` packages the result together with a boot
image whose only difference from the release bundle is the kernel.

Check either caller with the same gate:

```sh
python3 tests/memory-features.py --config out/kernel/.config --root out/root/rootfs --packages
```
