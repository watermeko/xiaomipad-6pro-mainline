# Xiaomi Pad 6 Pro fingerprint support

[简体中文](FINGERPRINT.zh-CN.md)

## Current status

The native Ubuntu Settings enrollment interface is implemented for the FPC1264
sensor. It uses the normal system authorization dialog and fprintd/libfprint
progress, cancellation and storage. Normal use does not require a terminal or a
separate fingerprint application.

As of 2026-10-07, native Settings enrollment has completed on the known 256 GB
test unit. Its saved template was retained through installation of the combined
DP/fingerprint kernel `6.17.0-rc1-gfe81794b5e1b` and userspace `4d6b22f`.
**Same-finger acceptance, other-finger rejection, native lock-screen unlock and
fingerprint login after an ordinary boot from tablet storage have passed.**
System authentication/session signals and the user's confirmation agree.

The v0.6.0 complete installation bundle includes these components and has passed
full installation, initial setup and user acceptance on the test unit.

## Requirements

v0.6.0 automatically supports the first local account created by initial setup
(UID 1000), without a preconfigured username. Use the exact matching kernel, FPC
module, device tree and OEM firmware. The current scope is **one finger for that account**. Kernel/module hashes and wiring
checks must not be bypassed.

A temporary RAM boot does not install a kernel for the next power-on. Fingerprint
availability after reboot requires the matching kernel and modules to be
persistently installed. That ordinary boot path has passed on this test unit.
Build and installation details are in the [component reference](../device/fingerprint/oem/README.md).

## Enroll through Ubuntu Settings

1. Open **Settings → System → Users → Fingerprint Login** for the configured
   account. Unlock Settings if the normal system dialog requests it.
2. Choose a finger and authorize enrollment in the system password dialog.
3. Follow the native scan, lift/reposition and progress instructions until the
   dialog reports completion. Cancellation waits for the ongoing operation to
   clean up before releasing the reader.

After successful enrollment, verification uses the regular Ubuntu login and
lock screen. The normal password-login stack is preserved, so password login
remains the fallback. The presence of the Settings row or a running service does
not demonstrate successful enrollment or unlock.

### One finger per account, and why

Enrolling a second finger is refused while one is stored. The desktop reports
this as **"Fingerprint device storage is full"**, which is wrong: nothing is
full, and the template is 772 KB. The real reason is in how verification works.

`pam_fprintd` asks fprintd to verify "any" enrolled print. fprintd then does one
of two things:

| prints enrolled | device implements `IDENTIFY` | what happens |
|---|---|---|
| 1 | either | verifies that one print |
| 2+ | yes | 1:N identification over the whole gallery |
| 2+ | **no** | **verifies `gallery[0]` only** |

This TOD driver does not implement 1:N identification, because the OEM runtime
matches one exported database per sensor capture. So with two enrolled fingers
the second would enroll successfully and then never match at login — a template
that only takes up space and misleads. The refusal exists to prevent that, not
to save storage. The misleading message is a bug in how the refusal is reported;
it is fixed in the driver source and ships with the next TOD rebuild.

**To use a different finger**, delete the stored one first and enroll the other:

1. **Settings → System → Users → Fingerprint Login**, then use the delete control.
2. Enroll the finger you want.

`fprintd-delete USERNAME --finger right-index-finger` does the same from a
terminal. Delete and re-enroll works in either order; the machine credential and
Gatekeeper handle in `/var/lib/liuqin-fingerprint/` are per account, so they are
reused and nothing else has to be recreated.

**To get 1:N, two things are needed**: a TOD `identify` implementation, and an
OEM runtime mode that matches several databases from one capture. The current
runtime takes exactly one (`--match-single DATABASE`), so this is a real feature
gap rather than a policy flag.

The message itself is already fixed in the driver source, and the fix is shipped
in the current package: the driver stopped using `FP_DEVICE_ERROR_DATA_FULL` for
this refusal, so the desktop shows the real reason instead of "storage is full".
Rebuilding the TOD against the tablet's own libfprint without installing a newer
dev package is described in
[the component reference](../device/fingerprint/oem/README.md#rebuilding-only-the-tod-when-the-dev-package-would-move-the-abi).

## Fingerprint for sudo and polkit

Out of the box the fingerprint authenticates the **login and lock screen only**.
`sudo`, `pkexec` and the desktop's privileged-action dialogs still ask for the
Linux password, because `pam_fprintd` is wired into the GDM stack alone.

To let the enrolled finger satisfy every PAM prompt on this tablet:

```sh
sudo sh device/tweaks/enable-fingerprint-pam.sh           # enable
sudo sh device/tweaks/enable-fingerprint-pam.sh --dry-run # inspect first
sudo sh device/tweaks/enable-fingerprint-pam.sh --revert  # password only again
```

It runs the standard `pam-auth-update --enable fprintd`, which puts
`pam_fprintd.so` at the top of `common-auth` with `default=ignore`. That means a
failed or absent fingerprint falls through to the password modules, so the
password never stops working. What changes is that a finger can now authorise
`sudo` — which is the point, and is a decision about this device's threat model.
Both `sudo` and `polkit-1` include `common-auth`, so one change covers both.

## Passwords and existing identities

The password dialog is the desktop's Polkit authorization for enrolling or
deleting a fingerprint. The provider does **not** store the Linux password. It
creates a separate, root-only random machine credential and Gatekeeper handle
for the configured account; those private files stay on this tablet. A Linux
password change therefore requires no separate fingerprint-password sync for
this native route.

Existing password-derived identities and templates are not automatically
migrated, recreated or deleted. Preserve any uncertain-creation markers rather
than attempting a credential reset. Initial credential creation writes real
Gatekeeper/RPMB state; cancellation during that short transaction finishes its
safe commit before stopping and does not proceed into fingerprint capture.
A temporary kernel does not make these operations read-only.

## Validation scope and remaining work

Native enrollment, template reload, same-finger acceptance, other-finger rejection,
native lock-screen unlock and GDM login after an ordinary reboot have passed.
Password login remains available without a separate unlock application.

Verification does not consume the old boot-local 18-hour enrollment authorization
or ask for the Linux password through the legacy helper. The reboot test started
at the regular login screen without any manual Keymaster negotiation or setup
helper. Fingerprint login does not decrypt the password-encrypted GNOME login
keyring; applications accessing its secrets may still request the keyring password.

Placement sensitivity, latency, suspend/resume, long-term reliability and
multiple fingers/accounts and fingerprint secure-storage coexistence after an
Android round trip are not established for this candidate.

## Appendix: recovery and legacy diagnostics

If fingerprint verification must be disabled while preserving private state and
password login, an administrator can stop and mask the normal daemon:

~~~sh
sudo systemctl mask --now fprintd.service
~~~

Diagnostic details are available from `fprintd.service` and
`liuqin-fpc-stable-module.service`. Share only status/phase information, never
passwords, random credentials, handles, tokens, templates or calibration.

`acceptance.py`, the old terminal launcher and `user_credentials.py` remain
internal tools for the legacy development-helper interface. They are not the
normal native entry; native installation removes their application-menu launchers.
The old `--sync-password` command applies only to password-derived legacy
identities. Do not run legacy create or random probe-UID operations as native
preflight checks. See the [component reference](../device/fingerprint/oem/README.md)
for that distinction and the matching-package requirements.
