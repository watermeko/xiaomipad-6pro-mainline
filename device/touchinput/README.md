# mytouchinput

An on-screen keyboard for the Xiaomi Pad 6 Pro running Plasma Mobile, written in
Go.  It appears when a text field wants input and disappears when it goes away,
and it feeds Chinese through fcitx5.

Status: **working.**  The keyboard is a `wlr-layer-shell` overlay surface: it
sits above Plasma Mobile's panels and its app launcher, it survives the task
switcher, and its toggle button stays visible and tappable in all of those
places.  See "Why a layer surface" for what went wrong with a plain window.

## The arrangement that works

```
Chrome / GTK / Qt  --text-input-v3-->  KWin  -->  fcitx5   (the Wayland input
                                                    |       method: converts to
                                                    |       pinyin and draws the
                                                    |       candidate window)
                                                    |
   mytouchinput  --uinput key events-->  KWin ------+
                 <--ProcessVisibilityEvent--  fcitx5
```

Three facts decide this:

1. **Chrome cannot use an application-side input method.**  It runs with
   `--ozone-platform=wayland --enable-wayland-ime`, so it hands its input to the
   compositor over `text-input-v3` and never looks at `GTK_IM_MODULE`.  Only a
   compositor-side input method can give it Chinese.  Verified: with fcitx5 as
   `kwinrc [Wayland] InputMethod` (the `fcitx5-wayland-launcher` entry), typing
   `nihao` into Chrome's omnibox brings up `1. 你好 2. 👌 3. 你号 ...` and space
   commits the character.
2. **fcitx5 will tell us when to appear.**  Its D-Bus Virtual Keyboard addon
   calls `ProcessVisibilityEvent` on a client that claims a specific bus name,
   which is exactly the focus signal that a layer-shell keyboard cannot get.
   This is what removes the permanently docked panel.
3. **The surface must not be a window.**  Anything that is part of the window
   stack is minimised by the shell when the launcher or the task switcher opens,
   and it can never outrank the panels.  A layer surface is neither minimised nor
   stacked among windows.

Key delivery stays on uinput (`ydotoold`): KWin routes those key events to the
input method, which is fcitx5, so the conversion happens in the normal path and
the application never receives the raw Latin keys as well.

## Why a layer surface

The keyboard used to be an ordinary `xdg_toplevel` docked by a KWin window rule
with `acceptfocus=false`, raised by a KWin script that set `keepAbove`.  Two
things were wrong with that, and they are the two bugs this change fixes:

* **The app launcher covered the toggle button.**  Plasma Mobile's fullscreen
  launcher is `plasmashell`'s own desktop window, and opening it *minimises every
  other window*.  Measured with a KWin script that dumps the window list:

  ```
  win 0 class=org.liuqin.TouchInput type=0 layer=3 keepAbove=true minimized=true  geom=0,526 1440x338
  win 1 class=plasmashell          type=1 layer=0 keepAbove=false active=true    geom=0,0 1440x900
  win 2 class=plasmashell          type=2 layer=9 keepAbove=false                geom=0,864 1440x36
  win 3 class=plasmashell          type=2 layer=9 keepAbove=false                geom=0,0 1440x22
  ```

  The keyboard was not merely behind the launcher, it was `minimized=true`, so
  nothing could bring it back by raising it.
* **The panels outranked it.**  A window rule's `keepAbove` lands the window in
  KWin's AboveLayer (`layer=3`); the Plasma panels are layer-shell `top`
  surfaces and live in TopLayer (`layer=9`).  No window rule can cross that, so
  the toggle button disappeared under anything the shell drew in the top layer.

A layer surface fixes both at once: it is not a window, so the shell never
minimises it and it never appears in the task switcher, and the `overlay` layer
is drawn above the panels.

The layer-shell surface is configured as:

| property | value | why |
|---|---|---|
| layer | `overlay` | above panels, the launcher and fullscreen applications |
| anchor | `bottom \| right` | pinned to the bottom edge, 1440 wide |
| size | `1440x338` | same geometry the window rule used to impose |
| margin | `bottom=36` | leaves Plasma Mobile's navigation bar (`0,864 1440x36`) visible and tappable |
| exclusive zone | `-1` | reserve no space; applications keep the whole screen |
| keyboard interactivity | `none` | the surface must never take focus -- the keys are injected through uinput and have to reach the field being typed into |

Verified on the device after removing both the window rule and the KWin script
(the geometry still comes out as `0,526 1440x338`, so nothing else was doing the
work):

* the toggle button is visible on top of the fullscreen app launcher;
* tapping it expands the keyboard over the launcher;
* tapping `q w e r t` typed `qwert` into the launcher's search field, i.e. focus
  stayed with the field and not with the keyboard;
* opening the task switcher and closing it leaves the button visible and
  tappable, and the keyboard no longer shows up as a task in the switcher;
* fcitx5 still gets the keys: `n i h a o` brings up `1. 你好 2. 👌 ...` above the
  keyboard.

An earlier note in `device/osk/README.md` claimed this compositor delivers no
pointer or touch input to layer surfaces.  That did not reproduce: a minimal
layer-shell client (overlay layer, `keyboard_interactivity=none`, anchored
bottom-right) receives `wl_touch` down events at the expected coordinates, with
or without acking the configure.  The layer path is therefore the default, and
`-toplevel` still selects the old window mode as a fallback.

## fcitx5's contract (read out of `libvirtualkeyboard.so`)

| item | value |
|---|---|
| bus name | `org.fcitx.Fcitx5.VirtualKeyboardBackend` |
| object path | `/org/fcitx/virtualkeyboard/impanel` |
| interface | `org.fcitx.Fcitx5.VirtualKeyboardBackend1` |

| method | signature |
|---|---|
| `ProcessVisibilityEvent` | `b` → void |
| `ProcessKeyEvent` | `j j j b j` → void |
| `NextPage`, `PrevPage` | — → void |
| `SelectCandidate` | `i` → void |
| `SetVirtualKeyboardFunctionMode` | `i` → void |

All return void; the mangled `ObjectVTablePropertyObjectMethodAdaptorIv...`
symbols give both the argument tuples and the empty return.

## What is done

* `internal/layout` — the two key layers, evdev codes, shift handling.
* `internal/inject` — key and text injection through `ydotool`, batched so a
  shifted key is one round trip.
* `internal/fcitx` — the D-Bus backend: claims the name, exports the object with
  the exact signatures above, and forwards `ProcessVisibilityEvent` into a
  channel.
* `internal/ui` — the Wayland client: a `wlr-layer-shell` overlay surface, shm
  buffers, the Material renderer, touch hit testing, and the ink animation.
  `internal/ui/layer.go` carries the handful of layer-shell requests, written by
  hand because the Wayland library has no bindings for the protocol and its
  string encoders are broken anyway (see `internal/ui/bind.go`).

## Building and running

It is a self-contained Go module:

    cd device/touchinput && GOOS=linux GOARCH=arm64 go build -buildvcs=false -o /tmp/mytouchinput .
    # -buildvcs=false keeps the binary byte-identical between builds; otherwise
    # Go stamps the git revision into it and every build hashes differently.
    adb push /tmp/mytouchinput /var/tmp/ && adb shell sudo install -m755 /var/tmp/mytouchinput /usr/local/bin/mytouchinput

`packaging/mytouchinput.service` is the user unit that starts it with the
session (`~/.config/systemd/user/`, then `systemctl --user enable --now
mytouchinput`).  It has to come up after `plasma-kwin_wayland.service`, which is
why it is a unit and not an XDG autostart entry.

Flags: `-width`/`-height` (logical size), `-scale` (buffer scale, 2 by default),
`-bottom-margin` (default 36, the navigation bar), `-layer-shell=false` for the
window fallback, `-dry-run` to log keys instead of injecting them.

## Rendering

The panel runs at scale 2: the buffer is twice the logical size and
`wl_surface.set_buffer_scale(2)` tells the compositor, so text and rounded
corners land on device pixels instead of being upscaled from a half-size
buffer.  Without it the whole keyboard looked like a blurry photo -- the screen
is 2880x1800 but the surface is 1440x338 logical.

Screen taps arrive in logical coordinates, so hit testing and the surface
geometry are unaffected.

All three shm buffers have to hold the same frame.  Converting only the buffer
about to be attached leaves the other two showing whatever they held when they
were last used -- immediately after a state change that is the *previous*
state, so the panel flickered between expanded and collapsed for as long as the
ripple kept rotating buffers, and could come to rest on a stale one.  Every
paint now converts the changed rows into all three.

## The interface

The keys are Material Design 3: `surfaceContainerHigh` key caps on a `surface`
body, violet `primary` for latched modifiers and the selected input method, and
9 px corner radii with 5 px gaps.  Pressing a key starts an ink reaction -- a
disc that grows from the touch point with a decelerate curve and fades out,
clipped to the key's rounded shape, which is what makes a tap feel acknowledged
before the character appears.  `MYTOUCHINPUT_INK_MS` stretches the animation so
a screenshot can catch it.

The ink reaction is driven from the main loop: it asks the animation for live
ripples every iteration and repaints while any exist, drawing only the keys they
touch (the static frame is composed once into `base` and copied back per
region).  Two bugs made it look like a frozen halo: the loop never asked for
live ripples at all, and there were only two buffers, so each frame took ~120 ms
and a 480 ms animation got four frames.  With three buffers and region-limited
repaints it now runs at about 60 fps -- `MYTOUCHINPUT_INK_DEBUG=1` logs every
frame's progress, radius and paint time.

The loop polls rather than chaining `wl_surface.frame` callbacks, and that poll
used to be free of charge in memory: `wl_display.sync` creates a callback proxy
per call and the client library keeps it in its object map by id, so a
roundtrip every 20 ms leaked ~8 KB/s -- 30 MB an hour, 267 MB resident after
five hours of uptime against 48 MB when fresh.  `roundtrip` now unregisters the
callback on every path (done, dispatch error, failed write), and the idle
interval is 50 ms: the same loop was burning 2.7 % of a core, now 1.1 %.  A
frame-callback design would remove the polling entirely, but that is the rewrite
this change did not need.

Icons for shift, backspace and enter are Material glyphs drawn from primitives
on a 24x24 grid, supersampled 4x and box-filtered down to size.  The Go and
DejaVu faces disagreed about those characters, and at keyboard sizes the result
was uneven.

`roundInset` used to return the *complement* of the quarter circle, which carved
the corners inwards: every key looked like it had bow-ties at its edges and the
toggle button came out as an hourglass.  That function now returns the half
width of the row inside the corner.

## Why not Gio

The obvious way to get Material Design in Go is `gioui.org`, and it does work on
this device -- a cross-compiled Material button renders fine through Mesa's
EGL/llvmpipe.  It cannot, however, be used for this keyboard: on Plasma Mobile's
KWin a Gio window cannot be placed, and Gio offers no layer-shell surface.  A
rules experiment isolated the first half: the same rule section that matched the
window (a forced opacity took effect) ignored its `position` and `size`, and the
window was opened maximised, so the keyboard could not be docked.  Gio also
cannot narrow a surface's input region, which is what lets the collapsed
keyboard pass taps through to the application.

So the window layer stays hand-written Wayland (layer-shell placement, input
regions) and the design layer is implemented directly in it.

## Showing and hiding

The keyboard does not react to focus.  It starts collapsed, showing only a
56x56 button at the bottom right with a keyboard glyph; tapping it expands the
keys, tapping it again collapses them.

Because the surface is always mapped, "collapsed" means: the rest of the surface
is painted fully transparent and the input region is narrowed to the button
alone, so taps outside it fall through to whatever is underneath.  A layer
surface with `keyboard_interactivity=none` never takes focus, so this works
without the surface being activated.

The fcitx5 backend is still registered so fcitx5 recognises the keyboard, but
`ProcessVisibilityEvent` is ignored -- fcitx5 never called it anyway.

## Known rough edges

* Glyphs: the embedded Go font has no ⇧ ⌫ ⏎, which rendered as empty boxes.
  The keyboard now loads DejaVuSans from the system when present, so the
  modifier keys read properly, and the labels avoid Han characters.
* The expanded keyboard covers the bottom 338 px of the screen.  It sits above
  everything, including dialogs and the fcitx5 candidate strip if those are ever
  placed at the bottom edge; on this device the candidate strip is drawn at the
  caret, so it stays clear.
* `ProcessVisibilityEvent` is ignored, so the keyboard never shows itself when a
  text field is focused: the toggle button is the only way in.
