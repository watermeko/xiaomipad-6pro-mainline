# Suspend and resume

The tablet suspends to PSCI deep sleep and resumes with everything back.  What
it does *not* do is reach a genuinely low-power platform state: the firmware
puts the application processor to sleep and stops there, so a suspended tablet
still draws about 121 mA.  Both halves are measured below, because the second
one decides whether this feature is worth having.

## What happens now

`/sys/power/mem_sleep` selects `deep`, so a suspend runs `psci_system_suspend`:
every non-boot CPU is offlined, the application processor is handed to the
firmware, the PMIC keeps counting time, and resume costs about half a second.
`s2idle` stays selectable for debugging but the shipped policy does not use it.

The policy that decides *when* comes from two files:

| Path | Who does it |
| --- | --- |
| `device/root-overlay/etc/xdg/powerdevilrc` | PowerDevil: idle for 5 minutes on battery or 15 on the charger, then sleep (`AutoSuspendAction=1`); `LidAction=1` for the folio cover; `PowerButtonAction=0` because `liuqin-power-keyd` owns the power key |
| `device/root-overlay/etc/systemd/logind.conf.d/90-liuqin.conf` | logind: `HandleLidSwitch=suspend` as the fallback for the boot before a session exists, where PowerDevil's blocking lid inhibitor is not there to take over |

With an external display attached PowerDevil keeps its default
`InhibitLidActionWhenExternalMonitorPresent=true`, so closing the cover on a
desk setup does not sleep the tablet.  A power-key short press still blanks and
locks by default; `gsettings set io.github.liuqin.power short-press-action
suspend` makes the key sleep the tablet instead.

Wake sources come from the device tree rather than userspace, so they work
regardless of who was listening when the tablet slept:

| Source | Registered as | Exercised |
| --- | --- | --- |
| PMIC RTC alarm | `c400000.spmi:pmic@0:rtc@6100`, `alarmtimer.0.auto` | yes — every measurement below wakes on it |
| Power key | `...pmic@0:pon@1300:pwrkey` | yes — a short press ended a multi-hour sleep on 2026-09-17 |
| Folio cover | `gpio-keys` `SW_LID`, `wakeup-source` in the device tree | no (needs the cover) |
| Volume up, resin | `gpio-keys`, `...pon@1300:resin` | no |
| Magnetic keyboard | `4-004c`, `wake-gpios = <&tlmm 42>` | no |

The charger's UCSI port, the battery manager, MHI and the three remoteprocs are
also wakeup sources.  `qcom-battmgr-bat` waking the AP every few minutes is
what made a 25 minute suspend end after 5 minutes 45 seconds, so
`liuqin-wakeup-sources` disarms the battery and wireless-charging supplies and
leaves VBUS and the Type-C port armed: plugging a charger still wakes the
tablet.

## What is verified

| Claim | Evidence |
| --- | --- |
| The kernel enters `deep`, not `s2idle` | `PM: suspend entry (deep)`, `psci: CPU1..7 killed`, monotonic clock stopped |
| It stays down for the requested time | 40 s → 43 s, 45 s → 48 s, 90 s → 94 s, 420 s → 422 s, 900 s → 902 s (RTC seconds) |
| Resume restores the tablet | touch, pen, keyboard, touchpad, Wi-Fi (with address) and the panel back after every run; `suspend_stats` counted 1 success and 0 failures per run |
| The idle policy fires | PowerDevil asked for sleep 900 s after boot on the charger with the shipped file, `PM: suspend entry (deep)` followed |
| A sleep that nobody interrupted is resumed | `liuqin-sleep-guard` blanked the lock screen's panel and slept the tablet again in each of 12 consecutive unattended wakes on 2026-11-01, 113-162 s of sleep per cycle |
| The deep state is stable for minutes | twelve 240 s suspends in four configurations all slept 233–244 s |
| It accumulates | nineteen chained suspends slept 9087 s inside a 9126 s window |

`tests/suspend-resume.py` is the check that has to keep passing:

```sh
python3 tests/suspend-resume.py --policy                  # offline, also in CI
python3 tests/suspend-resume.py --cycle 60                # one round trip
python3 tests/suspend-resume.py --drain 1200              # the sleeping cost
```

`--cycle` fails if the kernel did not enter the requested state, if the RTC
slept less than was asked for, if `suspend_stats` counted a failure, or if the
touch, pen, keyboard, touchpad, Wi-Fi or panel did not come back.  `--drain`
pins the state under test (`--drain-state deep|s2idle`), reports the gauge
resolution its window can resolve, and fails if the tablet did not stay down or
the draw is over budget.

The drain is a measurement of hours, and the session that starts it dies with
the USB gadget, so it can be started on the charger and left to begin on its
own once the cable comes out:

```sh
adb -s liuqin push tests/suspend-resume.py /tmp/
adb -s liuqin shell 'systemd-run --unit=liuqin-drain --collect /usr/bin/python3 \
    /tmp/suspend-resume.py --drain 10800 --wait-for-battery 3600'
# unplug the cable; the run arms its alarm, suspends, and logs to the journal
adb -s liuqin shell 'journalctl -u liuqin-drain --no-pager'
```

## What it costs

| State | Current | Drain |
| --- | --- | --- |
| Awake, panel blanked, Wi-Fi associated | 223.6 / 226.9 mA | 3.0 %/h |
| `deep` sleep (2.54 h window, 9087 s asleep) | **121 mA** | **1.6 %/h** |
| `s2idle`, same method (5 × 604 s) | 131 mA | 1.7 %/h |

The `deep` number comes from nineteen chained suspends that accumulated 9087 s
of sleep inside a 9126 s window, during which the fuel gauge moved 307 mAh
(6952 → 6645, 92 % → 88 %).  Against the 7519 mAh the gauge has learned, that is
121 mA.

So the sleep is worth about a factor of two, not the factor of ten a suspended
tablet should be, and `s2idle` — which leaves the SoC running — costs the same.
The gauge moves in steps of roughly 30 mAh, so any single window must be hours
long to mean anything; `--drain` prints the resolution it can resolve.

The USB block is the one part of the draw that was attributed:
unbinding `a6f8800.usb` from `dwc3-qcom-legacy` on battery took the draw from
465 mA to 439 mA and rebinding restored it to 459 mA, so the glue, the xHCI host
controller and the HS PHY are worth **26 mA**.  It cannot be turned into a
saving: after the unbind the UCSI firmware stops accepting role changes
(`failed to set usb role`), the port stays in host mode and the UDC never comes
back until the tablet is rebooted.  The reason the port is in host mode at all
with no cable is `role-switch-default-mode = "host"`, which the device tree
needs for docks; `dwc3-qcom-legacy` also warns `port-1 HS-PHY not in L2` on the
way down, so the PHY never enters its low-power state.

## Why it does not go lower

`/sys/kernel/debug/qcom_stats/` publishes one block per sleep level from the
firmware itself.  After every suspend in this work:

```
apss:        Count 229, accumulated 2758368719   (the APSS sleep state; ~2758 s)
cxsd:        Count 0                              (CX shutdown)
ddr:         Count 0                              (DDR low-power state)
aosd:        Count 0                              (AOSS sleep)
adsp:        Count 8,      accumulated 6.4 s      (the ADSP is awake essentially always)
adsp_island: Count 0                              (the island mode is never entered)
slpi:        Count 5460,   accumulated 2634 s     (the sensor DSP sleeps fine)
cdsp:        Count 34,     accumulated 3480 s
```

The application processor sleeps; CX never shuts down, DDR never leaves its
active state, the always-on subsystem never sleeps, and the ADSP is awake
almost all the time.  That is the 121 mA, measured rather than guessed.

Everything Linux can withdraw was withdrawn, one suspend per configuration:

| Configuration | cxsd | ddr | aosd |
| --- | --- | --- | --- |
| as shipped | 0 | 0 | 0 |
| WLAN driver unbound from PCI (`0000:01:00.0`) | 0 | 0 | 0 |
| SLPI and CDSP remoteprocs stopped | 0 | 0 | 0 |
| the AP's battery-manager client unbound | 0 | 0 | 0 |
| the ADSP remoteproc stopped as well | 0 | 0 | 0 |

With the WLAN unbound and every DSP stopped, the platform still does not leave
the APSS sleep level.  So this is not a vote Linux can withdraw: the firmware's
`SYSTEM_SUSPEND` puts the application processor to sleep and does nothing else,
whatever the AP does.  The RSC's sleep set is flushed by `rpmh_flush()` when the
last CPU enters CPU_PM, and mainline has no debugfs for the cached set, so what
the firmware does with it cannot be observed from here either.

## Why one sleep was all you got

PowerDevil does not suspend on a timer that restarts; it suspends when the idle
time *crosses* its timeout.  On this tablet the idle time is already past the
timeout when the tablet wakes, so it never crosses again until a human touches
the tablet -- and a sleep that the firmware ended on its own does not.  The
shipped policy therefore slept once per login and then stayed awake.

Measured on 2026-11-01 with `AutoSuspendIdleTimeoutSec=60`:

```
02:18:43  The system will suspend now!
02:18:54  Operation 'suspend' finished.        (11 s of sleep, nobody woke it)
02:26:30  nothing -- 7 m 36 s awake, panel off, 227 mA, until powerdevil was
          restarted by hand; the restart suspended the tablet again 60 s later,
          which is how the timeout itself was ruled out
```

Every resume also brings the lock screen back *lit*, and it stays lit until
PowerDevil's display timeout blanks it again, so one unattended wake cost about
five minutes of bright screen on top of the seven minutes of idle.

So the sleep has to be resumed by something other than PowerDevil.  Doing that
on every wake is worse than not doing it at all when the platform is waking
anyway: a naive loop ran 26 suspends between 02:48 and 03:12 with 5-48 s of
sleep and ~10 s awake each, and the tablet was unreachable over Wi-Fi for
minutes at a time because the reassociation never finished.

Those short sleeps were the battery-manager poll.  The wakeup-source policy had
only ever run at boot: a re-probe of the PMIC GLINK supplies arms
`qcom-battmgr-bat` again, and the unit that disarms it is `RemainAfterExit=yes`
and ordered `Before=sleep.target`, which systemd-sleep's
`replace-irreversibly` start of `sleep.target` does not pull in a second time.
It stayed on its boot-time start through a dozen sleeps, the poll woke the AP
every 5-50 s, and the sleeps that the drain measurement had seen as 476-604 s
were being cut to seconds.  The re-application is a `systemd-sleep` hook now
(`/usr/lib/systemd/system-sleep/liuqin-wakeup-sources`), and the same tablet
slept 113-162 s at a time on the charger afterwards.  `tests/suspend-resume.py`
applies the policy itself before it suspends, because it writes
`/sys/power/state` directly and systemd-sleep never runs for it.

`liuqin-sleep-guard` is the answer to both.  It reads the interrupt counters of
the input devices -- power key, touchscreen, pen, fingerprint reader, folio
keyboard, the tablet's own buttons -- so a wake that a human asked for resets
its grace period, blanks the lock screen's panel through
`liuqin-power-key-action short` (twice: that script toggles against its own
memory of the panel, which a resume has made stale), and only then sleeps the
tablet.  A suspend that the kernel refused (a resume leaves a wakeup pending
for about half a minute) is retried in 30 s; a sleep that lasted less than
`min_sleep` (60 s) is not worth another resume, so it leaves the tablet awake
with the panel dark for 120 s instead of thrashing.

What that is worth, measured over 05:07-05:18 on the charger at 100 %:

| | without the guard | with the guard |
| --- | --- | --- |
| sleeps | one, then awake forever | 145, 86, 102, 75 s |
| awake between them | 7 m 36 s | about 60 s, panel dark |
| share of wall time asleep | ~0 % | **~63 %** |
| effective draw | 227 mA | **~160 mA** |

On battery the same guard does better, because there the firmware lets the
tablet sleep 476-604 s at a time: with 20-90 s of overhead per cycle that is
85-90 % of wall time asleep, about 135 mA.  The ceiling is still the platform's
own 121 mA, and the reason it is not lower is the next section.

How much of the wall time is really asleep therefore depends on the firmware's
mood, not on the guard.  The same tablet, same image, hours apart:

| window | sleeps | asleep | awake | share asleep | effective draw |
| --- | --- | --- | --- | --- | --- |
| 05:07-05:18, charger | 145, 86, 102, 75 s | ~408 s | ~250 s | 63 % | ~160 mA |
| 06:24-06:44, charger | 5-40 s, 14 of them | ~250 s | ~950 s | 21 % | ~200 mA |
| 06:44-07:03, charger | 32 sleeps of 6-38 s | 668 s | 476 s | 42 % | ~182 mA |
| 12:32-12:55, charger | 167, 400, 406 s and shorter ones | 1214 s | 174 s | **87 %** | **~135 mA** |

Every one of those wakes came back with `pm_wakeup_irq` empty: the firmware
resumed the application processor without attributing an interrupt, which is
the same uncounted wake that ends a sleep early in the first place.  On battery
the same guard slept 476-604 s at a time, so the difference is the charger, not
the guard -- and the guard is what keeps the tablet returning to sleep at all.

One more thing had to be taught to the guard, and it cost an hour of access to
learn: after an unattended wake the WLAN has to reassociate, and a sleep that
lands before it does leaves the tablet off the network until something wakes it
again.  On 2026-11-01 that turned into forty minutes where neither SSH nor adb
worked -- each cycle slept again before the link came back, and only a human
pressing the power key ended it.  The guard now gives the link `link_wait` (25 s)
after a resume before it sleeps anyway, which keeps an offline tablet sleeping
while keeping a reachable one reachable.

## What still ends a sleep early

A tablet that wakes up on its own spends the power the sleep was supposed to
save, so the wake side matters as much as the sleep side.

1. **The ADSP's battery-manager poll.** A 25 minute suspend ended after 5 m 45 s
   with `qcom-battmgr-bat` sitting in the wakeup-source counters.  It is
   disarmed by `liuqin-wakeup-sources` before every sleep now
   (`/usr/lib/systemd/system-sleep/liuqin-wakeup-sources`), not only at boot:
   with the boot-time run alone a PMIC GLINK re-probe quietly armed it again
   and the sleeps dropped to 5-50 s.  With the hook in place the same suspend
   slept 420 s and 900 s with the RTC as the only wakeup, and 113-162 s later
   the same night.
2. **The RTC alarm.** Every measurement above is woken by
   `/sys/class/rtc/rtc0/wakealarm`; `pm8xxx_rtc_alarm` counts one interrupt per
   alarm and the tablet stays down to within a few seconds of the request.
3. **An unexplained wake with no wakeup-source event and no wakeup IRQ.** One
   300 s suspend ended after 87 s, one of 1500 s after 635 s, a 20 s request
   after 15 s, and a 10800 s request after 481 s, each with every counter in
   `/sys/kernel/debug/wakeup_sources` still at zero and the RTC alarm still
   armed.  On the 481 s run `CONFIG_PM_DEBUG` was active with
   `pm_debug_messages=1` and `/sys/power/pm_wakeup_irq` came back **empty**: the
   kernel did not attribute the resume to any interrupt at all.
4. **The first `systemctl suspend` after a boot can abort before it starts**
   with `Wakeup pending. Abort CPU freeze` (one `suspend_stats` failure,
   `-EBUSY`); a retry a few minutes later goes through.  No wakeup-source
   counter moves for that one either, so it is the same uncounted event.

Roughly one suspend in three ends early because of (3).  `CONFIG_PM_DEBUG` and
`CONFIG_PM_SLEEP_DEBUG` are in the kernel lock
(`device/configs/liuqin-suspend.config`), so `/sys/power/pm_wakeup_irq` and the
`PM: Triggering wakeup from IRQ N` line can name the interrupt when there is one
to name; `tests/suspend-resume.py --cycle` prints both.

## End to end, on battery

Two windows on 2026-11-01, cable out, nothing touching the tablet, gauge
differences (`charge_counter`, ~30 mAh resolution) over the wall time:

| window | what ran | used | draw | percent |
| --- | --- | --- | --- | --- |
| 1.59 h | the shipped policy with `liuqin-sleep-guard` chaining (`success` 6, sleeps of 453 s and 4772 s, ~85 % of the window asleep) | 162 mAh | **102 mA** | **1.36 %/h** |
| 0.84 h | no suspends at all: panel dark, Wi-Fi associated, idle | 181 mAh | **216 mA** | **2.88 %/h** |

So suspending is worth a factor of two in daily use, and the second window
cross-checks the earlier awake-idle measurement (3.0 %/h).  The suspended
number is also better than the 121 mA the chained-suspend drain measured
earlier, because the guard now leaves the tablet asleep for as long as the
firmware allows instead of cycling it: 4772 s in one go in that window.

The absolute number is still not a tablet's deep sleep -- that is the firmware
section below -- but it is what this port delivers in practice, measured rather
than modelled.

## What the firmware was asked, and what it answered

The floor is the firmware's, so the next step was to go at the firmware itself:
unpack the vendor images, find the interfaces the vendor kernel uses to put the
platform to sleep, and give the mainline kernel the same ones.  Three
candidates were found and each was implemented and measured; all three came back
negative, and the measurements are the useful part.

**1. The USB PHY (a known s2idle bug on SM8550).**  `dwc3-qcom-legacy` warns
`port-1 HS-PHY not in L2` on the way into suspend, and mainline holds an extra
`phy_init` on the PHYs, so the block never leaves its active state.  Unbinding
`s a6f8800.usb` from the driver on battery takes 26 mA off the draw, so the
question was whether it also holds CX up.  It does not: with the glue unbound a
60 s suspend still left `cxsd`, `ddr` and `aosd` at zero.

**2. The AOP's own "prevent" votes.**  `/sys/kernel/debug/aoss-qmp/` has
`prevent_cx_collapse`, `prevent_ddr_collapse` and `prevent_aoss_sleep`, the
mainline form of the vendor's `aop_send_message` controls.  Writing zero to all
three and suspending changed nothing.

**3. The SMP2P sleep state bit (the one the vendor kernel writes).**  The
vendor's `smp2p_sleepstate.c` clears bit 12 of the SMP2P "sleepstate" entry
before the system suspends and sets it again afterwards, which is how a
downstream kernel tells the DSPs that the AP is going away.  The entry lives on
the SLPI edge (SMEM `<481>, <430>`, remote pid 3); the vendor device tree names
it and its inbound sibling "sleepstate_see", and it is in the firmware's own
SMEM item, so nothing had to be invented.  The ported driver and the two device
tree entries are in `kernel/patches/` and `device/configs/liuqin-sleepstate.config`
(the kernel build applies `kernel/patches/*.patch` on top of the pinned commit).

Measured with the driver bound (`probe of smp2p-sleepstate returned 0`) and the
notifier clearing the bit on the way in:

```
before   apss Count 227 acc 134834671   adsp Count 8 acc 6421810
         cxsd 0  ddr 0  aosd 0  adsp_island 0
suspend 60 s -> success=1, apss Count 228 acc 176492987 (~42 s of sleep)
after    cxsd 0  ddr 0  aosd 0  adsp_island 0   adsp Count 8 acc 6421810
```

So this firmware does not act on the bit either: `apss` counts, every deeper
level stays at zero, and the ADSP does not sleep by one microsecond.  The driver
stays in the tree because it is the mechanism the DSPs are documented to use and
because a firmware update may start honouring it, but it does not move the
floor on this one.

**4. The vote itself, not just the bit.**  `rpmhpd` writes the *sleep* corner of
each domain as a copy of its active corner (`to_active_sleep()`), so `cx.lvl`
reaches the AOP as whatever corner the clocks and the display last voted --
never as "off".  A test patch (kept out of the tree) registered syscore_ops that
write `cx.lvl = 0` into the sleep set after the devices are suspended and
restore the corner on resume, which is the smallest version of what the vendor's
LPM does before its PSCI call.  Measured: `success=1`, `apss` 214 -> 215 with
518 s of sleep in the counters, and `cxsd`, `ddr`, `aosd` still at zero, `adsp`
unchanged to the microsecond.

Two things were learned on the way that are worth keeping:

- The inbound half of that entry ("sleepstate_see") must not be a wakeup source
  here.  It fires every few tens of seconds, and each event makes
  `pm_wakeup_pending()` true: `Wakeup pending. Abort CPU freeze` on every
  attempt, for a minute straight.  The ported driver only writes the bit.
- A boot image needs the *merged* device tree, not the kernel's own: the
  bootloader matches the board on the DTB the bundle build produces (the kernel
  DTB plus the stock overlays, 224 KB), and a bare 121 KB kernel DTB puts the
  tablet in fastboot.  `tools/deploy-liuqin-boot.py --dtb` exists for that, and
  the right input is the merged tree (`fdtoverlay -i <product dtb> -o <new> <overlay>`).

With that, four independent Linux-side causes are eliminated by measurement
(USB PHY, AOP prevent votes, the SMP2P sleep-state bit, and the CX sleep-set
vote itself), on top of the earlier one (every subsystem Linux can stop, stopped).

What is left, and it is the only remaining explanation that fits every
measurement: the AOP firmware on this device does not run its CX/DDR/AOSS
collapse sequence for the votes mainline sends.  The vendor kernel's RPMh usage
(`rpmhpd` sleep corners, cpufreq's sleep set, the interconnect paths it leaves
voted) is the place to compare next, and the cheapest check is to boot the
tablet's Android slot once and read `/sys/kernel/debug/qcom_stats` there: if
Android's own counters stay at zero too, no kernel change will move this floor.

## What a fix for the power floor would have to change

Everything above this line is Linux plumbing, and it is finished.  The power
floor is not, and it is not reachable from userspace:

1. **The firmware has to go deeper than APSS.**  `cxsd`, `ddr` and `aosd` read 0
   after every suspend, with every subsystem Linux can stop already stopped.
   Whether the RSC's sleep set carries a surviving vote or the firmware simply
   never goes deeper cannot be told from Linux.
2. **The ADSP has to sleep.**  It is awake essentially always while the sensor
   DSP sleeps thousands of times.  It carries the charger, fuel gauge, Type-C
   and audio firmware, and userspace cannot stop it for the length of a night.
3. **The island mode is not even modelled.**  `adsp_island` never increments,
   mainline's `qcom_q6v5_pas` has no island support and the device tree has no
   island carveout, so the low-power ADSP mode the vendor firmware uses for
   audio offload is out of reach today.

The measuring side is in place for whoever picks this up: one suspend, then
`qcom_stats/{apss,cxsd,ddr,aosd,adsp}` (the counters survive a reboot), and
`tests/suspend-resume.py --drain` for the milliamps.

## Operational traps

- **The boot image pins the root filesystem.**  The ramdisk carries an
  admission contract over 46 files, and `/etc/xdg/powerdevilrc` is one of them.
  Copying the shipped file onto a running tablet makes the next boot fail closed
  into the initramfs diagnostics shell (`native root rejected: hash differs
  from the contract`).  Rebinding is a pair: update the hash in the contract,
  patch the *live* boot image with `tools/patch-native-admission.py --boot-img
  <live boot_a> --contract <updated>`, write the file to the root, flash,
  reboot.  The per-user `~/.config/powerdevilrc` has to be moved aside too, or
  it keeps pinning `AutoSuspendIdleTimeoutSec=0` over the shipped default.
- **`liuqin-usb-gadget-watch` ships disabled.**  It rebuilds the gadget after
  `adbd` gives up on its FunctionFS transport, and with a host attached that
  rebuild races the role switch: the log ends with `FUNCTIONFS_SUSPEND`, "Set
  phy mode to usb host" and the xHCI probing on the port that still has a cable
  in it, and the tablet rebooted -- twice.  Enable it with
  `/etc/liuqin-usb-gadget-watch-enabled` only if you accept that, and stop it
  before any long `adb` transfer either way.
- **After a suspend with the cable attached, `adb` usually comes back dead.**
  `systemctl restart liuqin-usb-gadget` on the tablet restores it.
- **Unbinding platform blocks is not always reversible.**  The dwc3 glue
  (`a6f8800.usb`) leaves the port in host mode with no UDC and the Type-C role
  write failing with `I/O error`; only a reboot brings USB back (reproduced
  twice).  The same goes for the PMIC GLINK clients: unbinding the battery
  manager brings the tablet into a state where it became unreachable over both
  USB and Wi-Fi.
- **Stopping the ADSP and then unplugging a cable froze the tablet** (no pstore
  record, power-key reset).  Stopping and starting it *without* a cable event is
  fine -- that is how the APSS-only result above was measured.
- **A drain loop must stop when the charger returns.**  With a charger and a
  power key present, every suspend is woken within seconds, so a loop that keeps
  suspending flashes the screen until the tablet is reset.

## Reverting

The sleep policy is two files and a reload:

```sh
sudo sed -i 's/^AutoSuspendIdleTimeoutSec=.*/AutoSuspendIdleTimeoutSec=0/' \
    /etc/xdg/powerdevilrc
systemctl --user restart plasma-powerdevil
```

Setting `AutoSuspendAction=0` as well leaves the tablet like the 0.6.0 image:
the panel blanks, the SoC keeps running.  Forcing the old behaviour for a single
boot needs nothing at all:

```sh
echo s2idle | sudo tee /sys/power/mem_sleep
```
