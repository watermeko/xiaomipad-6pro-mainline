#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build the FPC1264 TOD driver (and its helper) against the target's libfprint.
#
# Two modes, because the two places this runs have different things installed:
#
#   1. dev packages installed (the original assumption):
#        CC=cc tools/build-tod.sh
#
#   2. dev packages extracted but NOT installed - the case on a tablet whose
#      runtime libfprint is pinned to an older build than the archive's dev
#      package, so installing the dev package would move the ABI the shipped
#      .so was linked against:
#        TOD_HEADERS=/tmp/toddev/usr/include \
#        TOD_LIBDIR=/tmp/todout/lib \
#        tools/build-tod.sh
#      TOD_LIBDIR must contain a libfprint-2-tod.so that resolves to the
#      installed libfprint-2-tod.so.1; the runtime ships only the versioned
#      name, so create the unversioned link there rather than in /usr/lib.
#
# The .so this produces can be packaged with
#   tools/build-liuqin-fingerprint-deb.py ... --tod <out>/libfprint-tod-fpc1264-oem.so
# which records its hash and the source it came from in CANDIDATE.json.
#
# Only the TOD is built in extracted mode: fpc-oem-print needs libfprint-2's
# pkg-config file, which is not available without installing the dev package,
# and nothing in the packaging path replaces that binary.
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
out=${OUT_DIR:-"$root/build/tod"}
cc=${CC:-cc}
headers=${TOD_HEADERS:-}
libdir=${TOD_LIBDIR:-}
mkdir -p "$out"

if [ -n "$headers" ]; then
	[ -d "$headers/libfprint-2/tod-1" ] ||
		{ echo "TOD_HEADERS has no libfprint-2/tod-1: $headers" >&2; exit 1; }
	[ -n "$libdir" ] || { echo 'TOD_LIBDIR is required with TOD_HEADERS' >&2; exit 1; }
	[ -e "$libdir/libfprint-2-tod.so" ] ||
		{ echo "TOD_LIBDIR has no libfprint-2-tod.so: $libdir" >&2; exit 1; }
	# gio and gusb still come from pkg-config; only libfprint is overridden,
	# because that is the package whose installed version differs from the
	# archive's dev version.
	"$cc" -shared -fPIC -O2 -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
		-I"$headers/libfprint-2/tod-1" -I"$headers/libfprint-2" \
		$(pkg-config --cflags gio-2.0 gusb) \
		"$root/src/fingerprint/libfprint-tod/fpc1264-oem.c" \
		-o "$out/libfprint-tod-fpc1264-oem.so" \
		-L"$libdir" -lfprint-2-tod \
		$(pkg-config --libs gio-2.0 gusb)
	(cd "$out" && sha256sum libfprint-tod-fpc1264-oem.so > SHA256SUMS)
	echo "extracted-header mode: only the TOD was built"
	exit 0
fi

"$cc" -shared -fPIC -O2 -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
    $(pkg-config --cflags libfprint-2-tod-1 gio-2.0) \
    "$root/src/fingerprint/libfprint-tod/fpc1264-oem.c" \
    -o "$out/libfprint-tod-fpc1264-oem.so" \
    $(pkg-config --libs libfprint-2-tod-1 gio-2.0)
"$cc" -O2 -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
    $(pkg-config --cflags libfprint-2 libfprint-2-tod-1) \
    "$root/src/fingerprint/libfprint-tod/fpc-oem-print.c" \
    -o "$out/fpc-oem-print" \
    $(pkg-config --libs libfprint-2 libfprint-2-tod-1)
(cd "$out" && sha256sum libfprint-tod-fpc1264-oem.so fpc-oem-print > SHA256SUMS)
