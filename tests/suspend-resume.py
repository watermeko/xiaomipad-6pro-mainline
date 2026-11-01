#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prove that the tablet sleeps, that resume restores it, and that sleeping
is cheaper than staying awake.

Three surfaces, the same shape as tests/memory-features.py:

  policy  the offline files that decide *when* the tablet suspends
  cycle   one live round-trip through the sleep state on the tablet
  drain   the battery current while suspended, measured against an awake
          baseline on the same battery

    # the shipped policy, before an image is built
    python3 tests/suspend-resume.py --policy --root device/root-overlay

    # a round-trip: request 90 s of deep sleep, wake on the RTC alarm
    adb -s liuqin push tests/suspend-resume.py /tmp/
    adb -s liuqin shell 'python3 /tmp/suspend-resume.py --cycle 90'

    # the sleeping cost: 20 minutes on battery, charger unplugged
    adb -s liuqin shell 'python3 /tmp/suspend-resume.py --drain 1200'

`--cycle` and `--drain` must run as root on the tablet.  Both write nothing
except the RTC alarm and /sys/power/state, and both clear the alarm afterwards
so a failed run cannot wake the tablet later.

Why the clock checks matter: during a real suspend the kernel's monotonic
clock stops while the PMIC's RTC keeps counting.  `suspended` below is the
RTC time the tablet spent asleep; `kernel` is what the kernel thought passed.
A tablet that never slept reports the same number for both, and a tablet that
woke early reports fewer RTC seconds than were requested.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RTC = Path('/sys/class/rtc/rtc0')
SUSPEND_STATS = Path('/sys/kernel/debug/suspend_stats')
WAKEUP_SOURCES = Path('/sys/kernel/debug/wakeup_sources')

# What the shipped desktop has to say about sleeping, and why it is checked as
# files rather than as prose: a default that drifts back to "never suspend"
# leaves the SoC running for as long as the tablet is in a bag.
POLICY = {
    'auto-suspend': {
        'why': 'a desktop that only blanks the panel leaves the SoC and the '
               'Wi-Fi radio running, which is the whole cost of a tablet in a bag',
        'checks': [
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'Battery][SuspendAndShutdown', 'AutoSuspendAction', '1'),
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'Battery][SuspendAndShutdown', 'AutoSuspendIdleTimeoutSec', '300'),
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'AC][SuspendAndShutdown', 'AutoSuspendAction', '1'),
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'AC][SuspendAndShutdown', 'AutoSuspendIdleTimeoutSec', '900'),
        ],
    },
    'lid-suspend': {
        'why': 'the folio cover is the tablet\'s lid; closing it has to end the '
               'session exactly like closing a laptop lid does',
        'checks': [
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'Battery][SuspendAndShutdown', 'LidAction', '1'),
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'AC][SuspendAndShutdown', 'LidAction', '1'),
            # PowerDevil blocks logind\'s switch handling, so logind is only the
            # fallback for the greeter and for a session that never started.
            ('device/root-overlay/etc/systemd/logind.conf.d/90-liuqin.conf',
             'Login', 'HandleLidSwitch', 'suspend'),
        ],
    },
    'battery-polls-do-not-wake': {
        'why': 'the ADSP battery manager publishes a status block every few '
               'minutes and every one of them woke the AP: a 25 minute sleep '
               'ended after 5 m 45 s with no user activity and no cable event',
        'executable': ['device/root-overlay/usr/local/sbin/liuqin-wakeup-sources',
                       'device/root-overlay/usr/lib/systemd/system-sleep/liuqin-wakeup-sources'],
        'content': [
            ('device/root-overlay/usr/local/sbin/liuqin-wakeup-sources',
             'qcom-battmgr-bat'),
            ('device/root-overlay/usr/local/sbin/liuqin-wakeup-sources',
             'qcom-battmgr-usb'),
            ('device/root-overlay/etc/systemd/system/liuqin-wakeup-sources.service',
             'WantedBy=multi-user.target'),
            # A PMIC GLINK re-probe arms the battery manager again after the
            # boot-time run, and a unit ordered Before=sleep.target is not
            # pulled in by systemd-sleep's sleep.target start, so the per-sleep
            # re-application lives in the systemd-sleep hook directory.
            ('device/root-overlay/usr/lib/systemd/system-sleep/liuqin-wakeup-sources',
             '/usr/local/sbin/liuqin-wakeup-sources'),
        ],
    },
    'unattended-resume-sleeps-again': {
        'why': 'powerdevil suspends when the idle time crosses its timeout, and '
               'an idle timeout only crosses once: a resume that nobody asked '
               'for leaves the idle time above the timeout, so the tablet stays '
               'awake at the awake-idle draw until somebody touches it -- '
               'measured on 2026-11-01, an 11 s sleep left the tablet awake for '
               'more than eight minutes with AutoSuspendIdleTimeoutSec=60',
        'executable': ['device/root-overlay/usr/local/sbin/liuqin-sleep-guard'],
        'content': [
            # The internal panel is the only reliable "nobody is looking"
            # signal: powerdevil blanks it before suspending, a resume leaves
            # it off, and a power-key wake turns it back on.
            ('device/root-overlay/usr/local/sbin/liuqin-sleep-guard',
             '/sys/class/drm/card*-DSI-*'),
            ('device/root-overlay/usr/local/sbin/liuqin-sleep-guard',
             'liuqin-sleep-guard-hold'),
            # A sleep that lands before the WLAN has reassociated leaves the
            # tablet off the network: on 2026-11-01 that cost forty minutes
            # with no SSH and no adb until somebody pressed the power key.
            ('device/root-overlay/usr/local/sbin/liuqin-sleep-guard',
             'operstate'),
            ('device/root-overlay/etc/systemd/system/liuqin-sleep-guard.service',
             'WantedBy=multi-user.target'),
            ('device/root-overlay/etc/systemd/system/liuqin-sleep-guard.service',
             'Restart=always'),
        ],
    },
    'power-key-kept': {
        'why': 'PowerDevil must not act on the power key a second time: '
               'liuqin-power-keyd owns it, and a short press has to blank',
        'checks': [
            ('device/root-overlay/etc/xdg/powerdevilrc',
             'General', 'PowerButtonAction', '0'),
        ],
    },
}


class Failure(Exception):
    pass


def read_ini(path):
    """Return {(section, key): value} for the Qt-shaped ini files KDE writes.

    PowerDevil's groups nest as `[AC][SuspendAndShutdown]`; configparser would
    keep that whole string as one section name, so the outer bracket is stripped
    here and the group is matched without it.
    """
    values = {}
    section = ''
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line[0] in '#;':
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            continue
        key, separator, value = line.partition('=')
        if separator:
            values[(section, key.strip())] = value.strip()
    return values


def check_policy(root, config=None):
    failures = []
    if config and Path(config).is_file():
        # The sleep path needs CONFIG_SUSPEND and CONFIG_PM_SLEEP from whatever
        # base configuration the build starts from; no project fragment pins
        # them, so a base-config sync is the way they would disappear.
        text = Path(config).read_text()
        for symbol in ('CONFIG_SUSPEND=y', 'CONFIG_PM_SLEEP=y'):
            if symbol not in text:
                failures.append('kernel config: %s is missing from %s' % (symbol, config))
            else:
                print('ok   kernel config: %s' % symbol)
    for name, feature in POLICY.items():
        for relative in feature.get('executable', []):
            path = Path(root) / relative
            if not path.is_file():
                failures.append('%s: missing file %s' % (name, path))
            elif not path.stat().st_mode & 0o111:
                failures.append('%s: %s is not executable, so the unit that runs '
                                'it fails with EACCES' % (name, path))
            else:
                print('ok   %s: %s is executable' % (name, relative))
        for relative, needle in feature.get('content', []):
            path = Path(root) / relative
            if not path.is_file():
                failures.append('%s: missing file %s' % (name, path))
            elif needle not in path.read_text():
                failures.append('%s: %s does not mention %s'
                                % (name, path.name, needle))
            else:
                print('ok   %s: %s mentions %s' % (name, relative, needle))
        for relative, section, key, expected in feature.get('checks', []):
            path = Path(root) / relative
            label = '%s: %s %s[%s] %s=%s' % (name, relative, '[', section, key, expected)
            if not path.is_file():
                failures.append('%s: missing file %s' % (name, path))
                continue
            actual = read_ini(path).get((section, key))
            if actual != expected:
                failures.append('%s: %s wants %s=%s, found %r'
                                % (name, path.name, key, expected, actual))
            else:
                print('ok   %s' % label)
    return failures


SLEEP_GUARD_HOLD = Path('/run/liuqin-sleep-guard-hold')


class sleep_guard_held:
    """Keep liuqin-sleep-guard from suspending on its own while a test drives
    the sleeps.

    The guard suspends whenever the internal panel is off, which is exactly the
    state the tests leave the tablet in.  Without the hold it would suspend the
    tablet between a test's own cycles, and a `--cycle` reading its counters
    back could be interrupted by a suspend it did not ask for.  Not having the
    file (a tablet without the guard) is not an error.
    """

    def __enter__(self):
        try:
            SLEEP_GUARD_HOLD.write_text('%d\n' % os.getpid())
            self.held = True
        except OSError:
            self.held = False
        return self

    def __exit__(self, *exception):
        if self.held:
            try:
                SLEEP_GUARD_HOLD.unlink()
            except OSError:
                pass
        return False


def read_int(path, default=0):
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return default


def monotonic():
    return time.clock_gettime(time.CLOCK_MONOTONIC)


def boottime():
    """Uptime including suspended time: /proc/uptime's first column."""
    return float(Path('/proc/uptime').read_text().split()[0])


def suspend_counts():
    success = failed = 0
    for line in SUSPEND_STATS.read_text().splitlines():
        field, _, value = line.partition(':')
        if field == 'success':
            success = int(value)
        elif field == 'fail':
            failed = int(value)
    return success, failed


def wakeup_events():
    # One row per source, tab separated, with the event count third.  A source
    # whose name contains a space (the header row is one such line) would
    # otherwise raise instead of being skipped.
    events = {}
    for line in WAKEUP_SOURCES.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) > 2 and parts[2].isdigit():
            events[parts[0]] = int(parts[2])
    return events


def interrupt_counts():
    """Per-IRQ totals from /proc/interrupts, keyed by "number name".

    A deep suspend has no other way to name the interrupt that woke the
    tablet: the wakeup-source counters only cover devices that call
    pm_wakeup_event(), and CONFIG_PM_SLEEP_DEBUG (which provides
    /sys/power/pm_wakeup_irq) is not in the product configuration.
    """
    counts = {}
    for line in Path('/proc/interrupts').read_text().splitlines()[1:]:
        head, _, tail = line.partition(':')
        try:
            irq = int(head.strip())
        except ValueError:
            continue
        parts = tail.split()
        numbers = []
        for part in parts:
            if part.isdigit():
                numbers.append(int(part))
            else:
                break
        name = ' '.join(parts[len(numbers):])
        counts['%s %s' % (irq, name)] = sum(numbers)
    return counts


def wake_irqs():
    """The interrupts with wakeup enabled, from /sys/kernel/irq/*/wakeup."""
    armed = []
    for directory in sorted(Path('/sys/kernel/irq').glob('*')):
        wakeup = directory / 'wakeup'
        name = directory / 'actions'
        if not wakeup.exists() or not name.exists():
            continue
        try:
            if wakeup.read_text().strip() != 'enabled':
                continue
        except OSError:
            continue
        armed.append('%s %s' % (directory.name, name.read_text().strip()))
    return armed


def report_interrupts(before, after, limit=8):
    deltas = {name: after.get(name, 0) - count
              for name, count in before.items()
              if after.get(name, 0) > count}
    ranked = sorted(deltas.items(), key=lambda item: -item[1])[:limit]
    for name, delta in ranked:
        print('irq         %-52s +%d' % (name, delta))
    if not ranked:
        print('irq         no interrupt fired')


def dmesg_lines():
    return subprocess.run(['dmesg'], capture_output=True, text=True,
                          check=True).stdout.splitlines()


WAKEUP_SOURCES = Path('/usr/local/sbin/liuqin-wakeup-sources')


def apply_wakeup_policy():
    """Re-arm the wakeup-source policy the way a real sleep does.

    The kernel keeps the driver-level wakeup flags across a suspend, but a
    PMIC GLINK re-probe arms the battery manager again, and its poll then ends
    every sleep after a few seconds -- which is what the RTC-versus-battery
    wakeup check below is for.  A real sleep re-applies the policy from
    /usr/lib/systemd/system-sleep/; this test writes /sys/power/state itself,
    so systemd-sleep never runs and the policy has to be applied here.
    """
    if not WAKEUP_SOURCES.is_file():
        return
    subprocess.run([str(WAKEUP_SOURCES)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def arm_alarm(seconds):
    (RTC / 'wakealarm').write_text('0')
    (RTC / 'wakealarm').write_text('+%d' % seconds)


def clear_alarm():
    try:
        (RTC / 'wakealarm').write_text('0')
    except OSError:
        pass


# The parts of the tablet that a resume has to give back.  They are read
# through their user-visible names, not through driver directories: the
# touchscreen is an SPI device with a vendor driver, and the point of the check
# is that input still reaches the session.
def input_names():
    names = set()
    for line in Path('/proc/bus/input/devices').read_text().splitlines():
        if line.startswith('N: Name='):
            names.add(line.split('=', 1)[1].strip().strip('"'))
    return names


def wifi_associated():
    operstate = Path('/sys/class/net/wlp1s0/operstate')
    if not operstate.exists() or operstate.read_text().strip() != 'up':
        return False
    addresses = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'wlp1s0'],
                               capture_output=True, text=True)
    return ' inet ' in ' %s ' % addresses.stdout.replace('\n', ' ')


def resume_state():
    """What has to be back after a resume."""
    names = input_names()
    return {
        'touch': 'NVTCapacitiveTouchScreen' in names,
        'pen': 'NVTCapacitivePen' in names,
        'keyboard': 'Xiaomi Keyboard' in names,
        'touchpad': 'Xiaomi Mouse' in names,
        'wifi': wifi_associated(),
        'panel': Path('/sys/class/drm/card0-DSI-1/status').read_text().strip(),
    }


def cycle(seconds, state, expected_wake):
    if os.geteuid() != 0:
        raise Failure('--cycle needs root')
    if not SUSPEND_STATS.exists():
        raise Failure('no %s (CONFIG_PM_SLEEP / debugfs)' % SUSPEND_STATS)
    mem_sleep = Path('/sys/power/mem_sleep').read_text().strip()
    if state == 'deep' and 'deep' not in mem_sleep:
        raise Failure('platform offers no deep sleep: mem_sleep=%r' % mem_sleep)

    # Pin the state under test rather than trusting whatever is selected, and
    # put the selection back on the way out.
    original = mem_sleep
    selected = 'deep' if state == 'deep' else 's2idle'
    Path('/sys/power/mem_sleep').write_text(selected)

    before_dmesg = dmesg_lines()
    before_stats = suspend_counts()
    before_events = wakeup_events()
    before_rtc = read_int(RTC / 'since_epoch')
    before_boottime = boottime()
    before_monotonic = monotonic()
    before_state = resume_state()

    apply_wakeup_policy()
    arm_alarm(seconds)
    subprocess.run(['sync'], check=True)
    alarm_left = ''
    after_irqs = {}
    try:
        before_sleep_irqs = interrupt_counts()
        with open('/sys/power/state', 'w') as handle:
            handle.write('mem')
        # Both reads happen on the resume side: a woken tablet has already
        # consumed the alarm, and the interrupt counters have to be taken
        # before the resume's own timer and radio activity drowns the wake.
        after_irqs = interrupt_counts()
        alarm_left = (RTC / 'wakealarm').read_text().strip()
    finally:
        clear_alarm()
        Path('/sys/power/mem_sleep').write_text(
            'deep' if 'deep' in original else 's2idle')

    elapsed_rtc = read_int(RTC / 'since_epoch') - before_rtc
    elapsed_boottime = boottime() - before_boottime
    elapsed_monotonic = monotonic() - before_monotonic
    after_stats = suspend_counts()
    after_events = wakeup_events()
    after_state = resume_state()
    time.sleep(2)
    new_dmesg = dmesg_lines()[len(before_dmesg):]

    entry = [line for line in new_dmesg if 'PM: suspend entry' in line]
    exit_ = [line for line in new_dmesg if 'PM: suspend exit' in line]
    killed = [line for line in new_dmesg if re.search(r'psci: CPU\d+ killed', line)]
    if not entry or not killed:
        # The ring buffer can rotate between the two snapshots -- a resume
        # writes a lot -- and then the positional slice above hides the entry
        # line and the psci kills.  Fall back to the newest entry line in the
        # whole log so a rotated buffer does not read as "the CPUs stayed up".
        whole = dmesg_lines()
        newest = None
        for index, line in enumerate(whole):
            if 'PM: suspend entry' in line:
                newest = index
        if newest is not None:
            if not entry:
                entry = [whole[newest]]
            if not exit_:
                exit_ = [line for line in whole[newest + 1:]
                         if 'PM: suspend exit' in line]
            if not killed:
                killed = [line for line in whole[newest:]
                          if re.search(r'psci: CPU\d+ killed', line)]

    failures = []

    def expect(condition, message):
        if condition:
            print('ok   %s' % message)
        else:
            print('FAIL %s' % message)
            failures.append(message)

    print('requested   %4d s of %s' % (seconds, selected))
    print('rtc         %4d s asleep (the PMIC clock kept counting)' % elapsed_rtc)
    print('boottime    %4.1f s (includes sleep)' % elapsed_boottime)
    print('kernel      %4.1f s on the monotonic clock, which stops while asleep'
          % elapsed_monotonic)
    print('suspend     success %d->%d, fail %d->%d'
          % (before_stats[0], after_stats[0], before_stats[1], after_stats[1]))

    expect(alarm_left in ('', '0'), 'the RTC alarm was consumed by the wake')
    expect(bool(entry), 'the kernel logged a suspend entry')
    expect(bool(exit_), 'the kernel logged a suspend exit')
    expect(after_stats[0] == before_stats[0] + 1,
           'suspend_stats counted exactly one success')
    expect(after_stats[1] == before_stats[1],
           'suspend_stats counted no failure')
    expect(elapsed_rtc >= seconds * 0.9,
           'the tablet stayed asleep for the requested %d s (RTC)' % seconds)
    expect(elapsed_rtc <= seconds + 60,
           'the tablet woke up on the alarm, not later')
    expect(elapsed_boottime >= seconds * 0.9,
           'time really passed while the PMIC clock ran')
    if state == 'deep':
        expect(any('(deep)' in line for line in entry),
               'the kernel entered deep, not s2idle')
        expect(bool(killed),
               'the non-boot CPUs were offlined for the platform suspend')
    else:
        expect(any('(s2idle)' in line for line in entry),
               'the kernel entered s2idle')

    # Resume is asynchronous: Wi-Fi reassociates a second or two later, so the
    # state is polled instead of sampled once.
    settled = {}
    settle_seconds = 0
    while True:
        settled = resume_state()
        if settled.get('wifi') or settle_seconds >= 30:
            break
        time.sleep(1)
        settle_seconds += 1

    for name, value in sorted(settled.items()):
        print('after       %-9s %s' % (name, value))
    print('settled     %d s after resume' % settle_seconds)
    for name in ('touch', 'pen', 'keyboard', 'touchpad', 'wifi'):
        expect(settled[name] == before_state[name],
               'the %s came back after the resume' % name)
    expect(settled['panel'] == before_state['panel'],
           'the panel is %s again' % before_state['panel'])

    counts = {name: after_events.get(name, 0) - before_events.get(name, 0)
              for name in after_events}
    fired = {name: count for name, count in counts.items() if count}
    print('wakeups     %s' % (fired or 'none recorded'))
    report_interrupts(before_sleep_irqs, after_irqs)
    print('armed       %s' % (', '.join(wake_irqs()) or 'none'))
    wake_irq = Path('/sys/power/pm_wakeup_irq')
    if wake_irq.exists():
        # CONFIG_PM_DEBUG names the interrupt that ended the suspend.  The
        # wakeup-source counters do not cover the PMIC/RSC path, so this is the
        # only reliable answer for a wake that arrives with no source event.
        # An empty attribute reads as ENODATA, not as an empty string: "no
        # interrupt was attributed" is a result, not an error.
        try:
            number = wake_irq.read_text().strip()
        except OSError:
            number = ''
        name = ''
        for line in Path('/proc/interrupts').read_text().splitlines():
            if line.split(':')[0].strip() == number:
                name = line.split(':', 1)[1].strip()
                break
        print('wake irq    %s %s' % (number or '(none)', name))
    if expected_wake:
        came_from = fired.get(expected_wake, 0) > 0
        if not came_from and 'rtc' in expected_wake and 'rtc' in (name or '').lower():
            # The RTC alarm is an interrupt rather than a wakeup source whose
            # counter moves on every alarm, so the interrupt name is the same
            # evidence for it.  The sleep length and the consumed alarm above
            # already pin down that it was this alarm and not another.
            came_from = True
        expect(came_from, 'the wake came from %s' % expected_wake)

    return failures


DESIGN_MAH = 8600  # "M81_8600mah", the model string the fuel gauge reports


def drain(seconds, threshold_percent_per_hour, wait_for_battery=0, state='deep'):
    """Battery current while asleep, on battery, against an awake baseline.

    The baseline is meant to be the state this tablet idles in when it does not
    sleep: the panel blanked by PowerDevil's idle timeout.  The caller sets
    that up (AutoSuspendIdleTimeoutSec=0, TurnOffDisplayIdleTimeoutSec short)
    and waits for /sys/class/drm/card0-DSI-1/dpms to read Off; the panel state
    is reported below so an awake number that still includes the panel cannot
    be mistaken for a fair baseline.

    The gauge reports charge_counter in mAh but no charge_full, so the percentage
    is converted with the capacity learned from the counter itself (7615 mAh at
    100 % after 362 cycles on the 8 GB test unit, against 8600 mAh of design
    capacity).
    """
    if os.geteuid() != 0:
        raise Failure('--drain needs root')
    usb = Path('/sys/class/power_supply/qcom-battmgr-usb')
    battery = Path('/sys/class/power_supply/qcom-battmgr-bat')
    if wait_for_battery and read_int(usb / 'online') == 1:
        # The measurement is meant to survive the cable being pulled, so the
        # operator can start it while the tablet is still charging and walk
        # away: nothing here needs the session that started it.
        print('waiting    up to %d s for the charger to go away' % wait_for_battery)
        deadline = monotonic() + wait_for_battery
        while monotonic() < deadline and read_int(usb / 'online') == 1:
            time.sleep(5)
    if read_int(usb / 'online') == 1:
        raise Failure('%s reports a charger; unplug it: the battery has to be '
                      'discharging for a drain measurement' % usb)

    def charge():
        return read_int(battery / 'charge_counter')

    def current():
        return read_int(battery / 'current_now')

    # Pin the state under test: the shipped policy selects `deep`, but the two
    # states cost very different amounts and the number is meaningless without
    # saying which one produced it.
    selected = 'deep' if state == 'deep' else 's2idle'
    Path('/sys/power/mem_sleep').write_text(selected)

    capacity = read_int(battery / 'capacity')
    start_charge = charge()
    full_mah = (start_charge / (capacity / 100.0)
                if capacity >= 50 and start_charge > 0 else float(DESIGN_MAH))
    dpms = Path('/sys/class/drm/card0-DSI-1/dpms')
    panel = dpms.read_text().strip() if dpms.exists() else 'unknown'
    print('battery     %d%% (%d mAh counter, %.0f mAh learned full), panel %s'
          % (capacity, start_charge, full_mah, panel))
    if panel != 'Off':
        print('note        the awake baseline includes a lit panel')

    # Awake baseline: sample the gauge, and take the counter delta over the same
    # window so the two numbers can be compared with each other.
    samples = []
    deadline = monotonic() + min(seconds, 120)
    while monotonic() < deadline:
        samples.append(abs(current()))
        time.sleep(5)
    awake_ma = sum(samples) / len(samples) / 1000.0
    awake_mah = start_charge - charge()
    awake_events = wakeup_events()

    apply_wakeup_policy()
    arm_alarm(seconds)
    before_rtc = read_int(RTC / 'since_epoch')
    before_charge = charge()
    before_capacity = read_int(battery / 'capacity')
    before_dmesg = dmesg_lines()
    alarm_left = ''
    after_irqs = {}
    try:
        subprocess.run(['sync'], check=True)
        before_sleep_irqs = interrupt_counts()
        with open('/sys/power/state', 'w') as handle:
            handle.write('mem')
        after_irqs = interrupt_counts()
        alarm_left = (RTC / 'wakealarm').read_text().strip()
    finally:
        clear_alarm()
    elapsed = read_int(RTC / 'since_epoch') - before_rtc
    slept_mah = before_charge - charge()
    slept_percent = before_capacity - read_int(battery / 'capacity')
    fired = {name: count - awake_events.get(name, 0)
             for name, count in wakeup_events().items() if count > awake_events.get(name, 0)}
    entry = [line for line in dmesg_lines()[len(before_dmesg):]
             if 'PM: suspend entry' in line]

    # charge_counter is mAh, so mAh over hours is mA.
    asleep_ma = slept_mah * 3600.0 / elapsed if elapsed else 0
    percent_per_hour = asleep_ma / full_mah * 100.0
    print('state       %s'
          % (entry[0].split('PM:')[1].strip() if entry else 'unknown'))
    print('requested   %s' % selected)
    print('awake       %6.1f mA, %d mAh over the baseline window'
          % (awake_ma, awake_mah))
    print('asleep      %6.1f mA over %d s (%d mAh, %d %%), %.2f %%/h of %.0f mAh'
          % (asleep_ma, elapsed, slept_mah, -slept_percent,
             percent_per_hour, full_mah))
    print('wakeups     %s' % (fired or 'none recorded'))
    # The fuel gauge reports charge_counter in steps of roughly 30 mAh, so a
    # window shorter than a few hours cannot resolve a few tens of mA.
    quantum = 30.0
    if slept_mah >= 0:
        print('resolution  +-%.0f mA from the gauge quantum over %d s'
              % (quantum * 3600.0 / elapsed if elapsed else 0, elapsed))

    failures = []
    if not entry or selected not in entry[0]:
        failures.append('the drain was measured in %s, not %s'
                        % (entry[0] if entry else 'no state at all', selected))
    if elapsed < seconds * 0.9:
        failures.append('the tablet slept only %d s of the requested %d s'
                        % (elapsed, seconds))
    if alarm_left not in ('', '0'):
        failures.append('the RTC alarm was still armed after the resume (%s)'
                        % alarm_left)
    if slept_mah < 0:
        failures.append('the counter went up by %d mAh: the tablet was charging'
                        % -slept_mah)
    if seconds >= 600 and slept_mah == 0:
        print('note        the counter did not move in %d s, so the drain is '
              'below the gauge\'s 1 mAh resolution' % elapsed)
    budget_ma = threshold_percent_per_hour / 100.0 * full_mah
    resolution_ma = quantum * 3600.0 / elapsed if elapsed else budget_ma
    if asleep_ma - resolution_ma > budget_ma:
        failures.append('suspended drain %.2f %%/h exceeds the %.2f %%/h budget '
                        'even after the gauge resolution (%.0f mA) is subtracted'
                        % (percent_per_hour, threshold_percent_per_hour, resolution_ma))
    elif asleep_ma > budget_ma:
        print('note        %.1f mA is over the %.0f mA budget, but inside the '
              'gauge resolution for a %d s window'
              % (asleep_ma, budget_ma, elapsed))
    if asleep_ma > awake_ma / 4.0:
        failures.append('sleeping (%.1f mA) is not clearly cheaper than awake '
                        'idle (%.1f mA)' % (asleep_ma, awake_ma))
    for failure in failures:
        print('FAIL %s' % failure)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--policy', action='store_true',
                        help='check the shipped suspend policy (offline)')
    parser.add_argument('--root', default=str(PROJECT),
                        help='tree the policy check reads (default: this repository)')
    parser.add_argument('--config',
                        help='optional kernel .config for the policy check')
    parser.add_argument('--cycle', type=int, metavar='SECONDS',
                        help='suspend for SECONDS and verify the resume')
    parser.add_argument('--state', choices=('deep', 's2idle'), default='deep',
                        help='sleep state for --cycle (default: deep)')
    parser.add_argument('--expect-wakeup', default='c400000.spmi:pmic@0:rtc@6100',
                        help='wakeup source --cycle must see fire (empty to skip)')
    parser.add_argument('--drain', type=int, metavar='SECONDS',
                        help='measure the suspended drain for SECONDS on battery')
    parser.add_argument('--drain-state', choices=('deep', 's2idle'), default='deep',
                        help='sleep state for --drain (default: deep)')
    parser.add_argument('--max-drain-percent-per-hour', type=float, default=1.0,
                        help='budget for --drain (default: 1.0 %%/h)')
    parser.add_argument('--wait-for-battery', type=int, default=0, metavar='SECONDS',
                        help='before --drain, wait this long for the charger to '
                             'be unplugged (default: 0, fail instead)')
    args = parser.parse_args()

    failures = []
    try:
        if args.policy:
            failures += check_policy(args.root, args.config)
        if args.cycle:
            with sleep_guard_held():
                failures += cycle(args.cycle, args.state, args.expect_wakeup)
        if args.drain:
            with sleep_guard_held():
                failures += drain(args.drain, args.max_drain_percent_per_hour,
                                  args.wait_for_battery, args.drain_state)
    except Failure as error:
        print('FAIL %s' % error, file=sys.stderr)
        return 2

    if not (args.policy or args.cycle or args.drain):
        parser.error('nothing to do: pass --policy, --cycle or --drain')

    if failures:
        print('\n%d check(s) failed' % len(failures))
        return 1
    print('\nall checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
