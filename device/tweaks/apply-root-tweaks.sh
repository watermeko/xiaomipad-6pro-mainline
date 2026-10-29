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
# Which desktop session the per-account half is being applied for.  The masks
# in [mask-user] are a GNOME Shell optimisation and the ones in
# [mask-user-phosh] are Phosh-specific; applying either set under the other
# session is what broke Phosh's RequiredComponents.  auto reads
# XDG_CURRENT_DESKTOP, which is "ubuntu:GNOME" or "Phosh:GNOME" here.
session=auto
skip_system=0
dry_run=0
while [ "$#" -gt 0 ]; do
	case $1 in
	--no-purge) purge=0 ;;
	--dry-run) dry_run=1 ;;
	--no-user) skip_user=1 ;;
	--session) shift; [ "$#" -gt 0 ] || die '--session needs a value'; session=$1 ;;
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
# Hides the Android firmware partitions from udisks2, and so from the dock and
# Files.  The rule only changes what the desktop is offered; the device nodes
# and the partitions themselves are untouched.
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
mask system colord.service
mask user localsearch-3.service
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

# --- per-user units and extensions ------------------------------------------
# [mask-user] is different from the system masks above: these belong to a
# session, so they go into the live user's systemd --user instance and the
# user's dconf, not into /etc.  That is also why this part needs a running
# session: on the installer's extracted tree there is no user yet, and a
# second account on the tablet may legitimately want them.
#
#   gsd:<unit>         mask a GNOME settings-daemon unit
#   gvfs:<unit>        mask a gvfs volume monitor
#   extension:<uuid>   disable a GNOME Shell extension
#
# With --no-user this section is skipped, which is what the installer passes.
case $session in
auto)
	case ${XDG_CURRENT_DESKTOP:-} in
	*Phosh*) session=phosh ;;
	*GNOME*) session=gnome ;;
	*) session=other ;;
	esac
	;;
gnome | phosh | other) : ;;
*) die "--session must be auto, gnome, phosh or other" ;;
esac

mask_user() {
	# Read the tree's own list when it is there (a real system), and the staged
	# payload otherwise (a --dry-run before anything is installed).
	trim=$root/usr/share/liuqin/root-trim.txt
	[ -f "$trim" ] || trim=$here/payload/usr/share/liuqin/root-trim.txt
	[ -f "$trim" ] || { say 'no trim list, nothing to mask per user'; return 0; }

	section_entries() { # <section>
		awk -v want="$1" '
			$0 == "[" want "]" { inside = 1; next }
			/^\[/ { inside = 0 }
			inside && $0 !~ /^[[:space:]]*(#|$)/ { print $1 }
		' "$trim"
	}

	# The section that belongs to the session that is starting, and the one
	# that belongs to the other session.  Anything the other session asked for
	# is removed here, so switching desktops cannot leave a stale mask behind -
	# which is exactly how a Phosh session ended up starting without the
	# RequiredComponents that [mask-user] masks.
	case $session in
	gnome) active=mask-user inactive=mask-user-phosh ;;
	phosh) active=mask-user-phosh inactive=mask-user ;;
	*) active= inactive='mask-user mask-user-phosh' ;;
	esac

	entries=
	for section in $active; do
		entries="$entries $(section_entries "$section")"
	done
	stale=
	for section in $inactive; do
		stale="$stale $(section_entries "$section")"
	done
	[ -n "$entries$stale" ] ||
		{ say "no per-user entries for a $session session"; return 0; }

	# The caller must name the account; guessing would mask units in the wrong
	# session on a multi-user tablet.
	[ -n "$user_name" ] || die '--no-user was not given but no user account was named'
	uid=$(sed -n "s/^$user_name:x:\([0-9]*\):.*/\1/p" "$root/etc/passwd")
	[ -n "$uid" ] || die "no such account in this tree: $user_name"
	[ -d "$root/home/$user_name" ] || die "the account has no home directory: $user_name"
	user_units=$root/home/$user_name/.config/systemd/user

	units=
	extensions=
	for entry in $entries; do
		case $entry in
		gsd:* | gvfs:* | unit:*) units="$units ${entry#*:}" ;;
		extension:*) extensions="$extensions ${entry#*:}" ;;
		*) die "unrecognised entry for a $session session: $entry" ;;
		esac
	done

	# Remove what the other session asked for.  Only links this product wrote
	# are touched: a mask the account made for its own reasons also points at
	# /dev/null, so the names come from the trim list rather than from whatever
	# happens to be in the directory.
	for entry in $stale; do
		case $entry in
		gsd:* | gvfs:* | unit:*) ;;
		*) continue ;;
		esac
		unit=${entry#*:}
		case " $units " in *" $unit "*) continue ;; esac
		dst=$user_units/$unit
		if [ -L "$dst" ] && [ "$(readlink "$dst")" = /dev/null ]; then
			if [ "$dry_run" = 1 ]; then
				say "would unmask per user (not used by $session): $unit"
			else
				rm -f "$dst"
				say "unmasked per user (not used by $session): $unit"
			fi
		fi
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
			say "masking per-user units for $user_name ($session):$units"
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

	# Phosh's on-screen keyboard suppresses itself whenever an input device with
	# keyboard capability is present (sm.puri.phosh.osk ignore-hw-keyboards).
	# On this tablet the pogo keyboard keeps enumerating "Xiaomi Keyboard" even
	# when it is folded behind the panel - the hall switch reports tablet mode at
	# the same time - so Phosh concluded there was a keyboard and never showed
	# the on-screen one: with the tablet in hand, no text field could be typed
	# into at all.  Turning the key on makes the keyboard follow text input
	# instead of device presence.
	phosh_osk=
	if [ "$session" = phosh ]; then
		phosh_osk=1
	fi

	if [ -n "$extensions" ] || [ -n "$phosh_osk" ]; then
		if [ "$dry_run" = 1 ]; then
			for uuid in $extensions; do
				say "would disable extension: $uuid"
			done
			if [ -n "$phosh_osk" ]; then
				say 'would make the on-screen keyboard ignore the pogo keyboard'
			fi
			return 0
		fi

		if [ "$skip_system" = 1 ]; then
			# A live session: write the keys through dconf.  An earlier version
			# wrote a text keyfile to ~/.config/dconf/db/liuqin-tweaks and pointed
			# a profile at it, but file-db: only accepts databases built by
			# `dconf compile`, so the text file was never read and none of these
			# settings ever took effect.  dconf write needs no profile and reaches
			# the database the session is already using.
			if [ -n "$extensions" ]; then
				say "disabling extensions for $user_name:$extensions"
				# GVariant list literal of quoted strings: ['uuid', 'uuid']
				q=\'
				list=$(for uuid in $extensions; do
					printf "%s%s%s, " "$q" "$uuid" "$q"
				done)
				dconf write /org/gnome/shell/disabled-extensions \
					"[${list%, }]" ||
					die 'could not write the disabled extension list'
			fi
			if [ -n "$phosh_osk" ]; then
				say 'on-screen keyboard now ignores the pogo keyboard'
				dconf write /sm/puri/phosh/osk/ignore-hw-keyboards true ||
					die 'could not write the on-screen keyboard setting'
			fi
		else
			# Staging a tree that is not running: leave the text keyfile where
			# dconf update compiles it on the target (/etc/dconf/db/local.d).
			keyfile=$root/etc/dconf/db/local.d/10-liuqin-tweaks
			mkdir -p "$(dirname -- "$keyfile")"
			{
				printf '# Written by apply-root-tweaks.sh from the per-user sections\n'
				printf '# of /usr/share/liuqin/root-trim.txt.  The reasons are in the\n'
				printf '# sections themselves.\n'
				if [ -n "$extensions" ]; then
					q=\'
					list=$(for uuid in $extensions; do
						printf "%s%s%s, " "$q" "$uuid" "$q"
					done)
					printf '\n[org/gnome/shell]\n'
					printf 'disabled-extensions=[%s]\n' "${list%, }"
				fi
				if [ -n "$phosh_osk" ]; then
					printf '\n[sm/puri/phosh/osk]\nignore-hw-keyboards=true\n'
				fi
			} >"$keyfile"
			chmod 0644 "$keyfile"
			say "staged dconf keys in /etc/dconf/db/local.d (dconf update compiles them)"
		fi
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
	say 'per-user masks skipped (--no-user): no account exists in this tree yet'
else
	mask_user
fi

say 'done'
