# liuqin-osk — touch keyboard with Chinese input

Working. Tapping the keys types through `/dev/uinput`; fcitx5 converts to
pinyin and the candidates appear above the search field.

## Why not one of the packaged keyboards

The tablet runs Plasma Mobile on KWin 6.6.  The stock on-screen keyboards
cannot produce Chinese here:

1. `kwin_wayland` exports only `zwp_text_input_manager_v1/v2/v3` — no
   `zwp_input_method_manager_v1` for ordinary clients (`wayland-info`), so a
   normal client cannot send synthetic keys.
2. `maliit-keyboard` and `plasma-keyboard` run through KWin's private
   input-method socket.  They can only commit finished strings, which bypasses
   an application-side input method, and neither ships a pinyin engine.
3. Qt 6.10 refuses the client-side virtual keyboard outright
   (`qtvirtualkeyboard currently is not supported at client-side, use
   QT_IM_MODULES=qtvirtualkeyboard at compositor-side`).

`fcitx5` does convert key events correctly here, so the keyboard only has to
emit real key events.

## How it works

* `liuqin-osk.py` — GTK4 keyboard.  Keys call `ydotool`, which writes through
  `/dev/uinput`, so applications receive genuine key events and their own IM
  module (`QT_IM_MODULE=fcitx`) converts them.  It only ever emits Latin keys.
* `中/英` switches fcitx5 to an explicit engine (`fcitx5-remote -o` then
  `-s pinyin`, or `-c` for English), sequentially — firing those three calls
  off concurrently let `-s` lose the race and the engine stayed on
  `keyboard-us`.
* `ydotoold.service` starts ydotoold from boot; the compositor must see the
  virtual keyboard when it enumerates input devices.
* `kwinrulesrc` docks the window and sets `acceptfocus=false`, so tapping a key
  never steals focus from the text field that has to receive the key events.
* `kwin-script/liuqin-osk-dock` re-raises the keyboard (`keepAbove`) whenever a
  window appears: a window rule cannot force `keepabove` on this compositor
  (measured — the window stayed under application windows) while a KWin script
  can.
* `liuqin-osk.service` / `fcitx5.service` — systemd user units rather than XDG
  autostart, because the keyboard has to start *after* `plasma-kwin_wayland`
  and plain autostart raced it.

## Presentation mode

`LIUQIN_OSK_LAYER=0` (what the unit sets) makes the keyboard an ordinary
toplevel.  The layer-shell variant is unusable: measured with window-local
press logging, a `wl-layer-shell` surface receives **no** pointer or touch
events on this compositor, with `keyboard_interactivity` `none` or `on_demand`.

## Verified

* Docked: `frameGeometry = 0,526 1440x338`, flush with the bottom edge and
  clear of the navigation bar at `0,864 1440x36`; `keepAbove = true`;
  `skipTaskbar = true`.
* Survives a session restart: `liuqin-osk.service` and `fcitx5.service` both
  come up active and the window is docked again.
* Tapping `中/英` moves fcitx5 to the `pinyin` engine, tapping `n i h a o`
  brings up the candidate list (`1. 你好 …`) and space commits `你好` into the
  focused text field — done entirely by tapping the on-screen keyboard.

## Gotchas worth remembering

* A `types=` key in a window rule silently aborts the whole match, and a rule
  needs `enabled=true` or it is ignored.  Both cost an afternoon.
* `Qt`, `QRectF`, `move()` and `resize()` do not exist in KWin scripting, so a
  script cannot set geometry; `wantsInput` is read-only.  Geometry has to come
  from the rule, `keepAbove` from the script.
* `fcitx5 -d` under `Type=simple` makes systemd tear the cgroup down when the
  daemonising parent exits; use `--replace` without `-d`.
* fcitx5 only accepts `-s pinyin` when an input context is active; with nothing
  focused `fcitx5-remote -n` legitimately returns an empty string.
* `sed -i` on a log file that a running process holds open sends that process's
  later output to the unlinked inode — apparent "logging stopped".

## UI-test tooling

Synthetic taps on this panel are awkward enough that they need dedicated tools:

* `liuqin-tapd` — keeps **one** uinput touchscreen alive.  A device created per
  tap only works for the first couple of taps; after that libinput stops
  accepting the recreated device.  It needs `INPUT_PROP_DIRECT` (`PROP=2`), and
   `99-liuqin-tap.rules` puts it into the same `LIBINPUT_DEVICE_GROUP` as the
  real panel — without that group the compositor has no output mapping for it
  and drops every event.
* `liuqin-tap <x> <y>` — FIFO client, in the device's rotated axis space.
* `liuqin-stap <x> <y>` — taps at *logical screen* coordinates by undoing the
  panel's `wl_output transform 270`:
  `tap_x = (899 - y) / 0.623`, `tap_y = x / 1.598`.
* `LIUQIN_OSK_DEBUG=1` on the keyboard prints each key's allocated rectangle,
  `CLICK <name>` per handler, `PANY <x> <y>` per press, and `FCITX <args> rc=…`
  for every input-method call.

## Install

```sh
sudo ./install.sh watermeko
```

Installs everything above, enables the units, writes the fcitx5 profile with
`DefaultIM=pinyin`, and clears `kwinrc [Wayland] InputMethod` so KWin does not
launch a competing keyboard.

## Files

| file | purpose |
|---|---|
| `liuqin-osk.py` | the keyboard |
| `liuqin-osk` | wrapper preloading `libgtk4-layer-shell.so.0` |
| `liuqin-osk.service` | session unit, `After=plasma-kwin_wayland.service` |
| `fcitx5.service` | session unit for the input method |
| `liuqin-osk.conf` | `/etc/environment.d`: `QT_IM_MODULE=fcitx` etc. |
| `kwinrulesrc` | docks the window, `acceptfocus=false`, `enabled=true` |
| `kwin-script/liuqin-osk-dock/` | raises the keyboard above applications |
| `ydotoold.service` | system unit, `Before=display-manager.service` |
| `99-liuqin-tap.rules` | puts the test touchscreen in the panel's device group |
| `liuqin-tapd`, `liuqin-tap`, `liuqin-stap` | UI-test tap tooling |
| `install.sh` | idempotent installer |