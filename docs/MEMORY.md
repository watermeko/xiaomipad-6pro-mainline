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

Ubuntu 26.04 ships `firefox` and `chromium-browser` as snap shims, so purging
`snapd` removes the default browser and there is no deb Firefox or Chromium in
the archive. The measured choice on this unit, one page loaded, PSS summed over
every process the browser spawned:

| Browser | Processes | PSS, 1 page | PSS, 5 tabs | Install |
|---|---:|---:|---:|---|
| Google Chrome 156 (arm64 deb) | 12–15 | **421–452 MB** | **532 MB** | vendor deb, 131 MB on disk, dep closure already satisfied |
| GNOME Web / Epiphany 49.2 (WebKitGTK) | 18 | **815 MB** (184 app + 631 in WebKit subprocesses) | not measured | `epiphany-browser`, 2 packages, 3.4 MB |

Both were measured on the same session with the same page.  Chrome is smaller
here, which is the opposite of the usual assumption, and the reason is visible
in the per-process split: WebKitGTK starts a network process plus one
UIProcess/web process per tab, and each one maps the full WebKit and its
JavaScriptCore heap, so five WebKit processes cost more than four Chrome
renderers.  Chrome's numbers are also what a user already expects from a
Chromebook-class machine.

The recommendation for this tablet is therefore **Chrome from Google's arm64
deb**, not because it is small in the abstract but because it is the smaller of
the two available options and it is the one whose sync the user wants:

```sh
# on the tablet, with snapd already purged
curl -LO https://dl.google.com/linux/direct/google-chrome-stable_current_arm64.deb
sudo apt-get install -y ./google-chrome-stable_current_arm64.deb
```

`apt-get install ./file.deb` (not `dpkg -i`) resolves the dependency closure
from the archive. On the measured unit every dependency was already present:
`libcups2t64` stays in the tree even though `cups` is purged, because it is a
library and not the daemon.

Two things to know before relying on it:

- The arm64 build is not in Google's apt repository index for `arm64`; the
  `.deb` is published as a direct download and will not receive updates from
  `apt upgrade`. Re-download it, or add Google's repo for `amd64` only — there
  is no arm64 repository to subscribe to.
- Chrome needs the ozone Wayland platform on this compositor. Launch it once
to confirm; if it starts under Xwayland instead, set
  `--ozone-platform=wayland` in `~/.config/chrome-flags.conf` (Ubuntu's
  `google-chrome-stable` wrapper reads that file).

If a browser is not wanted in the image at all, leave both out: the trim list
removes `snapd` and says nothing about what to install afterwards, so the image
ships without a browser and the user picks one.  No browser is added to a
`[purge]` or `[keep]` section on purpose — the choice is a user decision, not a
product one, and the two candidates differ by 2× the package count and 2× the
memory.

## Further reduction: what else was measured

The trim above brought the idle session to 1406 MB.  A second pass looked for
what was left, measuring every change on the tablet before keeping it.  All of
it is in the `[mask-user]` section of `device/configs/liuqin-root-trim.txt` and
applied by `device/tweaks/apply-root-tweaks.sh --user <account>`.

| Change | Saved | Cost |
|---|---:|---|
| mask `gsd-{wwan,smartcard,sharing,print-notifications,usb-protection}` | 72 MB | hardware this tablet does not have; none is a `Requires` |
| mask `gsd-xsettings` | (in the 72) | only serves X11 clients, and the X11 layer is unused |
| mask `gvfs-{afc,gphoto2,mtp,goa}-volume-monitor` | 36 MB | cannot act as an iOS/PTP/MTP host; goa has no backend left |
| disable `ding@rastersoft.com` | 77 MB | desktop icons; Files and the dock still work |
| disable `ubuntu-appindicators@ubuntu.com` | 99 MB | StatusNotifier tray icons; nothing in this image uses the protocol |
| disable `snapd-prompting`, `snapd-search-provider` | small | they stay ACTIVE for a package manager the trim removes |
| **total** | **~212 MB** | 1406 → **1194 MB** (terminal closed) |

The last two rows were found only after the first were applied: `ding` was
hiding them in the same measurement bucket. The 99 MB indicator host was the
single largest process anywhere in the session, larger than the compositor's
own helper processes — worth knowing before any future assumption that "small"
extensions are small.

Two things were investigated and **rejected**, because the numbers did not
justify the risk:

- **`Xwayland` + `mutter-x11-frames` (117 MB together).** Killing
  `mutter-x11-frames` works and it does not come back. `Xwayland` restarts on
  demand: it is started by Mutter itself when an X11 client connects, and
  `gsd-xsettings` was not the trigger (masking it changed nothing). Nothing in
  this session is an X11 client, so the process is left running by Mutter's own
  startup path rather than by demand. Disabling it needs a Mutter experimental
  feature that is not upstream-stable, so it stays.
- **`ibus` (69 MB).** This is the Chinese input method. A tablet with
  `screen-keyboard-enabled=true` and no hardware keyboard needs it, so it is
  not a candidate at all.

What is left, and why it stays:

| Group | MB | Why |
|---|---:|---|
| `other` (~95 processes) | 291 | udisksd, NetworkManager, polkitd, iio-sensor-proxy, adbd, journald, gdm3, systemd itself |
| `gnome-shell` | 311 | the compositor and the desktop |
| X11 compatibility | 121 | see above |
| `gsd-*` (11 left) | 111 | power, media keys, keyboard, rfkill, sound, colour, datetime, a11y, screensaver, disk-utility, housekeeping |
| `xdg-desktop-portal*` | 113 | Flatpak, Waydroid and sandboxed apps route through these |
| `ibus` | 71 | Chinese input |
| `audio` | 67 | PipeWire + WirePlumber for four speakers |
| `gjs` (2 left) | 56 | the shell's notification and screensaver helpers |
| `gvfs` | 55 | trash, udisks2 volume monitor, fuse, metadata |

### Verification after the second pass

The masks and the dconf key were confirmed to survive a reboot: `gsd-*` went
from 18 to 11 processes, `gvfs-*-volume-monitor` from 5 to 1 (only udisks2), all
four extensions reported `INITIALIZED` (the state of one that is installed but
not running), and the session came up normally with the power key, volume keys,
the magnetic keyboard, rfkill, auto-rotation and the disk mounts still working.

Getting the extension list to survive took two fixes, both caught by rebooting
rather than by reading the code: `apply-root-tweaks.sh` assumed root and failed
as an ordinary account (the session unit has to skip the system half, which is
what `--user-only` is for), and a per-account run cannot write `/etc/dconf`, so
the system-wide key stays the package's job while the session unit only masks
units. `liuqin-session-tweaks.service` is the unit that does the per-account
half on first login, which is what covers the account gnome-initial-setup
creates after a fresh install.

### The dock and Files were listing the Android partitions

Cutting the gvfs volume monitors down to udisks2 removed the network and media
sources, but it left the one that mattered on this device. The stock layout has
twelve partitions on the internal UFS that carry a real filesystem - `metadata`,
`persist`, `persistbak`, `dsp_a`, `dsp_b`, `vm-bootsys_a`, `vm-bootsys_b`
(ext4), `logfs`, `modem_a`, `modem_b`, `bluetooth_a`, `bluetooth_b` (vfat) and
`cust` (erofs) - and udisks2 offered every one of them as a mountable volume.
The dock and Files showed them as anonymous `31 MB Volume`, `67 MB Volume`,
`275 MB Volume`, `4.2 MB Volume` and `168 MB Volume` entries, plus two labelled
`dsp` and `LOGFS`.

They are firmware, not storage: mounting one read-write is a good way to lose a
partition the bootloader needs. `90-liuqin-hide-android-volumes.rules` sets
`UDISKS_IGNORE=1` on them, which makes udisks2 skip the device entirely, so it
disappears from udisks, from the GVfs volume monitor, and therefore from the
dock and the Files sidebar.

The match is deliberately narrow: it keys on the internal UFS controller in
`DEVPATH` (`*/1d84000.ufshc/*`) rather than on `sd*` names, because the internal
disks are `sda`..`sdf` here and a plain `sd[a-z][0-9]*` pattern would also hide
a USB stick plugged into the port. `linux_root` and `linux_home` are excluded so
the system's own partitions stay visible. Device nodes are untouched - the
fingerprint runtime and the boot tooling open `/dev/disk/by-partlabel/*`
directly and never go through udisks.

Measured with the same monitor the desktop reads: the volume list went from 14
entries to none. `tests/memory-features.py` gained a `volume-hiding` feature that
checks the rule's contents and, on a live system, the udev database for all
fourteen partitions plus the two that must stay visible - a rule file proves
intent, the database proves it took effect.

### The one thing that would save more

`zram` is idle in this measurement (`mm_stat` shows no stored pages) because a
fresh boot has nothing to reclaim yet. Its value is not the idle number — it is
that a browser allocation no longer ends the session. Beyond that, the next
real step is a lighter session (a wlroots compositor instead of
`gnome-shell` + `gsd` + `gjs`), which the notes in
[Memory notes](../docs/MEMORY.md#is-a-non-gnome-desktop-worth-it) already size
at ~600 MB — for the cost of the GNOME integration this project owns.

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

### Kernel rebuild and deployment

The kernel was rebuilt and flashed, and zram is live on the tablet:

| | Result |
|---|---|
| build | `tools/build-liuqin-kernel.py` against the pinned commit, `aarch64-linux-gnu-gcc-13`, `.config` hash `fa931ca5…` matching the lock |
| module set | 481 modules, exactly the set the running system has; only the build-id bytes differ |
| release | `6.17.0-rc1-gfe81794b5e1b`, unchanged, so the root filesystem still matches |
| deploy | `tools/deploy-liuqin-boot.py`: the device-tested bundle's ramdisk and DTB, kernel replaced, written to `boot_a` whole, read back and compared |
| `/sys/block/zram0` | present, 3221225472 bytes (3 GiB), `comp_algorithm` = `[zstd]`, swap priority 100 |
| reclaim | a Python process allocating 6720 MiB of anonymous memory (more than `MemTotal`) ran to completion; `zram0` held 320 MB of swap at a 19.24:1 compression ratio and the session stayed alive |
| `systemd-oomd` | active, and now has something to reclaim instead of only something to kill |

The configuration replay and the `.config` diff for the kernel were reproduced
on the development host. The post-trim figures above are measurements of a
hand-applied trim on the installed 0.6.0 root, not of a rebuilt image; the zram
figures are from the rebuilt and flashed kernel.

### Does a fresh install get all of this?

That is the question the gate exists to answer, and the answer is now checked
rather than assumed.  `tests/memory-features.py` names each customisation and
the evidence for it, across three surfaces:

| Feature | Proven by |
|---|---|
| `zram-swap` | `CONFIG_ZRAM`/`ZSMALLOC`/`ZRAM_BACKEND_ZSTD`/`ZRAM_DEF_COMP_ZSTD` in the generated `.config`, `CONFIG_ZSWAP` off, `/etc/systemd/zram-generator.conf` selecting zstd, `systemd-zram-generator` installed |
| `rootfs-trim` | the trim list and `liuqin-root-trim` installed, `/snap`, `/var/lib/snapd` and `snap-confine` gone, the purged packages absent, the `[keep]` packages and the four sensor libraries present |
| `unit-masks` | for every masked unit that `usr/lib/systemd` still ships, `etc/systemd` has a `/dev/null` symlink. Conditional on purpose: masking a unit whose package was purged proves nothing |

It runs in three places:

- **as a build stage.** `tools/build-liuqin-image.py` runs it as `--stage
  features`, between `manifest` and `boot`, against the assembled root and its
  real dpkg database. A customisation that stopped landing fails the image
  build, not the release.
- **in CI.** `.github/workflows/checks.yml` reads the same feature table and
  refuses a pull request whose kernel fragments or trim list no longer supply a
  feature symbol or a `[keep]` package.
- **on a tablet.** The file is portable; push it and run it against `/`:
  `adb -s liuqin push tests/memory-features.py /tmp/` then
  `adb -s liuqin shell 'python3 /tmp/memory-features.py --config /proc/config.gz --root / --packages'`.
  Run it as root. The fingerprint cache is `0600` files inside a `0700`
  directory, so an ordinary account cannot stat them; the gate now reports
  `cannot be inspected without root` for that rather than calling the files
  missing, which is what it used to do and what made a permission problem look
  like a regression.
  On the unit this work was measured on all five features pass, including
  `volume-hiding`, whose udev half is only checked when `--root` is the running
  system.
  Both come from the shipped list, so a bundle built from this tree has them;
  the tablet in front of us was trimmed by hand from an older image.

`bundle.json` carries `zram_swap`, `rootfs_trim` and `unit_masks` so
`install-liuqin.py` prints what a bundle actually contains before it writes
anything — the 0.6.0 bundle on the release page does not have them, and an old
bundle must not read as if it did.

Deploying again, after any kernel change:

```sh
python3 tools/build-liuqin-kernel.py --source ../linux-sm8450-liuqin --out out/kernel
python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel --dry-run   # build + verify only
python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel             # write, verify, reboot
```

`deploy-liuqin-boot.py` saves the live `boot_a` under `backups/liuqin-boot/`
before writing and refuses to run when the kernel build does not match
`kernel/source.json`. It writes nothing but `boot_a`: `boot_b` keeps the
bootloader's fallback copy, which is the way back if an image does not load.
