# Ubuntu for Xiaomi Pad 6 Pro

Run Ubuntu 26.04 on the Xiaomi Pad 6 Pro, with the Plasma Mobile desktop and a device-adapted kernel based on upstream Linux. [中文](README.zh-CN.md)

## Latest Release and Recent Updates

**[v0.6.0](https://github.com/yzddmr6/xiaomipad-6pro-mainline/releases/tag/v0.6.0)** is now a full release. Native fingerprint support, DP output and dual-boot fixes are included in one installation bundle. Installation, initial setup and user acceptance passed on the known 256 GB test unit.

Main updates since the initial open-source release:

- **Native fingerprint login**: enroll with `fprintd-enroll` (or the Users page of Plasma's System Settings), then unlock the screen or log in after boot. Same-finger acceptance and other-finger rejection are verified; currently limited to the first account and one finger.
- **DP external display**: external picture, internal-display recovery after unplugging and USB recovery on reconnect are verified. Other adapters, DP audio and high refresh rates remain unverified.
- **Dual boot and camera**: added an installation layout that preserves Android and a KernelSU module to return to Ubuntu, fixed startup failures caused by stock firmware, added experimental rear-camera support and fixed the speakers. See the installation notes below for dual-boot validation scope and the support table for camera limitations.
- **Input, recording and charging**: fixed the magnetic keyboard touchpad, added touch-panel variants, USB OTG, single-microphone recording and charging authentication. The kernel configuration required by Waydroid is included; Waydroid remains experimental without end-to-end device acceptance.

## 📮 Follow & Discuss

Progress updates, usage tips and AI discussions (primarily in Chinese) are published here first — issue feedback is welcome.

| WeChat: 熵减矩阵 | Xiaohongshu: yzddmr6 |
|:---:|:---:|
| <img src="docs/assets/gzh-qr.png" width="200" alt="WeChat: 熵减矩阵"> | <img src="docs/assets/xhs-qr.jpg" width="200" alt="Xiaohongshu: yzddmr6"> |
| Updates · Tips · AI talks | Sharing · Feedback |

## ⚠️ Read Before Installing

This project is only for the **Xiaomi Pad 6 Pro (liuqin, SM8475)**. Other Xiaomi Pad models are not compatible.

- **Data loss**: unlocking the bootloader and performing an initial installation erase user data. Back up your files first.
- **Storage and layout**: installation has been tested on one known **256 GB partition layout**, not every 256 GB device. Other capacities and modified partition layouts are unverified and unsupported. The installer repartitions the tail of the disk. In the dual-boot layout both systems boot from slot A; the Linux-only layout places Ubuntu in slot B. Do not bypass the checks.
- **Validation scope**: installation and initial setup, rotation, touch, the magnetic keyboard (including its touchpad), speakers, single-microphone recording, USB OTG host mode (wired mouse), native fingerprint login, DP output and suspend to deep sleep have device-test evidence. See the table below for each feature's scope; not every combination is retested with every release. Android recovery still requires separate device validation.
- **Installation layout**: the installer offers a Linux-only layout and a dual-boot layout that keeps stock Android. Both systems use slot A and switching writes the other system's image into `boot_a`. The known 256 GB unit has passed slot-A Ubuntu startup, Android's first boot after restoring stock firmware, and a return to Ubuntu through the KernelSU module script under a debug Android boot. The Manager WebUI button, automatic KernelSU activation under an ordinary Android boot, and the Linux-only layout remain unverified. See the [installation steps](docs/INSTALL-TESTING.md).
- **Recovery preparation**: obtain the matching stock firmware and read the [data and recovery instructions](docs/FLASHING.md#data-and-recovery) before installing.
- **Hardware limitations**: some features are incomplete. Review the hardware support table below.

Flashing an incorrect boot image or partition can prevent the tablet from starting. Follow the installation guide and keep your backups.
Factory calibration and device addresses must come from the same tablet; never copy them between devices.

## 🚀 Getting Started

Use a complete installation bundle from [GitHub Releases](https://github.com/yzddmr6/xiaomipad-6pro-mainline/releases). Do not mix files from different versions.

| I want to | Read |
|---|---|
| Install Ubuntu | [Installation guide](docs/FLASHING.md) |
| Build the kernel and device components | [Build guide](docs/BUILD.md) |
| Restore Android | [Data and recovery instructions](docs/FLASHING.md#data-and-recovery) |
| Reclaim memory (zram, package trim) | [Memory tweaks](#memory-tweaks), then [Memory notes](docs/MEMORY.md) |
| Make the tablet sleep (and wake it) | [Suspend and resume](docs/SUSPEND.md) |
| See the tray icons (Tailscale, Telegram, ...) | [System tray](#system-tray) |

Prebuilt installation bundles include matching boot and root filesystem images, installation tools and checksums.

## Hardware Support

This describes hardware support and known limitations for Xiaomi Pad 6 Pro (liuqin).
Component identities come from confirmed board information
and device trees; other batches, capacities and accessory combinations are not implied tested.

✅ Working · 🟡 Partial · ❌ Unsupported · 🧪 Unverified

Verified features at a glance; see the table below for the scope of each:

- ✅ CPU · ✅ GPU desktop acceleration · ✅ Internal storage · ✅ 120 Hz display · ✅ Touch · ✅ Manual brightness
- ✅ Magnetic keyboard and touchpad · ✅ Native fingerprint login · ✅ Auto-rotation · ✅ Power and volume keys
- ✅ Wi-Fi · ✅ Bluetooth · ✅ USB data transfer · ✅ USB OTG (wired mouse) · ✅ DP output (tested combination)
- ✅ Four speakers · ✅ Single-microphone recording · ✅ H.264 hardware decoding (userspace) · ✅ Rear-camera preview (experimental) · ✅ Battery reporting and basic charging
- 🟡 Suspend to deep sleep (enters, resumes, one wake in three unexplained) · 🟡 Cover-close sleep (configured, not exercised)

### Platform, Display and Input

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| SoC / CPU | Qualcomm Snapdragon 8+ Gen 1 (SM8475), ARM64 | ✅ Working | Kernel boot and Ubuntu desktop; not all power states are validated |
| GPU / compositing | Adreno 730 / Freedreno / Mesa | ✅ Working | Desktop acceleration; some applications need rendering workarounds |
| Internal storage | UFS / ext4 | ✅ Working | Persistent system and packages on `linux_root` and `linux_home`; installer targets the known 256 GB layout only |
| Display | Novatek NT36532 / dual DSI / DSC | ✅ Working | 2880 x 1800 at 120 Hz; other refresh rates are not individually tested |
| Manual brightness | Kinetic KTZ8866 backlight | ✅ Working | Backlight and manual brightness adjustment |
| Touchscreen | Novatek NT36532 / SPI (CSOT or TM panel) | ✅ Working | Driver selects the firmware by panel module; touch input, swipes and gestures |
| Magnetic keyboard | Nanosic WN8030 | ✅ Working | Character and volume keys, touchpad, reattachment; suspend recovery not fully covered |
| Fingerprint | FPC1264 / libfprint TOD / fprintd | ✅ Working | Native Settings enrollment, same-finger acceptance/other-finger rejection, lock-screen unlock and fingerprint login after ordinary reboot; currently limited to the first account (UID 1000) and one finger, see [fingerprint guide](docs/FINGERPRINT.md) |
| Stylus | NVTCapacitivePen input interface | 🧪 Unverified | Coordinates, pressure, buttons and input after wake not tested |
| Hall switches | GPIO / SW_LID / SW_TABLET_MODE | 🟡 Partial | Switch states are readable and the lid switch is a wakeup source, so opening the cover wakes the tablet; the desktop's lid action (PowerDevil `LidAction=Sleep`) is configured but could not be exercised without the folio cover |

### Wireless and USB

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Wi-Fi 2.4 GHz | Qualcomm QCA6490 / ath11k | ✅ Working | Wireless connection and everyday networking |
| Wi-Fi 5 GHz | QCA6490, supported as WCN6855 family | ✅ Working | 5 GHz connections verified; no peak-throughput claim |
| Wi-Fi hotspot / AP | NetworkManager / ath11k | 🧪 Unverified | Confirmed networking scope is client mode |
| Bluetooth | QCA6490 / hci_qca / BlueZ | ✅ Working | Everyday Bluetooth functionality is usable |
| USB 2.0 device mode | Synopsys DWC3 / NXP eUSB2 repeater | ✅ Working | USB NCM networking and transfer; High-Speed device mode |
| USB reconnect after charging | USB-C / USB gadget | 🟡 Partial | Since v0.1.1 the UCSI typec controller negotiates automatically; a dedicated retest is pending |
| USB 3.x SuperSpeed | USB controller / PHY | 🧪 Unverified | Since v0.1.1 the SM8475 PHY tables and controller are in place; SuperSpeed peripheral enumeration untested |
| USB OTG / host mode | USB-C data-role switching | ✅ Working | Since v0.1.1 UCSI negotiates the role automatically; wired mouse validated, USB drives and docks pending |
| USB-C external display | DisplayPort Alt Mode / FSA4480 | ✅ Working | External picture, internal-display recovery after unplugging, and USB recovery when reconnected to the computer are verified with the tested monitor/adapter combination; other docks, DP audio and high refresh rates remain unverified |

### Audio, Video and Sensors

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Four speakers | 4 × Cirrus Logic CS35L41 / AudioReach | ✅ Working | Stereo playback and volume control with per-device calibration; tuning continues |
| Internal microphone | WCD938x AMIC1 over SoundWire → LPASS TX macro → ADSP codec DMA | ✅ Working | Mono 48 kHz recording available since v0.3.0 and validated on hardware; the other three mics and noise suppression are not wired yet |
| H.264 hardware decoding | Qualcomm Iris2 / V4L2 | ✅ Working | Userspace decoding verified; not evidence of browser integration |
| Other decoding formats | Iris / V4L2 | 🧪 Unverified | HEVC, VP9 and other formats not individually validated |
| Browser hardware decoding | Browser / V4L2 integration | 🧪 Unverified | Video playback alone does not prove hardware decoding |
| Hardware encoding | Qualcomm video engine | 🧪 Unverified | Hardware encoding workflows not tested |
| Rear camera | S5KJN1 / Qualcomm CAMSS / libcamera software ISP | 🟡 Partial | Preview, photos and video in the Camera app; software image processing, no autofocus, video stutters. See [Camera](docs/CAMERA.md) |
| Front camera | Camera sensor / CAMSS | ❌ Unsupported | Not enabled or validated |
| Accelerometer / auto-rotation | SLPI / SSC / iio-sensor-proxy | ✅ Working | First boot, login screen, desktop rotation and magnetic-keyboard landscape use |
| Gyroscope / magnetometer | SSC sensor path | 🧪 Unverified | Application-usable measurements not confirmed by accelerometer support |
| Ambient light sensor | SSC light-sensor path | 🧪 Unverified | Real light measurements not fully validated |
| Automatic brightness | Desktop brightness policy | ❌ Unsupported | Automatic brightness control not integrated |

### Power and Time

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Power / volume keys | Qualcomm PMIC / GPIO input | ✅ Working | Screen on/off, power menu and volume; native lock-screen authentication verified |
| Battery / basic charging | qcom_battmgr / UPower | ✅ Working | Capacity reporting, charging state and basic wall charging |
| Computer USB power | USB power path | 🟡 Partial | Limited supply power; heavy workloads may still discharge the battery |
| Xiaomi proprietary fast charging | Vendor charging protocol | 🟡 Partial | Charger authentication integrated; battery authentication verified and PD adapters reach 9 V / 2 A. MiPPS and standard PPS fast charging await adapter validation |
| Charging while powered off | Boot-stage charging hold | 🟡 Partial | No complete charging display; use a long power-key press to boot while charging |
| Suspend / resume | PSCI deep sleep / PowerDevil | 🟡 Partial | `deep` is the selected sleep state: a suspend offlines every non-boot CPU and hands the SoC to the firmware, and the resume brings touch, pen, keyboard, touchpad, Wi-Fi and the panel back. `liuqin-sleep-guard` puts an unattended wake back to sleep, so the tablet keeps returning to sleep instead of staying awake after the first one. Measured on battery: **102 mA (1.36 %/h)** with the shipped policy against **216 mA (2.88 %/h)** awake with the panel dark. Partial because the platform still stops at the APSS sleep level -- `cxsd`, `ddr` and `aosd` stay at zero after every suspend, and the five Linux-side causes that could explain it (every subsystem stopped, the USB PHY, the AOP prevent votes, the SMP2P sleep state bit and the CX sleep-set vote) have all been eliminated by measurement, so a real deep sleep needs firmware work. About one suspend in three also ends early with no interrupt attributed. See [Suspend and resume](docs/SUSPEND.md) |
| RTC / offline time retention | Qualcomm PMK8350 RTC | 🧪 Unverified | Network time synchronization works; offline writes and power-loss retention are not guaranteed |

## Memory Tweaks

The v0.6.0 bundle on the [releases page](https://github.com/yzddmr6/xiaomipad-6pro-mainline/releases)
predates this work: installed as-is, it keeps the whole Ubuntu desktop resident,
runs `snapd`, `fwupd`, CUPS and the Evolution daemons, and has **no swap at all** —
the install layout leaves no room for a swap partition, and the product kernel had
`CONFIG_ZRAM` unset, so `systemd-oomd` could only kill. Measured on the 8 GB unit,
that is 2267 MB of idle PSS with no reclaim target.

Two pieces fix it, and both are in this repository now:

| Piece | What it does |
|---|---|
| a boot image with the kernel rebuilt from `kernel/source.json` plus `device/configs/liuqin-memory.config` | gives the kernel `zram` with zstd, so 3 GiB of compressed swap exists |
| `liuqin-memory-tweaks` package | installs the zram geometry, the reviewed trim list, `liuqin-root-trim` and the unit masks |

Measured after applying both: 1406 MB total PSS with a full session up, and a
process allocating 6720 MiB (more than `MemTotal`) completes at a 19.24:1
compression ratio instead of ending the session. `docs/MEMORY.md` has the
per-group numbers and the reason for every entry in the trim list.

**Those numbers describe the GNOME session.** The desktop is Plasma Mobile since
2026-10-30 and the trim list now purges the GNOME and Phosh sessions instead of
masking parts of them; `docs/MEMORY.md` records the migration's measured effect
on disk and packages, and the first Plasma idle numbers.

### If you are installing fresh

Nothing extra to do once a bundle is published that includes these changes: the
installer runs `device/tweaks/apply-root-tweaks.sh` on the extracted root
archive before first boot, and the kernel is built from the locked configuration.
Which of this a given bundle carries is recorded in its `bundle.json` under
`features` (`zram_swap`, `rootfs_trim`, `unit_masks`) and printed by
`install-liuqin.py` before it writes anything.

**The published v0.6.0 bundle does not carry them.** Check before you assume:

```sh
python3 install.py --bundle . --check    # prints the feature lines
```

### If you already installed v0.6.0

Build or obtain the two pieces and apply them in order — the kernel first,
because without it the zram configuration has no driver to bind:

```sh
# 1. the kernel, into boot_a only; boot_b keeps the bootloader's fallback copy
sudo blockdev --setrw /dev/sde && sudo blockdev --setrw /dev/sde14
sudo dd if=boot-*-zram.img of=/dev/disk/by-partlabel/boot_a bs=1M conv=notrunc,fsync
sync && sudo reboot

# 2. the root filesystem side
sudo apt-get install -y ./liuqin-memory-tweaks_*_arm64.deb

# 3. what the trim would remove, then remove it, then reboot
sudo liuqin-root-trim --dry-run
sudo liuqin-root-trim
```

`tools/deploy-liuqin-boot.py` does step 1 with a read-back comparison, the
read-only flags of the partition and its disk restored on every exit path, and
the live `boot_a` saved under `backups/` first. Prefer it to the `dd` above.

Rebuilding the two pieces yourself:

```sh
python3 tools/build-liuqin-kernel.py --source ../linux-sm8450-liuqin --out out/kernel
python3 tools/build-liuqin-memory-tweaks.py --kernel-out out/kernel
```

It refuses an existing output directory, so a rebuild needs
`rm -rf out/memory-tweaks` first, or `--out` pointing somewhere fresh. The
result is reproducible: the same kernel build and the same tree produce the
same two hashes.

### Verifying that it landed

```sh
adb -s liuqin push tests/memory-features.py /tmp/
adb -s liuqin shell 'python3 /tmp/memory-features.py --config /proc/config.gz --root / --packages'
```

It reports each customisation separately and exits non-zero if any is missing.
The same file is the image builder's `--stage features` gate, so a bundle cannot
ship a customisation that stopped landing.

### Reverting

Every step is a package name plus a boot image.

```sh
sudo apt-get install snapd firefox                                    # put snap back
sudo apt-get install fwupd cups cups-browsed modemmanager rsyslog \
    networkd-dispatcher switcheroo-control evolution-data-server gnome-calendar
sudo apt-get install gnome-shell gdm3 ubuntu-session                 # GNOME session back
sudo rm /etc/systemd/zram-generator.conf                              # drop zram swap
```

The kernel side is not runtime-reversible: it needs a rebuild and a boot image
flash, or the `boot_a` copy under `backups/liuqin-boot/`.

## Suspend and Sleep

Through v0.6.0 the tablet never slept: PowerDevil was pinned to
`AutoSuspendIdleTimeoutSec=0` because resume had not been proven on this board,
so an idle tablet blanked the panel and left the SoC and the Wi-Fi radio
running. The sleep path is now verified, and this repository ships defaults that
use it:

| Piece | What it does |
|---|---|
| `device/configs/liuqin-*.config` in the kernel lock | keep `CONFIG_SUSPEND`, PSCI system suspend and the debugfs suspend counters |
| `device/root-overlay/etc/xdg/powerdevilrc` | `AutoSuspendAction=1` with a 5 min idle timeout on battery and 15 min on the charger, and `LidAction=1` for the folio cover |
| `device/root-overlay/etc/systemd/logind.conf.d/90-liuqin.conf` | `HandleLidSwitch=suspend` as the fallback before a session exists |

`/sys/power/mem_sleep` selects `deep`, so a suspend goes through
`psci_system_suspend` and the SoC is handed to the firmware. The RTC alarm,
the power key and both hall switches are wakeup sources from the device tree, so
waking does not depend on the session still listening. A power-key short press
still blanks and locks by default; `gsettings set io.github.liuqin.power
short-press-action suspend` makes the key sleep the tablet instead.

**What is not proven yet**: about one suspend in three ends early with every
wakeup-source counter at zero and no wakeup IRQ attributed at all (the resume
comes from the firmware, below Linux), the folio cover's lid action never ran on
the real switch (a virtual `SW_LID` device does not reach the source PowerDevil
watches), and suspend with an external display attached is untested.  The
sleeping cost itself is measured: 121 mA (1.6 %/h) against 227 mA awake, over a
2.5 hour window -- and the firmware's own counters say why it is not lower.
`docs/SUSPEND.md` has the numbers, the wake-source table and the gaps;
`tests/suspend-resume.py` is the check that has to keep passing.

On an installed tablet the defaults above only take effect if the boot
contract is rebound to the new file: `/etc/xdg/powerdevilrc` is one of the
files the ramdisk's admission contract pins, so copying it onto a running
tablet makes the next boot stop in the initramfs diagnostics shell.  A root
image build does that for you; `docs/SUSPEND.md` explains the manual route.

Reverting to the old behaviour is one key and a reload:

```sh
sudo sed -i 's/^AutoSuspendIdleTimeoutSec=.*/AutoSuspendIdleTimeoutSec=0/' /etc/xdg/powerdevilrc
systemctl --user restart plasma-powerdevil
```

## System tray

Plasma Mobile has no place to draw system tray icons: applications register
with `org.kde.StatusNotifierWatcher` and nothing ever displays them (KDE bug
483089), so Tailscale, Telegram, Syncthing and everything else that lives in a
tray is invisible. This port patches the task panel so the icons are drawn next
to the task switcher, home and close buttons:

- the patch lives in a plasma-mobile fork, pinned in
  [`plasma-mobile/source.json`](plasma-mobile/source.json); it adds a small
  StatusNotifierItem host (a model that follows the registry, each item's icon,
  title and status, and its activate/secondary-activate/context-menu methods)
  and a row in `containments/taskpanel` that draws it;
- [`tools/deploy-liuqin-taskpanel.py`](tools/deploy-liuqin-taskpanel.py) builds
  that one containment on the tablet and installs it, then restarts
  `plasma-plasmashell.service`. The applet's QML is installed as a package,
  because the packaged plugin carries its QML compiled in and cannot be
  replaced file by file;
- `--uninstall` puts the packaged task panel back;
- the build needs `build-essential cmake extra-cmake-modules qt6-base-dev
  qt6-declarative-dev qt6-sensors-dev libplasma-dev libkf6config-dev
  libkf6coreaddons-dev libkf6windowsystem-dev` on the tablet (its full
  plasma-mobile build also wants KWin, KPipeWire and QCoro development files,
  which is why the standalone CMake project exists at all).

What it does and does not do: the icons appear and a tap activates the item;
long-press context menus and tool tips are not wired up yet. Items that only
publish `IconPixmap` are supported (they go through an image provider), and an
item that reports `Passive` status is dimmed. Whether an application shows up
at all is up to the application: Tailscale's daemon does not publish a tray
item, so it needs its own GUI (`tailscale web --listen 127.0.0.1:5252`, or
`ssh -L 5252:127.0.0.1:5252` from another machine).

## Usage and Maintenance

Ubuntu packages are managed through APT. Update instructions for the project kernel and device components will accompany each installation release.
Do not mix boot images and system components from different releases.

To run Android applications inside Ubuntu, Waydroid is supported; the required kernel configuration is built in. See [Waydroid support](docs/WAYDROID.md).

Charging power is negotiated through the vendor charger authentication path. See [Fast charging](docs/FASTCHARGE.md).

Report problems through GitHub Issues with the device model, system version, reproduction steps and relevant logs.
Remove passwords, network credentials and personal information before sharing logs.
The accounts listed above are also available for usage discussions.

## Development and Contributions

| Repository | Contents |
|---|---|
| xiaomipad-6pro-mainline | Device configuration, userspace integration, build and installation tools, documentation |
| [linux-sm8450-liuqin](https://github.com/yzddmr6/linux-sm8450-liuqin) | Complete Linux kernel source and device adaptation commits |

[kernel/source.json](kernel/source.json) records the kernel revision used by the build.
The device branch is `liuqin-6.17`. Contributions to drivers, tools and documentation are welcome;
see [CONTRIBUTING.md](CONTRIBUTING.md).

## Acknowledgments and Licensing

This project builds on the kernel work of [sm8450-mainline](https://github.com/sm8450-mainline/linux),
along with Ubuntu, KDE, GNOME and the Linux Qualcomm community.

Original project code is MIT-licensed unless a file states otherwise. Linux and third-party components retain their own licenses;
firmware is subject to its respective owners' terms. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
