#!/bin/sh
# Install the on-screen keyboard: device/touchinput, a Go program that draws a
# Material Design keyboard, types through uinput (so fcitx5 does the Chinese
# conversion) and is docked at the bottom of the Plasma Mobile session by a KWin
# window rule plus a small script.
#
# Run as root on the tablet.  Idempotent.
set -eu

USER_NAME=${1:-watermeko}
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
HERE=$(cd "$(dirname "$0")" && pwd)

as_user() {
    sudo -u "$USER_NAME" env HOME="$HOME_DIR" "$@"
}

# --- the keyboard itself -----------------------------------------------------
# The source lives in device/touchinput; build it for the tablet first:
#   cd device/touchinput && GOOS=linux GOARCH=arm64 go build -buildvcs=false -o mytouchinput .
KEYBOARD="$HERE/../touchinput"
if [ ! -x "$KEYBOARD/mytouchinput" ]; then
    echo "error: $KEYBOARD/mytouchinput is missing; build it first:" >&2
    echo "  cd device/touchinput && GOOS=linux GOARCH=arm64 go build -buildvcs=false -o mytouchinput ." >&2
    exit 1
fi
install -m755 "$KEYBOARD/mytouchinput" /usr/local/bin/mytouchinput

# --- key injection ----------------------------------------------------------
# ydotoold must exist before the compositor enumerates input devices, otherwise
# the virtual keyboard is missing from the session's device list.
install -m644 "$HERE/ydotoold.service" /etc/systemd/system/ydotoold.service
systemctl daemon-reload
systemctl enable --now ydotoold.service

# --- input method wiring ----------------------------------------------------
install -m644 "$HERE/liuqin-osk.conf" /etc/environment.d/50-liuqin-osk.conf

# fcitx5 rewrites its profile on exit, so it has to be written while fcitx5 is
# stopped, and it has to contain the pinyin engine or 中/英 selects nothing.
FCITX_DIR="$HOME_DIR/.config/fcitx5"
install -d -o "$USER_NAME" -g "$USER_NAME" "$FCITX_DIR"
pkill -x fcitx5 2>/dev/null || true
sleep 1
cat > "$FCITX_DIR/profile" <<'PROFILE'
[Groups/0]
Name=Default
Default Layout=us
DefaultIM=pinyin

[Groups/0/Items/0]
Name=keyboard-us
Layout=

[Groups/0/Items/1]
Name=pinyin
Layout=

[GroupOrder]
0=Default
PROFILE
chown "$USER_NAME:$USER_NAME" "$FCITX_DIR/profile"

# --- dock it ---------------------------------------------------------------
# A window rule pins the keyboard to the bottom edge above the navigation bar
# and sets acceptfocus=false, so tapping a key never steals focus from the text
# field the injected keys have to reach.  `enabled=true` is required, and a
# types= key would abort the match.
RULES="$HOME_DIR/.config/kwinrulesrc"
if [ ! -e "$RULES" ]; then
    # Write in place: replacing the file gives it a new inode and KWin can miss
    # the change, leaving the previous rules (and the wrong app id) in memory.
    cat "$HERE/kwinrulesrc" | as_root tee "$RULES" >/dev/null
    chown "$USER_NAME:$USER_NAME" "$RULES"
elif ! grep -q 'org\.liuqin\.TouchInput' "$RULES"; then
    echo "warning: $RULES already has rules; merge device/osk/kwinrulesrc by hand" >&2
fi

# A window rule cannot force keepAbove on this compositor (measured: the window
# stayed below application windows), so a KWin script raises the keyboard and
# re-raises it whenever a window appears.
SCRIPTS="$HOME_DIR/.local/share/kwin/scripts"
install -d -o "$USER_NAME" -g "$USER_NAME" "$SCRIPTS"
rm -rf "$SCRIPTS/liuqin-osk-dock"
cp -r "$KEYBOARD/kwin-script/mytouchinput-dock" "$SCRIPTS/mytouchinput-dock"
chown -R "$USER_NAME:$USER_NAME" "$SCRIPTS"
as_user kwriteconfig6 --file kwinrc --group Plugins \
    --key mytouchinput-dockEnabled true
# fcitx5 has to be the compositor's input method: Chrome is a native Wayland
# client and only uses text-input-v3, so this is what makes Chinese work there.
as_user kwriteconfig6 --file kwinrc --group Wayland --key InputMethod \
    /usr/share/applications/fcitx5-wayland-launcher.desktop

# --- session startup --------------------------------------------------------
# systemd user units rather than XDG autostart: the keyboard has to start after
# the compositor, and plain autostart also raced it at login.
UNITS="$HOME_DIR/.config/systemd/user"
install -d -o "$USER_NAME" -g "$USER_NAME" "$UNITS"
install -m644 -o "$USER_NAME" -g "$USER_NAME" \
    "$KEYBOARD/packaging/mytouchinput.service" "$UNITS/mytouchinput.service"
# Retire the Python keyboard this replaced, if it is still installed.
as_user systemctl --user disable --now liuqin-osk.service >/dev/null 2>&1 || true
rm -f "$UNITS/liuqin-osk.service" /usr/local/bin/liuqin-osk \
      /usr/local/share/liuqin-osk/liuqin-osk.py
install -m644 -o "$USER_NAME" -g "$USER_NAME" \
    "$HERE/fcitx5.service" "$UNITS/fcitx5.service"
rm -f "$HOME_DIR/.config/autostart/liuqin-osk.desktop" \
      "$HOME_DIR/.config/autostart/fcitx5.desktop" \
      "$HOME_DIR/.config/autostart/mytouchinput.desktop"

# --- UI-test tooling --------------------------------------------------------
install -m755 "$HERE/liuqin-tapd" /usr/local/bin/liuqin-tapd
install -m755 "$HERE/liuqin-tap" /usr/local/bin/liuqin-tap
install -m755 "$HERE/liuqin-stap" /usr/local/bin/liuqin-stap
install -m644 "$HERE/99-liuqin-tap.rules" /etc/udev/rules.d/99-liuqin-tap.rules
udevadm control --reload-rules || true

# --- apply ------------------------------------------------------------------
as_user systemctl --user daemon-reload || true
as_user systemctl --user enable --now mytouchinput.service fcitx5.service || true
as_user qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true

echo "liuqin-osk installed for $USER_NAME."
echo "Check it with:  sudo liuqin-tapd & liuqin-stap 433 797   # the 中/英 key"