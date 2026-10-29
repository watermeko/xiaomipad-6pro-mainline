#!/usr/bin/env python3
"""liuqin-osk - a layer-shell on-screen keyboard for the Xiaomi Pad 6 Pro.

Why this exists: KWin (Plasma Mobile 6.6) does not export
zwp_input_method_manager_v1 to ordinary clients, and Qt 6.10 refuses
client-side QtVirtualKeyboard, so both maliit-keyboard and plasma-keyboard
start up but never map a window on this device.

This keyboard avoids the compositor's input-method protocol entirely:

  * it is a wl-layer-shell surface, so it can anchor itself to the bottom
    edge, claim an exclusive zone (applications get resized above it) and
    declare keyboard_interactivity=NONE, which is what keeps the focused
    text field focused while you tap keys;
  * it types through /dev/uinput via ydotoold, so the application receives
    genuine key events;
  * Chinese input is left to fcitx5, which converts those key events with
    its pinyin engine. The 中/英 key just toggles fcitx5.

Only Latin keys are emitted; the input method does the rest.
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

APP_ID = "org.liuqin.Osk"

# evdev key codes.  A glyph maps to (code, needs_shift).
GLYPHS = {}

for _code, _letter in zip(
    [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30, 31, 32, 33, 34, 35, 36, 37,
     38, 44, 45, 46, 47, 48, 49, 50],
    "qwertyuiopasdfghjklzxcvbnm",
):
    GLYPHS[_letter] = (_code, False)
    GLYPHS[_letter.upper()] = (_code, True)

for _code, _digit in zip(range(2, 12), "1234567890"):
    GLYPHS[_digit] = (_code, False)
    GLYPHS["!@#$%^&*()"[_code - 2]] = (_code, True)

GLYPHS.update(
    {
        "-": (12, False), "_": (12, True),
        "=": (13, False), "+": (13, True),
        "[": (26, False), "{": (26, True),
        "]": (27, False), "}": (27, True),
        ";": (39, False), ":": (39, True),
        "'": (40, False), '"': (40, True),
        "`": (41, False), "~": (41, True),
        "\\": (43, False), "|": (43, True),
        ",": (51, False), "<": (51, True),
        ".": (52, False), ">": (52, True),
        "/": (53, False), "?": (53, True),
        " ": (57, False),
    }
)

SHIFT_CODE = 42
BACKSPACE = 14
ENTER = 28
CONTROL = 29

LETTER_ROWS = [
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
    ["SHIFT", "z", "x", "c", "v", "b", "n", "m", "BACKSPACE"],
    ["SYM", "IME", "SPACE", ".", "ENTER"],
]

SYMBOL_ROWS = [
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
    ["-", "/", ":", ";", "(", ")", "$", "&", "@", '"'],
    ["SHIFT", ".", ",", "?", "!", "'", "~", "_", "BACKSPACE"],
    ["ABC", "IME", "SPACE", "+", "ENTER"],
]

LABELS = {
    "SHIFT": "⇧",
    "BACKSPACE": "⌫",
    "ENTER": "⏎",
    "SPACE": "",
    "SYM": "?123",
    "ABC": "ABC",
    "IME": "中/英",
}

CSS = """
window.osk {
    background: #2b2b2e;
}
.osk-bar {
    background: #1f1f22;
    color: #d8d8dc;
    padding: 2px 8px;
}
.osk-key {
    background: #444448;
    color: #ffffff;
    border-radius: 8px;
    font-size: 22px;
    min-height: 54px;
    padding: 0;
    box-shadow: none;
    border: none;
}
.osk-key:hover { background: #52525a; }
.osk-key:active { background: #6a6a74; }
.osk-key.modifier { background: #35353a; }
.osk-key.modifier.active { background: #3d7ebd; }
.osk-key.accent { background: #3d7ebd; }
.osk-space { font-size: 16px; }
"""


def ydotoold_env():
    env = dict(os.environ)
    env.setdefault("YDOTOOL_SOCKET", "/run/ydotoold.socket")
    return env


def run(args):
    try:
        subprocess.Popen(
            args,
            env=ydotoold_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def tap(code, shift=False, ctrl=False):
    events = []
    if ctrl:
        events.append(f"{CONTROL}:1")
    if shift:
        events.append(f"{SHIFT_CODE}:1")
    events.append(f"{code}:1")
    events.append(f"{code}:0")
    if shift:
        events.append(f"{SHIFT_CODE}:0")
    if ctrl:
        events.append(f"{CONTROL}:0")
    run(["ydotool", "key", *events])


def ime_name():
    try:
        out = subprocess.run(
            ["fcitx5-remote", "-n"],
            env=ydotoold_env(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def fcitx(*args):
    """Run fcitx5-remote and wait, so the calls cannot race each other."""
    try:
        done = subprocess.run(
            ["fcitx5-remote", *args],
            env=ydotoold_env(),
            timeout=5,
            check=False,
            capture_output=True,
            text=True,
        )
        print(
            "FCITX %s rc=%d out=%r err=%r"
            % (" ".join(args), done.returncode, done.stdout.strip(), done.stderr.strip()),
            flush=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print("FCITX %s failed: %s" % (" ".join(args), exc), flush=True)


def set_ime(chinese):
    """Switch fcitx5 explicitly instead of blind toggling.

    `fcitx5-remote -t` only flips the input method on and off, leaving whatever
    engine was selected in place, and firing the three calls off concurrently
    let `-s` lose the race (observed: the engine stayed keyboard-us).  Naming
    the engine, in order, makes the 中/英 key deterministic.
    """
    if chinese:
        fcitx("-o")
        fcitx("-s", "pinyin")
    else:
        fcitx("-c")


class Keyboard(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="liuqin-osk")
        self.set_decorated(False)
        self.add_css_class("osk")

        self.shift = False
        self.symbols = False
        self.collapsed = False
        self.height = 316

        self.layer = os.environ.get("LIUQIN_OSK_LAYER", "1") not in ("0", "false")
        if self.layer:
            LayerShell.init_for_window(self)
            LayerShell.set_namespace(self, "liuqin-osk")
            LayerShell.set_layer(self, LayerShell.Layer.TOP)
            # This panel reports wl_output transform 270 and KWin maps layer-shell
            # anchors through that transform inconsistently, so the vertical edge
            # is selectable rather than hardcoded.
            edge_name = os.environ.get("LIUQIN_OSK_EDGE", "bottom").lower()
            vertical = (
                LayerShell.Edge.TOP if edge_name == "top"
                else LayerShell.Edge.BOTTOM
            )
            for edge in (vertical, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(self, edge, True)
            # Never take keyboard focus: the focused text field must keep it so
            # the injected key events reach the application.
            kb_modes = {
                "none": LayerShell.KeyboardMode.NONE,
                "ondemand": LayerShell.KeyboardMode.ON_DEMAND,
                "exclusive": LayerShell.KeyboardMode.EXCLUSIVE,
            }
            LayerShell.set_keyboard_mode(
                self,
                kb_modes.get(
                    os.environ.get("LIUQIN_OSK_KB", "none").lower(),
                    LayerShell.KeyboardMode.NONE,
                ),
            )
            # KWin pushes an exclusive-zone surface to the top of this rotated
            # output, so the zone stays 0 and the keyboard overlays the window.
            LayerShell.set_exclusive_zone(self, 0)
        else:
            # KWin never delivers pointer events to the layer surface here, even
            # with keyboard_interactivity=on_demand, so fall back to a plain
            # toplevel: the KWin rule in liuqin-osk.kwinrules pins it to the
            # bottom edge and forces "accept focus = no".
            self.set_default_size(1440, self.height)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(self.root)

        self.bar = self._build_bar()
        self.root.append(self.bar)

        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.grid.set_margin_top(6)
        # The window is anchored to the very bottom of the output, so Plasma
        # Mobile's navigation bar lies on top of the last row of keys.  Padding
        # moves the *content* up without moving the surface (a layer-shell
        # bottom margin desynchronises the input region on this rotated output).
        self.grid.set_margin_bottom(40)
        self.grid.set_margin_start(6)
        self.grid.set_margin_end(6)
        self.root.append(self.grid)

        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.grid.append(self.rows)

        if not self.layer:
            # A plain toplevel receives pointer input from KWin, unlike a
            # layer-shell surface on this compositor.  Positioning and focus
            # behaviour then come from a KWin window rule.
            print("liuqin-osk: plain window (no layer shell)", flush=True)

        self._rebuild()

        print(
            "liuqin-osk: layer_window=%s edge=%s kb_mode=%s"
            % (
                LayerShell.is_layer_window(self),
                os.environ.get("LIUQIN_OSK_EDGE", "bottom"),
                LayerShell.get_keyboard_mode(self),
            ),
            flush=True,
        )

        if os.environ.get("LIUQIN_OSK_DEBUG"):
            GLib.timeout_add(2000, self._dump_geometry)
            # Log every press with window-local coordinates: comparing that
            # with where the tap was aimed reveals the window origin, which
            # Wayland never tells the client.
            any_press = Gtk.GestureClick()
            any_press.connect("pressed", self._on_any_press)
            self.add_controller(any_press)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

    def _build_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("osk-bar")

        self.ime_label = Gtk.Label(label="fcitx5: ?")
        self.ime_label.set_hexpand(True)
        self.ime_label.set_halign(Gtk.Align.START)
        bar.append(self.ime_label)

        hide = Gtk.Button(label="▾")
        hide.add_css_class("osk-key")
        hide.add_css_class("modifier")
        hide.set_size_request(44, 28)
        hide.connect("clicked", self._on_collapse)
        bar.append(hide)
        return bar

    def _rebuild(self):
        while (child := self.rows.get_first_child()) is not None:
            self.rows.remove(child)

        self._buttons = []
        rows = SYMBOL_ROWS if self.symbols else LETTER_ROWS
        for row in rows:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            line.set_homogeneous(True)
            for name in row:
                line.append(self._make_key(name))
            self.rows.append(line)

        GLib.idle_add(self._refresh_ime)

    def _make_key(self, name):
        label = LABELS.get(name, name)
        if self.shift and name not in LABELS:
            label = name.upper()

        button = Gtk.Button(label=label)
        button.add_css_class("osk-key")
        if name in ("SHIFT", "BACKSPACE", "ENTER", "SYM", "ABC", "IME"):
            button.add_css_class("modifier")
        if name == "SHIFT" and self.shift:
            button.add_css_class("active")
        if name == "SPACE":
            button.add_css_class("osk-space")
        if name == "SPACE":
            button.set_hexpand(True)
            button.set_size_request(200, -1)

        button.connect("clicked", self._on_click, name)
        self._buttons.append((name, button))
        return button

    def _on_click(self, _button, name):
        print("CLICK %s" % name, flush=True)
        if name == "SHIFT":
            self.shift = not self.shift
            self._rebuild()
        elif name == "SYM":
            self.symbols = True
            self._rebuild()
        elif name == "ABC":
            self.symbols = False
            self._rebuild()
        elif name == "IME":
            self.chinese = not getattr(self, "chinese", False)
            set_ime(self.chinese)
            GLib.timeout_add(300, self._refresh_ime)
        elif name == "BACKSPACE":
            tap(BACKSPACE)
        elif name == "ENTER":
            tap(ENTER)
        elif name == "SPACE":
            tap(57)
        else:
            entry = GLYPHS.get(name)
            if entry is None and self.shift:
                entry = GLYPHS.get(name.upper())
            if entry is not None:
                code, needs_shift = entry
                tap(code, shift=needs_shift != self.shift)
                if self.shift and name not in LABELS:
                    self.shift = False
                    self._rebuild()

    def _refresh_ime(self):
        name = ime_name()
        active = "pinyin" in name.lower() or "libpinyin" in name.lower()
        self.ime_label.set_text(
            ("中文 · " if active else "EN · ") + name
        )
        return False

    def _on_collapse(self, _button):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.grid.set_visible(False)
            self.set_default_size(-1, 34)
        else:
            self.grid.set_visible(True)
            self.set_default_size(-1, self.height)

    def _on_any_press(self, _gesture, n_press, x, y):
        print("PANY %d %d" % (int(x), int(y)), flush=True)

    def _dump_geometry(self):
        """Report allocated key rectangles so taps can be aimed precisely."""
        from gi.repository import Graphene

        for name, button in getattr(self, "_buttons", []):
            alloc = button.get_allocation()
            ok, pt = button.compute_point(self, Graphene.Point().init(0, 0))
            if ok:
                print(
                    "KEY %-10s x=%4d y=%4d w=%4d h=%3d"
                    % (name, int(pt.x), int(pt.y), alloc.width, alloc.height),
                    flush=True,
                )
            else:
                print(
                    "KEY %-10s x=%4d y=%4d w=%4d h=%3d"
                    % (name, alloc.x, alloc.y, alloc.width, alloc.height),
                    flush=True,
                )
        return False

    def _on_key(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self._on_collapse(None)
            return True
        return False


class OskApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS.encode())
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            self.window = Keyboard(self)
        self.window.present()


def main():
    return OskApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
