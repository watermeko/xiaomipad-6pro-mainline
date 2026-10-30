#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Stage the payload directory apply-root-tweaks.sh installs from.
#
# The files are not copied by hand: each one comes from the single place in
# this repository that owns it, so the installer image, the deb and the tree a
# developer inspects cannot hold three different versions of the same policy.
#
#   device/configs/liuqin-root-trim.txt        the reviewed trim list
#   device/root-overlay/etc/systemd/zram-generator.conf
#   device/root-overlay/usr/local/sbin/liuqin-root-trim
#   device/root-overlay/etc/udev/rules.d/90-liuqin-hide-android-volumes.rules
#   device/root-overlay/etc/tmpfiles.d/90-liuqin-thp.conf
#
# Usage: sh device/tweaks/stage-payload.sh OUT_DIR
# Writes OUT_DIR/payload/<relative path> for every installed file.
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
[ "$#" = 1 ] || { printf 'usage: %s OUT_DIR\n' "${0##*/}" >&2; exit 2; }
out=$1
# The output is either this project's build area (a developer inspecting a
# staged payload) or a staging tree the caller just created, which is how the
# initramfs build uses it.  Anything else is refused, so a mistyped argument
# cannot scatter files, and a name that already exists is never overwritten.
case $out in
"$project_root"/out/* | /tmp/*) : ;;
*)
	if [ ! -d "$out" ] || [ -n "$(ls -A "$out" 2>/dev/null)" ]; then
		printf 'stage-payload: refusing to write into %s (must be under out/ or /tmp, or an empty directory)\n' "$out" >&2
		exit 1
	fi
	;;
esac
if [ -e "$out/payload" ]; then
	printf 'stage-payload: %s/payload already exists; refusing to mix two runs\n' "$out" >&2
	exit 1
fi
mkdir -p "$out/payload"

stage() { # <source> <relative destination> <mode>
	src=$project_root/$1
	dst=$out/payload/$2
	mode=$3
	[ -f "$src" ] && [ ! -L "$src" ] || {
		printf 'stage-payload: missing input: %s\n' "$1" >&2; exit 1; }
	install -D -m "$mode" "$src" "$dst"
	# The bytes must be the bytes: a staging step that rewrote them would make
	# the manifest lie about what is installed.
	cmp -s "$src" "$dst" || {
		printf 'stage-payload: staged copy differs from %s\n' "$1" >&2; exit 1; }
}

stage device/configs/liuqin-root-trim.txt usr/share/liuqin/root-trim.txt 0644
stage device/root-overlay/etc/systemd/zram-generator.conf \
	etc/systemd/zram-generator.conf 0644
stage device/root-overlay/usr/local/sbin/liuqin-root-trim \
	usr/local/sbin/liuqin-root-trim 0755
stage device/root-overlay/etc/udev/rules.d/90-liuqin-hide-android-volumes.rules \
	etc/udev/rules.d/90-liuqin-hide-android-volumes.rules 0644
stage device/root-overlay/etc/tmpfiles.d/90-liuqin-thp.conf \
	etc/tmpfiles.d/90-liuqin-thp.conf 0644

# The staged list must still be the shape apply-root-tweaks.sh and the image
# builder read, or the trim silently becomes a no-op.
grep -qx '\[purge\]' "$out/payload/usr/share/liuqin/root-trim.txt" ||
	{ printf 'stage-payload: the trim list lost [purge]\n' >&2; exit 1; }
grep -qx '\[keep\]' "$out/payload/usr/share/liuqin/root-trim.txt" ||
	{ printf 'stage-payload: the trim list lost [keep]\n' >&2; exit 1; }
grep -qx 'compression-algorithm = zstd' "$out/payload/etc/systemd/zram-generator.conf" ||
	{ printf 'stage-payload: the zram geometry lost its compressor\n' >&2; exit 1; }
grep -q 'UDISKS_IGNORE' \
	"$out/payload/etc/udev/rules.d/90-liuqin-hide-android-volumes.rules" ||
	{ printf 'stage-payload: the volume-hiding rule lost UDISKS_IGNORE\n' >&2; exit 1; }
grep -q '^w /sys/kernel/mm/transparent_hugepage/enabled .* madvise$' \
	"$out/payload/etc/tmpfiles.d/90-liuqin-thp.conf" ||
	{ printf 'stage-payload: the huge-page policy lost its madvise pin\n' >&2; exit 1; }

printf 'stage-payload: %s files in %s\n' \
	"$(find "$out/payload" -type f | wc -l | tr -d ' ')" "$out/payload"
