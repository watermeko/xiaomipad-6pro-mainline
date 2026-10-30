#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Apply this project's root filesystem customisations to an extracted tree.
#
# One implementation, two callers:
#
#   the installer   tools/lib/install-root.sh runs this on
#                   /mnt/install/native-root straight after untar, so a fresh
#                   install is trimmed and masked before it ever boots
#   a live system   the liuqin-memory-tweaks package's postinst runs it with
#                   --no-purge on /, which installs the masks and the files an
#                   already-installed tablet is missing
#
# Nothing here needs a package manager to be correct: the masks and the zram
# configuration are files, and the purge list is the only part that needs dpkg,
# so a caller without dpkg (the installer's BusyBox userland) applies the files
# and reports what it skipped.
#
#   apply-root-tweaks.sh ROOT [--no-purge] [--dry-run]
#
# Exit status is non-zero if anything this script was asked to do failed.  It
# never leaves a mask half-written: every link is created by rename.

set -eu

die() { printf 'apply-root-tweaks: %s\n' "$*" >&2; exit 1; }
say() { printf 'apply-root-tweaks: %s\n' "$*"; }

[ "$#" -ge 1 ] || die 'usage: apply-root-tweaks.sh ROOT [--no-purge] [--dry-run]'
root=$1
shift
purge=1
user_name=
skip_user=0
skip_system=0
dry_run=0
while [ "$#" -gt 0 ]; do
	case $1 in
	--no-purge) purge=0 ;;
	--dry-run) dry_run=1 ;;
	--no-user) skip_user=1 ;;
	--user-only) skip_user=0; skip_system=1 ;;
	--user) shift; [ "$#" -gt 0 ] || die '--user needs an account name'; user_name=$1 ;;
	*) die "unknown argument: $1" ;;
	esac
	shift
done
[ -d "$root" ] || die "not a directory: $root"
case $root in
/*) : ;;
*) die "ROOT must be absolute: $root" ;;
esac

# The directory this script and its payload live in.  Both halves need it: the
# system half to install from payload/, the per-account half to read the list
# when the tree has no copy yet.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$skip_system" = 0 ]; then
# --- the files --------------------------------------------------------------
install_file() { # <rel-dest> <mode>
	rel=$1
	mode=$2
	src=$here/payload/$rel
	[ -f "$src" ] || die "payload is missing $rel"
	dst=$root/$rel
	if [ "$dry_run" = 1 ]; then
		say "would install /$rel ($mode)"
		return 0
	fi
	mkdir -p "$(dirname -- "$dst")"
	# Write beside the destination and rename: a reader either sees the old
	# file or the new one, never a truncated copy.
	tmp=$dst.liuqin-tweaks.$$
	cp "$src" "$tmp"
	chmod "$mode" "$tmp"
	mv -f "$tmp" "$dst"
}

# The zram geometry.  Without this file systemd-zram-generator does nothing, and
# without it an installed system reports no swap while the kernel supports one.
install_file etc/systemd/zram-generator.conf 0644
# The reviewed trim list, shipped so /usr/local/sbin/liuqin-root-trim on the
# installed system applies exactly what the image builder applied.
install_file usr/share/liuqin/root-trim.txt 0644
install_file usr/local/sbin/liuqin-root-trim 0755
# Hides the Android firmware partitions from udisks2, and so from Dolphin and
# any other file manager.  The rule only changes what the desktop is offered;
# the device nodes and the partitions themselves are untouched.
install_file etc/udev/rules.d/90-liuqin-hide-android-volumes.rules 0644

# --- the masks --------------------------------------------------------------
# A mask is a symlink to /dev/null in /etc/systemd.  Only a unit that is still
# shipped in /usr/lib is masked: masking a unit whose package was purged proves
# nothing and leaves a dangling link behind.
mask() { # <system|user> <unit>
	kind=$1
	unit=$2
	shipped=$root/usr/lib/systemd/$kind/$unit
	[ -e "$shipped" ] || { say "not present, no mask needed: $unit"; return 0; }
	dst=$root/etc/systemd/$kind/$unit
	if [ "$dry_run" = 1 ]; then
		say "would mask $kind/$unit"
		return 0
	fi
	mkdir -p "$(dirname -- "$dst")"
	tmp=$dst.liuqin-tweaks.$$
	ln -sfn /dev/null "$tmp"
	mv -f "$tmp" "$dst"
	[ "$(readlink "$dst")" = /dev/null ] || die "mask did not land: $dst"
}
# The update notifiers: their configuration belongs to packages the trim
# removes, but an installed tablet may still have them for the length of one
# boot, and a masked timer cannot fire in that window.
mask system apt-daily.timer
mask system apt-daily-upgrade.timer
mask system unattended-upgrades.service
mask system update-notifier-download.timer

# A udev rule is inert until udev re-reads it and the affected devices get a
# fresh event, so make the volume hiding effective now instead of at the next
# boot.  Reloading rules and re-triggering block devices does not disturb
# mounted filesystems; restarting udisks2 drops its cached view and re-probes,
# which is what removes the volumes the desktop was already showing.
reload_udev() {
	if [ "$dry_run" = 1 ]; then
		say "would reload udev rules and restart udisks2"
		return 0
	fi
	udevadm control --reload-rules ||
		say "warning: udev rules not reloaded; the volume hiding applies after a reboot"
	udevadm trigger --subsystem-match=block --action=change ||
		say "warning: block devices not re-triggered"
	systemctl try-restart udisks2.service >/dev/null 2>&1 || true
}
reload_udev

# The kernel read-only remount guard reads this marker; the marker itself is
# the installer's, so nothing to do here beyond leaving it alone.
fi

# --- per-account entries ----------------------------------------------------
# [mask-user] is different from the system masks above: these belong to a
# session, so they go into the live user's own systemd --user instance or
# ~/.config, not into /etc.  That is also why this part needs a running
# session: on the installer's extracted tree there is no user yet, and a
# second account on the tablet may legitimately want the opposite.
#
#   unit:<unit>          mask a systemd --user unit
#   autostart:<file>     hide an XDG autostart entry in ~/.config/autostart
#
# With --no-user this section is skipped, which is what the installer passes.
mask_user() {
	# Read the tree's own list when it is there (a real system), and the staged
	# payload otherwise (a --dry-run before anything is installed).
	trim=$root/usr/share/liuqin/root-trim.txt
	[ -f "$trim" ] || trim=$here/payload/usr/share/liuqin/root-trim.txt
	[ -f "$trim" ] || { say 'no trim list, nothing to apply per account'; return 0; }

	entries=$(awk '
		$0 == "[mask-user]" { inside = 1; next }
		/^\[/ { inside = 0 }
		inside && $0 !~ /^[[:space:]]*(#|$)/ { print $1 }
	' "$trim")
	[ -n "$entries" ] || { say 'no per-account entries'; return 0; }

	# The caller must name the account; guessing would write into the wrong
	# session on a multi-user tablet.
	[ -n "$user_name" ] || die '--no-user was not given but no user account was named'
	uid=$(sed -n "s/^$user_name:x:\([0-9]*\):.*/\1/p" "$root/etc/passwd")
	[ -n "$uid" ] || die "no such account in this tree: $user_name"
	[ -d "$root/home/$user_name" ] || die "the account has no home directory: $user_name"
	user_units=$root/home/$user_name/.config/systemd/user
	user_autostart=$root/home/$user_name/.config/autostart

	units=
	autostarts=
	for entry in $entries; do
		case $entry in
		unit:*) units="$units ${entry#*:}" ;;
		autostart:*) autostarts="$autostarts ${entry#*:}" ;;
		*) die "unrecognised per-account entry: $entry" ;;
		esac
	done

	if [ -n "$units" ]; then
		if [ "$dry_run" = 1 ]; then
			for unit in $units; do
				say "would mask per user: $unit"
			done
		else
			# A symlink to /dev/null in the user's unit directory is the same
			# mask systemd applies for a user unit; no daemon has to be running
			# for it to take effect on the next login.
			say "masking per-user units for $user_name:$units"
			for unit in $units; do
				dst=$user_units/$unit
				mkdir -p "$(dirname -- "$dst")"
				tmp=$dst.liuqin-tweaks.$$
				ln -sfn /dev/null "$tmp"
				mv -f "$tmp" "$dst"
				[ "$(readlink "$dst")" = /dev/null ] ||
					die "user mask did not land: $dst"
			done
		fi
	fi

	# An XDG autostart entry is hidden by a same-named desktop file in the
	# user's own autostart directory with Hidden=true; that is the only way to
	# switch one off without editing a file the package manager owns.
	if [ -n "$autostarts" ]; then
		if [ "$dry_run" = 1 ]; then
			for entry in $autostarts; do
				say "would hide autostart entry: $entry"
			done
			return 0
		fi
		say "hiding autostart entries for $user_name:$autostarts"
		for entry in $autostarts; do
			dst=$user_autostart/$entry
			mkdir -p "$(dirname -- "$dst")"
			tmp=$dst.liuqin-tweaks.$$
			{
				printf '[Desktop Entry]\n'
				printf 'Type=Application\n'
				printf 'Name=%s\n' "${entry%.desktop}"
				printf 'Hidden=true\n'
			} >"$tmp"
			mv -f "$tmp" "$dst"
			grep -qx 'Hidden=true' "$dst" ||
				die "autostart override did not land: $dst"
		done
	fi
}

# --- the trim ---------------------------------------------------------------
# Only with dpkg available and only when not asked to skip: the installer's
# BusyBox userland has no dpkg, and a live system may be trimmed already.
if [ "$purge" = 1 ]; then
	if [ -x "$root/usr/bin/dpkg-query" ] && [ "$dry_run" = 0 ]; then
		purge_list=$(awk '
			$0 == "[purge]" { inside = 1; next }
			/^\[/ { inside = 0 }
			inside && $0 !~ /^[[:space:]]*(#|$)/ { print $1 }
		' "$root/usr/share/liuqin/root-trim.txt")
		[ -n "$purge_list" ] || die 'the shipped trim list has an empty [purge] section'
		say 'removing the packages the trim list names'
		# --no-triggers: this runs inside a tree, not on the running system, so
		# service restarts and initramfs rebuilds have no meaning here.  The
		# caller's own chroot (or the next boot) runs them for real.
		chroot "$root" /usr/bin/env DEBIAN_FRONTEND=noninteractive \
			/usr/bin/dpkg --purge --no-triggers $purge_list ||
			die 'the purge failed; the tree is partially trimmed'
		say 'purge PASS'
	elif [ "$dry_run" = 1 ]; then
		say 'would purge the [purge] packages (dpkg present)'
	else
		say 'no dpkg in this tree; the trim is the package manager step of the image build'
	fi
else
	say 'purge skipped (--no-purge)'
fi

if [ "$skip_system" = 0 ]; then
# --- the snap state directories ---------------------------------------------
# A purge leaves these behind; dpkg owns none of them.
if [ "$dry_run" = 0 ]; then
	rm -rf "$root/snap" "$root/var/snap" "$root/var/lib/snapd" "$root/var/cache/snapd"
fi
fi

if [ "$skip_user" = 1 ]; then
	say 'per-account entries skipped (--no-user): no account exists in this tree yet'
else
	mask_user
fi

say 'done'
