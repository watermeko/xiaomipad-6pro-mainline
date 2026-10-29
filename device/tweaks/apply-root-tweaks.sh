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
mask_user() {
	# Read the tree's own list when it is there (a real system), and the staged
	# payload otherwise (a --dry-run before anything is installed).
	trim=$root/usr/share/liuqin/root-trim.txt
	[ -f "$trim" ] || trim=$here/payload/usr/share/liuqin/root-trim.txt
	[ -f "$trim" ] || { say 'no trim list, nothing to mask per user'; return 0; }
	entries=$(awk '
		$0 == "[mask-user]" { inside = 1; next }
		/^\[/ { inside = 0 }
		inside && $0 !~ /^[[:space:]]*(#|$)/ { print $1 }
	' "$trim")
	[ -n "$entries" ] || { say 'the trim list has no [mask-user] entries'; return 0; }

	if [ "$dry_run" = 1 ]; then
		printf '%s\n' "$entries" | while read -r entry; do
			say "would mask per user: $entry"
		done
		return 0
	fi
	# The caller must name the account; guessing would mask units in the wrong
	# session on a multi-user tablet.
	[ -n "$user_name" ] || die '--no-user was not given but no user account was named'
	uid=$(sed -n "s/^$user_name:x:\([0-9]*\):.*/\1/p" "$root/etc/passwd")
	[ -n "$uid" ] || die "no such account in this tree: $user_name"
	[ -d "$root/home/$user_name" ] || die "the account has no home directory: $user_name"

	units=
	extensions=
	for entry in $entries; do
		case $entry in
		gsd:* | gvfs:*) units="$units ${entry#*:}" ;;
		extension:*) extensions="$extensions ${entry#*:}" ;;
		*) die "unrecognised [mask-user] entry: $entry" ;;
		esac
	done

	if [ -n "$units" ]; then
		# A symlink to /dev/null in the user's unit directory is the same mask
		# systemd applies for a user unit; no daemon has to be running for it to
		# take effect on the next login.
		say "masking per-user units for $user_name:$units"
		for unit in $units; do
			dst=$root/home/$user_name/.config/systemd/user/$unit
			mkdir -p "$(dirname -- "$dst")"
			tmp=$dst.liuqin-tweaks.$$
			ln -sfn /dev/null "$tmp"
			mv -f "$tmp" "$dst"
			[ "$(readlink "$dst")" = /dev/null ] || die "user mask did not land: $dst"
		done
	fi

	if [ -n "$extensions" ]; then
		# Extensions are not systemd units: GNOME Shell owns the list in dconf.
		# Write it as a dconf keyfile the system reads on login, so the choice
		# does not depend on a running shell here.
		say "disabling extensions for $user_name:$extensions"
		# dconf keyfiles want a GVariant list literal of quoted strings:
		#   ['uuid', 'uuid']
		# The quoting is done with printf and a single-quote character held in a
		# variable, so no shell layer interprets it.
		q=\'
		list=$(for uuid in $extensions; do printf "%s%s%s, " "$q" "$uuid" "$q"; done)
		# A user-only run cannot write /etc/dconf (root-owned), and does not need
		# to: the account's own dconf profile is read first and is per-account
		# by construction.  The system-wide key is what the package writes so
		# that accounts created later inherit it.
		if [ "$skip_system" = 1 ]; then
			keyfile=$root/home/$user_name/.config/dconf/db/liuqin-tweaks
			mkdir -p "$(dirname -- "$keyfile")"
			printf 'user-db:user\nfile-db:/home/%s/.config/dconf/db/liuqin-tweaks\n' \
				"$user_name" >"$root/home/$user_name/.config/dconf/user"
			chmod 0644 "$root/home/$user_name/.config/dconf/user"
		else
			keyfile=$root/etc/dconf/db/local.d/10-liuqin-disabled-extensions
			mkdir -p "$(dirname -- "$keyfile")"
		fi
		cat >"$keyfile" <<EOF
# Written by apply-root-tweaks.sh from the [mask-user] section of
# /usr/share/liuqin/root-trim.txt.  Disabling an extension is the only way to
# stop a Shell extension without editing its schema; the cost is in the
# section's comment.
[org/gnome/shell]
disabled-extensions=[${list%, }]
EOF
		chmod 0644 "$keyfile"
		grep -q 'disabled-extensions' "$keyfile" || die 'the dconf keyfile did not land'
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
