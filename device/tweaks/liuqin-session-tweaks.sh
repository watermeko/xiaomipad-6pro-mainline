#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Apply the per-account part of this product's tweaks in a live session.
#
# Why this exists: device/configs/liuqin-root-trim.txt has a [mask-user]
# section for units and extensions that belong to a session, not to the system.
# The installer cannot apply it (the image carries no account yet) and the
# package's postinst only sees the accounts that exist at install time.  On a
# fresh install the first account is created later, by gnome-initial-setup, so
# nothing would ever apply it there.
#
# This unit is WantedBy=default.target in the user instance, so it runs once per
# login for whichever account is logging in.  It is idempotent: the masks are
# symlinks to /dev/null and the dconf key is a replacement, so a second login
# changes nothing.
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

# Only when the list actually has a per-user section; a bundle built before
# this existed has none, and this unit should not warn about that every login.
awk '$0 == "[mask-user]" || $0 == "[mask-user-phosh]" { found = 1 }
     END { exit !found }' "$trim" || exit 0

# Who is asking.  A --user unit runs as the account, so the session is this one.
account=$(id -un)
[ -n "$account" ] || exit 0
case "$(id -u)" in
0) exit 0 ;;  # never apply a session's tweaks as root
esac

# The per-account half now depends on which desktop is starting: [mask-user]
# holds the masks that are valid under GNOME Shell, [mask-user-phosh] the ones
# that are valid under Phosh.  apply-root-tweaks.sh reads XDG_CURRENT_DESKTOP
# itself, applies the section for the session that is starting and removes the
# other session's masks, so this unit only has to hand the session over.  That
# matters because Phosh lists five of the [mask-user] units as
# RequiredComponents: a mask left by a previous GNOME login makes a Phosh
# session start without them.
exec sh "$helper" / --no-purge --user-only --user "$account" --session auto
