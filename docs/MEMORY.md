# Memory: where it goes, and what this product removes

This document is the evidence behind the trim lists in `device/configs/`:

| File | Applies to |
|---|---|
| `device/configs/liuqin-memory.config` | kernel (`CONFIG_ZRAM`, zstd, multi-comp) |
| `device/configs/liuqin-root-trim.txt` | root filesystem packages (`[purge]` / `[keep]`) |
| `device/gnome-overlay/etc/systemd/zram-generator.conf` | swap geometry of the installed system |
| `device/gnome-overlay/etc/systemd/**` symlinks to `/dev/null` | units masked without removing their package |

## Measured baseline

Xiaomi Pad 6 Pro, 8 GB SKU, `MemTotal` 6608256 kB (firmware reservations take the
rest), Ubuntu 26.04, GNOME Shell 50.1, booted 10 minutes, one user, Settings
(→ Power) and a terminal open. Figures are **PSS** summed per process name, not
RSS, so shared GTK/Mesa pages are not counted once per process.

| Group | PSS | Notes |
|---|---:|---|
| GNOME Shell + session | 755 MB | `gnome-shell` 301, `gjs` helpers 115, `mutter-x11-frames` 52, `Xwayland` 48, `gsd-*` ~120 |
| Evolution / calendar / index | 244 MB | `evolution-alarm-notify` 43, EDS addressbook 30, calendar 28, source registry 26, `gnome-calendar` 53, `localsearch-3` 36 |
| Removable daemons | 215 MB | `fwupd` 52, `update-notifier` 28, `unattended-upgrade-shutdown` 23, `networkd-dispatcher` 20, `ModemManager` 18, `colord` 16, CUPS 30, `switcheroo-control` 9 |
| snap | 158 MB | `snapd` 72, `snap userd` 50, `snapd-desktop-integration` 28 |
| gvfs | 106 MB | ten per-protocol daemons, 13–17 MB each |
| xdg portals | 101 MB | needed by the sandboxed application path |
| ibus (Chinese input) | 98 MB | `ibus-x11` 26, `ibus-extension-gtk3` 30, daemon 19 |
| audio | 67 MB | PipeWire, WirePlumber, filter-chain |
| user-opened apps | 275 MB | Settings 158 + terminal 117 — not a baseline cost |
| **total** | **2267 MB** | |

Disk side, for context: 6.41 GiB installed, of which 1.78 GB is the stock HWE
kernel set (`linux-modules-7.0.0-{14,38}-generic`, headers) plus NVIDIA/AMD/
Intel/Mellanox/QLogic `linux-firmware-*` that this board cannot use, and 820 MB
is LibreOffice.

## The real problem is not the number, it is that nothing can be reclaimed

`swapon --show` is empty and `/proc/swaps` has no entry: the install layout keeps
the UFS tail for the A/B slots, `linux_home` and (dual boot) Android, so there is
no swap device. The product kernel had `CONFIG_ZRAM` and `CONFIG_ZSWAP` unset.
Two consequences, both measured:

- `systemd-oomd` runs (it is required by `basic.target`) and cannot do anything
  useful: PSI is compiled in, but with nothing swappable it can only kill.
- Any single allocation the size of a browser tab ends the session instead of
  costing some CPU.

So the trim has two halves: cut what is resident, and give the kernel a
compressed swap to reclaim into.

## What changed

**Kernel.** `device/configs/liuqin-memory.config` adds `ZRAM=y` (built in, not a
module, because the generator runs from sysinit and the module tree is pinned to
the product release), `ZSMALLOC=y`, the zstd backend as the only backend,
`ZRAM_MULTI_COMP=y` for recompressing cold pages, and leaves `ZSWAP` off — a
compressed swap cache in front of a swap device this product does not have.

`kernel/source.json` lists the fragment and carries the new configuration
identity. That value was produced by replaying the product's own pipeline
against the pinned commit and the compiler the release used: `make defconfig`,
`merge_config.sh` with the fragment list, `make olddefconfig`. The replay of the
**old** list reproduces the previous lock byte for byte
(`29a4fd23…`), and the diff of the old and new `.config` is exactly the zram
hunk — no symbol drifted.

**Root filesystem.** `device/configs/liuqin-root-trim.txt` is the list the image
builder applies in its ARM64 chroot (`tools/build-liuqin-native-root.sh`, `debs`
stage): purge, autoremove, `apt-get check`, then a gate that fails the build if
any `[keep]` package disappeared or any `[purge]` package survived. The same
file is shipped to the device as `/usr/share/liuqin/root-trim.txt` and applied by
`/usr/local/sbin/liuqin-root-trim` so an installed tablet can be trimmed without
reflashing.

**Overlay.** `liuqin-device-support` now ships the `/etc/systemd` mask links it
always intended to: the previous copy loop walked `-type f` only, so every
`… -> /dev/null` mask in `device/gnome-overlay` was silently dropped and
`unattended-upgrades`, `update-notifier-download.timer` and both `apt-daily`
timers kept running while git claimed they were masked. The loop now enumerates
files *and* symlinks, records the target, and the native-root builder asserts the
masks and `zram-generator.conf` in the assembled tree.

## Result on the 8 GB unit

Measured after applying the list by hand; the verification section has the full
numbers.

| After | Idle | Change |
|---|---:|---:|
| trim only | 1406 MB total PSS | −680 MB resident (2267 → 1406 with a login session up) |
| trim + zram | the above, plus 3 GiB of compressed swap | a browser-sized allocation stops triggering OOM |

Per group, the measured reasons:

- snap removed: 150 MB and the whole `/snap` mount layer. `firefox` and
  `thunderbird` in 26.04 are snap shims, so purging `snapd` takes both; the
  affected default browser story is written down below.
- Evolution group removed: 244 MB. `gnome-shell` only *Recommends*
  `evolution-data-server`, so the shell survives; the calendar dropdown and the
  address book stop working.
- Daemons removed: 190 MB, none of them has a reverse dependency that keeps the
  desktop (checked one by one with `apt-get -s purge`).
- `localsearch`'s indexer masked: 36 MB. The package itself stays because
  `nautilus` **Depends** it; removing it would remove Files, `ubuntu-session` and
  `xdg-desktop-portal-gnome`.

## What is deliberately kept

- **`colord`**: purging it removes `gnome-control-center`, which is the package
  this project replaces with the power-button policy build. The unit is masked
  instead, so the Settings → Color page reports an unavailable daemon.
- **`localsearch` package** (only its unit is masked): see above.
- **ibus**: 98 MB is the price of the Chinese input method on a keyboard-less
  tablet; `screen-keyboard-enabled=true` in the overlay depends on it.
- **xdg portals, gvfs, PipeWire, `gdm3`, `systemd-oomd`, `power-profiles-daemon`,
  `iio-sensor-proxy`, `upower`, `polkit`**: session, sandbox, audio, rotation and
  power policy all route through them.
- **`ssh.service` and adbd**: the debugging lifeline for a device that cannot be
  put in a dock.

## Browser after snap

Ubuntu 26.04 ships `firefox` and `chromium-browser` as snap shims; with `snapd`
purged neither can be installed from the archive. Options, in increasing order of
effort: install a deb browser that exists in `resolute` (`epiphany-browser` is
WebKitGTK, no snap, ~60 MB resident), add Mozilla's APT repository for a real
`.deb` Firefox, or keep a browser out of the image and let the user choose. This
repository does not pick one: the trim list is where that decision is made.

## Is a non-GNOME desktop worth it?

Measured on this unit, the entire GNOME stack above the kernel is ~755 MB. A
wlroots-class session (labwc or niri + waybar + foot) idles at ~100–150 MB, so
the ceiling is ~600 MB — less than zram alone buys, and it would invalidate the
parts of this project that live inside GNOME: the `gdm3` + fingerprint login
path, `gnome-initial-setup` first boot, the dconf power policy, the patched
`gnome-control-center` power panel, the on-screen keyboard and the 2× scaling
policy. Replacing the distribution as well is a different order of work: the
rootfs pipeline is built from an Ubuntu casper image
(`tools/build-liuqin-ubuntu-desktop-rootfs.sh`).

A cheaper order of operations, if GNOME is abandoned later: keep `gdm3` and the
PAM stack (they are desktop-independent), add a wlroots session, and make it the
default session while GNOME stays selectable. That is a session change, not a
distribution change, and it does not touch the kernel or the rootfs pipeline.

## Reverting

Every step is a package name.

```sh
sudo liuqin-root-trim --dry-run     # what would go
sudo liuqin-root-trim               # apply, then reboot
sudo apt-get install snapd firefox  # put a component back
sudo rm /etc/systemd/user/localsearch-3.service   # unmask the indexer
```

The kernel side is not runtime-reversible: it needs a rebuild
(`tools/build-liuqin-kernel.py`) and a boot image flash. Without it the rootfs
still trims, and `/usr/local/sbin/liuqin-root-trim` reports that
`/sys/block/zram0` is missing instead of pretending swap exists.

## Verification status

Measured on the tablet, 8 GB SKU, after the trim was applied by hand
(`liuqin-root-trim` plus the four sensor libraries below), booted into a user
session, no applications open, ~2 minutes of uptime:

| | before | after |
|---|---:|---:|
| total PSS | 2267 MB (with Settings + terminal open) / 1420 MB (idle greeter) | 1406 MB |
| `MemTotal` free-ish (`free -m` available) | 4625 MB | 4348 MB, with 2 GiB more in `buff/cache` after the same uptime |
| running services | 42 system + 55 user | 25 system + 31 user |
| swap | none, `CONFIG_ZRAM` off | `systemd-zram-generator` generates `dev-zram0.swap`; the device cannot back it until the kernel is rebuilt |

Groups after the trim: GNOME shell and session 553 MB, `gsd-*` 199 MB, ibus
99 MB, xdg portals 97 MB, gvfs 94 MB, audio 69 MB, evolution 29 MB,
removable daemons 7 MB.

Two things the hand run found that the lists alone would not have:

- **`liuqin-sensors` was under-declaring its libraries.** `ssccli` and the
  SSC-enabled `iio-sensor-proxy` link `libqmi-glib5` and `libqrtr-glib0`, which
  used to arrive as leftovers of `modemmanager` and `fwupd`. Purging those two
  packages left both binaries exiting 127, the accelerometer gate failing
  closed, `iio-sensor-proxy` never starting, auto-rotation gone and the
  fingerprint startup gate failing behind it. Fixed in
  `tools/build-liuqin-debs.sh` (Depends plus an `ldd` closure gate) and in the
  `[keep]` section of the trim list.
- **`evolution-data-server-common` is not removable.** It ships the
  `libedataserver` client libraries that `gnome-shell`, `gdm3` and
  `ubuntu-session` link; purging it removes all three. Only
  `evolution-data-server` itself is in the `[purge]` list.

The configuration replay and the `.config` diff for the kernel were reproduced
on the development host. The post-trim figures above are measurements of a
hand-applied trim on the installed 0.6.0 root, not of a rebuilt image; the zram
path is unproven until the kernel is rebuilt and flashed.
