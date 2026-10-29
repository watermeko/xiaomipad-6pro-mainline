#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Let the enrolled fingerprint satisfy PAM, so it works for sudo and for the
# desktop's privileged-action dialogs, not only for login.
#
# By default this product wires pam_fprintd into the GDM login stack only: the
# account is still authenticated by fingerprint at the greeter and the lock
# screen, but `sudo`, `pkexec` and every polkit password dialog still demand the
# Linux password.  Running this script adds the standard Ubuntu pam-config, which
# puts pam_fprintd at the top of common-auth:
#
#   auth [success=3 default=ignore] pam_fprintd.so max-tries=1 timeout=10
#
# `default=ignore` is what makes this safe: a failed or absent fingerprint falls
# through to the password modules, so the password never stops working.  What it
# does mean is that whoever can present an enrolled finger can also sudo - that
# is the point, and it is a decision about this device's threat model.
#
#   sh enable-fingerprint-pam.sh            # enable
#   sh enable-fingerprint-pam.sh --revert   # back to password-only
#   sh enable-fingerprint-pam.sh --dry-run  # show the stack, change nothing
#
# Ubuntu's pam-auth-update owns common-auth, so this does not edit that file
# directly: it toggles the profile and lets the tool regenerate, which keeps the
# file in the form the distribution expects to manage.

set -eu

mode=enable
for arg in "$@"; do
	case $arg in
	--revert) mode=revert ;;
	--dry-run) mode=dry ;;
	*) printf '%s: unknown argument: %s\n' "${0##*/}" "$arg" >&2; exit 2 ;;
	esac
done

die() { printf '%s: %s\n' "${0##*/}" "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die 'root is required (sudo)'
[ -f /usr/share/pam-configs/fprintd ] ||
	die 'libpam-fprintd is not installed, so there is nothing to enable'
[ -f /usr/lib/aarch64-linux-gnu/security/pam_fprintd.so ] ||
	die 'pam_fprintd.so is missing; install libpam-fprintd'

show() {
	printf 'common-auth auth stack:\n'
	grep -E '^auth' /etc/pam.d/common-auth | sed 's/^/  /'
}

case $mode in
dry)
	show
	printf '\nFingerprint for PAM is %s.\n' \
		"$(grep -q 'pam_fprintd' /etc/pam.d/common-auth && echo enabled || echo disabled)"
	;;
enable)
	if grep -q 'pam_fprintd' /etc/pam.d/common-auth; then
		printf 'already enabled; nothing to do\n'
		show
		exit 0
	fi
	# A copy the operator can restore by hand if the stack ever looks wrong.
	backup=/var/backups/common-auth.before-fprintd
	[ -e "$backup" ] || { mkdir -p "${backup%/*}"; cp -p /etc/pam.d/common-auth "$backup"; }
	DEBIAN_FRONTEND=noninteractive pam-auth-update --enable fprintd
	grep -q 'pam_fprintd' /etc/pam.d/common-auth ||
		die 'pam-auth-update did not add pam_fprintd; restore '$backup
	printf 'enabled. The password still works when no finger is presented.\n'
	show
	;;
revert)
	if ! grep -q 'pam_fprintd' /etc/pam.d/common-auth; then
		printf 'not enabled; nothing to do\n'
		exit 0
	fi
	DEBIAN_FRONTEND=noninteractive pam-auth-update --disable fprintd
	if grep -q 'pam_fprintd' /etc/pam.d/common-auth; then
		die 'pam-auth-update did not remove pam_fprintd'
	fi
	printf 'reverted; PAM asks for the password again.\n'
	show
	;;
esac