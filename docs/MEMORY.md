# Memory: where it goes, and what this product removes

This document is the evidence behind the trim lists in `device/configs/`:

| File | Applies to |
|---|---|
| `device/configs/liuqin-memory.config` | kernel (`CONFIG_ZRAM`, zstd, multi-comp) |
| `device/configs/liuqin-root-trim.txt` | root filesystem packages (`[purge]` / `[keep]`) |
| `device/root-overlay/etc/systemd/zram-generator.conf` | swap geometry of the installed system |
| `device/root-overlay/etc/systemd/**` symlinks to `/dev/null` | units masked without removing their package |

## Measured baseline (GNOME Shell, before the Plasma migration)

The desktop is Plasma Mobile since 2026-10-30; this section is the GNOME Shell
measurement that drove the original trim, kept because the purge decisions still
reference it.  The Plasma numbers are in "Plasma Mobile migration" below.

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
`… -> /dev/null` mask in `device/root-overlay` was silently dropped and
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

## Plasma Mobile migration (2026-10-30)

The session was GNOME Shell, then Plasma Mobile ran beside it, and the GNOME and
Phosh sessions were then removed.  What that cost and bought, measured on the
8 GiB unit:

| Quantity | Before | After |
|---|---:|---:|
| Installed packages (`dpkg-query -W`) | 2288 | 2098 |
| `/` used / free (32 GB root) | 13 G / 19 G | 13 G / 20 G |
| `free -m` used after boot | 1390–2267 (see baseline) | 2579 |

The disk figure is net: SDDM, Dolphin, Plasma Camera, Konsole, kcalc and kdialog
were installed while the GNOME Shell stack, Phosh, IBus and the GNOME
documentation/language packs were removed (the trim list's `[purge]` section is
the exact set).

Memory did **not** improve.  Idle per-process RSS after boot, measured with
`ps -eo rss,comm` (RSS, not the PSS the baseline uses, so the two tables are not
directly comparable): `plasmashell` 464 MB, `kwin_wayland` 241, `kded6` 160,
`org_kde_powerdevil` 147, `polkit-kde-authentication-agent` 145,
`kactivitymanagerd` 141, `xdg-desktop-portal` 138, `ksecretd` 136,
`gmenudbusmenuproxy` 132, `xembedsniproxy` 132, `ksmserver` 125, `Xwayland` 98,
`fcitx5` 77.  A PSS measurement and a review of the mask candidates
(`kactivitymanagerd`, `gmenudbusmenuproxy`, `xembedsniproxy`, KWallet vs the
gnome-keyring that is still installed for libsecret) is the next piece of work;
none of them is masked in `device/configs/liuqin-root-trim.txt` yet because
nothing has been measured against the idle baseline after masking.  That pass
has since been done: see "Steady state on Plasma Mobile" below for the numbers
and for the one mask that turned out to end the session.

Two GNOME-only pieces had to move with the session rather than be deleted:

- the stage-1 admission contract pinned `gdm3` and `gnome-shell` as the desktop
  and `display-manager.service -> gdm3.service`; it now pins `sddm`,
  `kwin_wayland`, `plasmashell`, `startplasmamobile` and
  `display-manager.service -> sddm.service` (initramfs/init, native profile);
- the power-key helper drove `org.gnome.ScreenSaver` and Mutter's DPMS.  It now
  drives `org.freedesktop.ScreenSaver` (KWin owns it) and
  `kscreen-doctor --dpms`, and PowerDevil is told `PowerButtonAction=0` so it
  does not act on the same key.  Verified on the tablet: press → locked and
  DPMS off, press → on-locked, press → off, press → on-locked.

## Steady state on Plasma Mobile (measured 2026-10-30)

The question the migration left open was "what does an idle Plasma Mobile
session actually cost, and what can still come out".  This section is that
measurement.  Method: PSS summed per process from `/proc/<pid>/smaps_rollup` and
aggregated by the systemd unit the process belongs to, taken on the tablet with
no application open.  PSS, not RSS, so a library two processes share is not
counted twice.

### What was running and should not have been

The migration replaced the GNOME session and with it every per-account mask the
trim list had accumulated, so the `[mask-user]` section had one entry left
(`baloo_file.desktop`) while the session ran the X11 compatibility layer, the
GNOME-era gvfs backends, two ssh agents, a SPICE guest agent and the KDE wallet
unlock again.  Each was stopped on its own and the drop in total PSS recorded:

| Removed | MB | Why nothing needs it |
|---|---:|---|
| `plasma-xembedsniproxy` | 34 | X11 tray protocol; no X11 client runs here |
| `plasma-gmenudbusmenuproxy` | 29 | exports GTK app menus; Plasma Mobile has no menubar |
| `gvfs-{afc,gphoto2,goa,mtp}-volume-monitor` | 35 | iOS/PTP/MTP/online-accounts hosts, all gone with the GNOME session |
| `ksecretd` + `kwalletd6` | 51 + 31 | `org.freedesktop.secrets` is owned by `gnome-keyring`; the wallet was only ever started by the login unlock |
| `ssh-agent` + `gcr-ssh-agent` | 4 + 3 | two agents, neither with a client |
| `obexd` | 15 | Bluetooth object push; it re-activates itself immediately after `kill` |
| `spice-vdagent` | small | QEMU guest agent on physical hardware; purged, not measured apart |
| `geoclue-demo-agent` | 11 | the sample client of geoclue, not geoclue itself |
| `ubuntu-insights-collect` | 116 peak | Ubuntu telemetry; the unit's own journal line records 116.2 MB peak per boot |

`ksecretd` and `xdg-document-portal` deserve their own note because "stopped"
and "never started" are different measurements:

- `ksecretd` is D-Bus-activated by `kwallet6`'s portal backend, not by a unit.
  Killing it is not enough to know whether it belongs to an idle session; what
  removed it from the baseline was masking the login unlock
  (`pam_kwallet_init.desktop`, `plasma-kwallet-pam.service`).  It stays
  activatable, so an application that really wants the KDE wallet still gets it.
- `xdg-document-portal` and `xdg-permission-store` (26 MB together) are part of
  the sandbox path this project deliberately keeps for Waydroid and flatpak, so
  they stay.  A tablet without either could take them out with two more
  `[mask-user]` lines.

### The mask that ended the session

`plasma-kactivitymanagerd.service` was the largest single candidate (43 MB,
and the tablet has no user interface for activities), and stopping it in a
running session does nothing visible.  Masking it does:

```
plasmashell[8269]: Aborting shell load: The activity manager daemon
                   (kactivitymanagerd) is not running.
```

plasmashell then runs without a shell: 50 MB of RSS, a black panel, and the
on-screen keyboard's toggle button as the only thing on screen.  It is
consequently **not** in the trim list, and `tests/memory-features.py` now
asserts the opposite direction — that the trim list does not mask it — so a
future pass cannot re-add those 43 MB by copying a process table.

### The on-screen keyboard leaked 30 MB an hour

`mytouchinput` was 250 MB resident after five hours of uptime against 48 MB when
freshly started, growing at a measured 8.4 KB/s from an idle session.  The cause
is the poll loop: it does a `wl_display.sync` roundtrip every 20 ms (50/s), the
Go Wayland client registers a new callback proxy per sync in its object map, and
nothing ever unregistered it.  `GODEBUG=gctrace=1` shows the live heap climbing
past the two 7.8 MB frame images it should be holding:

| | live heap after GC | RSS at +200 s | RSS at +5.5 h |
|---|---:|---:|---:|
| before (`roundtrip` never destroys) | 15 MB → 16 MB in 120 s | 53.7 MB | 267 MB |
| after (`callback.Destroy()` on every path) | flat at 15 MB | 47.8 MB | (flat) |

The fix is one call, plus an honest look at the poll rate: the loop also burnt
2.7 % of a core doing nothing, so the idle interval is 50 ms instead of 20 ms.
Measured after: **66 CPU ticks per 60 s instead of 163** (1.1 % of one core) and
RSS flat at 36–48 MB.  The frame-callback architecture described in
device/touchinput/README.md would remove the polling altogether; that is a
rewrite, not a leak fix, and the leak was the part that grew unbounded.

### Transparent huge pages were rounding the whole session up

`kernel/source.json`'s fragment set includes the distro default
`CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS=y`, which offers every anonymous mapping
2 MiB pages whether it asked or not.  On a 6.3 GiB `MemTotal` that is visible
per process (`gvfs-mtp-volume-monitor`: 8.5 MB anonymous, 8 MB of it huge pages;
`polkitd`: 12.9 MB as 12 MB) and 1360 MB of the session was huge-page backed.

Reproducible A/B, same boot, four `plasmashell` restarts alternating the sysfs
policy:

| `transparent_hugepage/enabled` | plasmashell PSS | RSS | of which huge pages |
|---|---:|---:|---:|
| `always`, run 1 | 309 MB | 426 MB | 206 MB |
| `madvise`, run 1 | 263 MB | 380 MB | 126 MB |
| `always`, run 2 | 311 MB | 429 MB | 208 MB |
| `madvise`, run 2 | 264 MB | 381 MB | 126 MB |

`device/root-overlay/etc/tmpfiles.d/90-liuqin-thp.conf` pins `madvise` at every
boot and turns khugepaged's defrag off.  The kernel default is untouched
because changing it means rebuilding the pinned kernel; the tmpfiles write
happens before the session starts, which is the only window that matters.
KWin moves with it for the same reason, though its own number swings with what
the session has drawn (134 MB after a fresh start, 220 MB after opening the
launcher and the task switcher).

### End to end

Same tablet, same unit, no application open, both rows summed over every
process in the session:

| | before this pass | after |
|---|---:|---:|
| total PSS, desktop only (user services excluded) | 1849 MB | 1340–1375 MB |
| `mytouchinput` | 250 MB, growing 8.4 KB/s | 37 MB, flat |
| `plasmashell` | 362 MB | 263–272 MB |
| `kwin_wayland` | 194 MB | 134–220 MB |
| running processes in the session | 100 | 70 |

What is left, and why, on the idle session (top of the PSS list):

| Unit | MB | Why it stays |
|---|---:|---|
| `plasmashell` | 263–272 | the shell; `kactivitymanagerd` keeps the rest |
| `kwin_wayland` | 134–220 | the compositor |
| `fcitx5` | 63 | Chinese input through the on-screen keyboard |
| `kded6` | 60 | kscreen, device automounter, network status, mpris, tray watcher |
| `org_kde_powerdevil` | 57 | brightness, idle policy, battery |
| `polkit-kde-agent` | 54 | privilege dialogs |
| `xdg-desktop-portal*` | 79 | the portal path kept for sandboxed apps |
| `kactivitymanagerd` | 51 | required by plasmashell, see above |
| `ksmserver` | 44 | session management |
| `Xwayland` | 44 | started by KWin itself, not on demand (rejected earlier, still true) |
| `wireplumber` + `pipewire` | 57 | the four speakers |
| `mytouchinput` | 37 | the keyboard, two 7.8 MB frame images plus the runtime |
| `udisks2`, `NetworkManager`, `adbd`, `upowerd`, journald | 100 | the machine itself |

Three things were identified and left alone rather than traded away:
`at-spi` (16 MB, accessibility is not a memory bug), `packagekitd` (16 MB, D-Bus
activated; it is what Plasma's update UI talks to), and the document portal pair
above.  `adb` stays because it is how this device is debugged.

### Trimming Plasma itself: what moved, and what did not

With the session masks done, the remaining Plasma processes were examined one
by one.  Three findings, none of them a large saving:

- **kded6 modules.**  The daemon loads 18 modules at login; seven of them serve
  hardware or behaviour this image does not have (an APN autodetect for the
  modem the trim list removes, a donation nag, a low-disk notifier the storage
  guard replaces, a look-and-feel switcher).  `/etc/xdg/kdedrc` turns them off
  and the set drops to 11, but kded6's own PSS does not move outside its
  restart-to-restart variance (64 MB with everything loaded, 55-75 MB with
  eleven): the daemon is mostly the Qt/KIO/Framework libraries it shares with
  the rest of the session.  Shipped for the behaviour, not for the bytes.
- **KWin effects.**  Blur is not loaded here at all -- Plasma Mobile does not
  use it -- and of the 29 effects KWin has loaded, only `mobiletaskswitcher` is
  ever active.  There is no pool of unused effects to switch off.
- **KWin plugins.**  The compositor maps the keyboard-accessibility plugins
  (`MouseKeys`, `StickyKeys`, `SlowKeys`, `BounceKeys`), `krunnerintegration`,
  `TouchpadShortcuts`, `nightlight`, `screenshot` and `screencast`.  Three of
  those serve hardware this tablet does not have (a touchpad, a physical krunner
  shortcut), but they are small and the code they pull in is shared with
  `libkwin`, so they were left alone.

The measurements also say where the pressure is *not*: the shell (`plasmashell`)
and the compositor are 400-490 MB together and they are what the session needs,
`fcitx5` is 47-63 MB and is the Chinese input method, and the rest is 10-50 MB
daemons.  That is the argument for the zram round below: on this desktop the
remaining headroom is in *how much of it is resident*, not in what is loaded.

Successive `free -m` readings after a boot drift upward as the shell prerenders
(`used` 1493 MB at two minutes, 2156 MB at seventeen with the launcher and the
task switcher having been opened once).  The PSS table above is the number that
means something; `free` counts shared buffers and slab.

### Nothing hands pages back: rounding the idle session into zram

Even after all of the above the kernel gave nothing back on its own: `zram` held
**zero** stored bytes for a whole boot, because handing pages to swap is a
reaction to memory pressure and an idle tablet has none.  The mechanism already
shipped in the kernel (`memory.reclaim` reached mainline in 5.19) does it on
demand, per cgroup, and does not need the desktop to cooperate.  Android solves
the same problem with `madvise(MADV_PAGEOUT)` on background processes.

The write takes an optional swap hint, and the hint is what makes this useful:
`echo "516M swappiness=200" > /sys/fs/cgroup/user.slice/memory.reclaim` asks the
kernel to prefer anonymous pages over page cache.

| Round | asked | session `memory.current` | of which anonymous | of which page cache | zram after |
|---|---:|---:|---:|---:|---:|
| first, 3 min after boot | 516 MB (8 %) | 2320 → 1779 MB | −116 MB | −306 MB | 17 MB |
| periodic, 2 % | 129 MB | 1795 → 1666 MB | −125 MB | −1 MB | 26 MB |

The first round mostly eats page cache because at boot everything the session
holds was touched seconds ago, and page cache is already counted as
`MemAvailable` -- so its real yield is the anonymous part.  The policy is
therefore 4 % / 2 % of `MemTotal`: same anonymous yield, half the cache thrown
away.  The periodic rounds are what actually round up a long session, and by
then there is nothing warm in the target and the kernel takes anonymous memory
almost exclusively (`−125 MB` above, one write, no cache).

Total PSS on that boot went **1484 → 1224 MB** after the boot round (the second
round above took it to 1094 MB), `MemAvailable` 4116 → 4332 MB, for 17-26 MB of
zram and no desktop involvement.

How far it can go, measured by writing larger targets by hand in one session:
reclaiming 840 MB in total took the same session to **660 MB of PSS and 4856 MB
of `MemAvailable`, with 711 MB of anonymous memory in 52 MB of zram (13.6:1)**.
That is the ceiling, not the policy: past the knee the extra rounds stop finding
anonymous pages and start dropping page cache, which buys nothing (page cache is
already `MemAvailable`) and costs a UFS read on the way back.

What it costs, measured by doing the same thing before and after:

| Interactions | before the reclaim | after |
|---|---|---|
| app launcher opened ×4, plasmashell CPU ticks | 56 / 41 / 40 / 47 | 45 / 45 / 39 / 42 |

100 ticks is one second of CPU, so opening the launcher costs ~0.4-0.5 s of
plasmashell CPU either way: the reclaim did not add anything measurable.  Going
past the knee is a different story -- a third 200 MB round in one session added
3 MB to zram but dropped 116 MB of PSS, i.e. it was taking page cache, which
costs a UFS read to get back.

`liuqin-memory-reclaim` is the mechanism: a oneshot service plus a timer
(`OnBootSec=180s`, then every 30 min).  It is conservative on purpose --
`swappiness=200` to prefer anonymous pages, a target sized from `MemTotal`, a
skip while CPU pressure is above 20 %, an `EAGAIN` bisect because the kernel
reclaims what it can and returns failure when it cannot reach the target, and a
silent no-op on a kernel or a layout without swap.  Each round logs what it
took, split into the anonymous and page-cache halves, so the journal is the
measurement rather than the intention:

```
rounded first: session 2320 -> 1779 MB (took 541 MB of 516 asked;
  anon 885 -> 769, file 1390 -> 1084), zram 0 -> 17 MB
rounded later: session 1795 -> 1666 MB (took 129 MB of 129 asked;
  anon 683 -> 558, file 1077 -> 1073), zram 17 -> 26 MB
```

## Reverting

Every step is a package name.

```sh
sudo liuqin-root-trim --dry-run     # what would go
sudo liuqin-root-trim               # apply, then reboot
sudo apt-get install snapd firefox  # put a component back
sudo rm /etc/systemd/user/localsearch-3.service   # unmask the indexer
```

The per-account entries are symlinks and one-line desktop files in the account's
own configuration, so undoing one is a `rm`, and the cache the daemon may have
written comes back on its next start:

```sh
sudo rm /etc/tmpfiles.d/90-liuqin-thp.conf   # let the kernel default apply again
rm ~/.config/systemd/user/plasma-xembedsniproxy.service   # one mask
rm ~/.config/autostart/pam_kwallet_init.desktop           # one autostart hide
systemctl --user daemon-reload                           # after either
```

`/sys/kernel/mm/transparent_hugepage/enabled` can be set back to `always`
without a reboot for an A/B; the tmpfiles file is what decides it after one.

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
| `session-trim` | the trim list names each `[mask-user]` unit and autostart entry; on a live system every account's `~/.config/systemd/user` has the `/dev/null` mask and `~/.config/autostart` the `Hidden=true` override, and — the other direction — `kactivitymanagerd` is *not* masked, because masking it is what rendered the shell black |
| `hugepage-policy` | `/etc/tmpfiles.d/90-liuqin-thp.conf` pins `madvise`; on a live system `/sys/kernel/mm/transparent_hugepage/enabled` reports `[madvise]`, which is the half that proves the write ran rather than that a file exists |
| `idle-reclaim` | the helper, the service and the timer are installed **and** `timers.target.wants` has the link: a timer that is merely installed never runs. Each round logs what it took, split into the anonymous and page-cache halves |
| `kded-modules` | `/etc/xdg/kdedrc` turns off the modules that serve hardware or behaviour the image does not have; the gate asserts the file and the APN module's id, because a misspelled module id is silently ignored rather than rejected |

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
