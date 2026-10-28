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
dry_run=0
for arg in "$@"; do
	case $arg in
	--no-purge) purge=0 ;;
	--dry-run) dry_run=1 ;;
	*) die "unknown argument: $arg" ;;
	esac
done
[ -d "$root" ] || die "not a directory: $root"
case $root in
/*) : ;;
*) die "ROOT must be absolute: $root" ;;
esac

# --- the files --------------------------------------------------------------
# Each entry: destination relative to ROOT, the source's *name* within this
# script's own directory.  They are shipped next to this script by whichever
# package or installer image carries it, so this file has one copy of the
# policy and no second place to drift from.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

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

# --- the snap state directories ---------------------------------------------
# A purge leaves these behind; dpkg owns none of them.
if [ "$dry_run" = 0 ]; then
	rm -rf "$root/snap" "$root/var/snap" "$root/var/lib/snapd" "$root/var/cache/snapd"
fi

say 'done'
