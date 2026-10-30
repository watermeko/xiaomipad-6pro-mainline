#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Apply the per-account part of this product's tweaks in a live session.
#
# Why this exists: device/configs/liuqin-root-trim.txt has a [mask-user]
# section for entries that belong to a session, not to the system.  The
# installer cannot apply it (the image carries no account yet) and the
# package's postinst only sees the accounts that exist at install time.  On a
# fresh install the first account is created after the image is written, so
# nothing would ever apply it there.
#
# This unit is WantedBy=default.target in the user instance, so it runs once per
# login for whichever account is logging in.  It is idempotent: the masks are
# symlinks to /dev/null and the autostart overrides are replacements, so a
# second login changes nothing.
#
# It fails quietly when there is nothing to do, because on a tablet where the
# user removed the trim list this must not produce a failed unit.

set -eu

trim=/usr/share/liuqin/root-trim.txt
helper=/usr/lib/liuqin/apply-root-tweaks.sh

# Nothing to do, and nothing to complain about: the product was installed
# without the trim list, or the operator removed it.
[ -f "$trim" ] || exit 0
[ -x "$helper" ] || [ -x /bin/sh ] && [ -f "$helper" ] || exit 0

# Only when the list actually has a per-account section; a bundle built before
# this existed has none, and this unit should not warn about that every login.
awk '$0 == "[mask-user]" { found = 1 }
     END { exit !found }' "$trim" || exit 0

# Who is asking.  A --user unit runs as the account, so the session is this one.
account=$(id -un)
[ -n "$account" ] || exit 0
case "$(id -u)" in
0) exit 0 ;;  # never apply a session's tweaks as root
esac

exec sh "$helper" / --no-purge --user-only --user "$account"
