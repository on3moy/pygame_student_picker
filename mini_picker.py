# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["pygame>=2.6.1", "pynput>=1.7"]
# ///
"""
Mini student picker - a small always-on-top window that shows one name.

Built for presenting: it floats above your slides so the class can see who
got called, and a single controller button rolls the next name. Everything
you would want to change lives in two JSON files next to this script:

    mini_config.json   which roster, which controller buttons, where the
                       window sits, how long the names shuffle. The roster is
                       re-read while running, so edits to it land live.
    themes/*.json      colors, fonts, window size - one file per theme

In normal use there is one button to press: NEXT. Nobody repeats until
everyone has had a turn, and when the round is done the pool refills itself.

Controls:
    X     / bound controller button   NEXT - call a student. Both work while
                                      another window has focus: the pad through
                                      SDL background events, X through a global
                                      hotkey (see mini_config.json).
    T     / bound controller button   cycle to the next theme in themes/
    R     / bound controller button   start a fresh round early
    L                                 map controller buttons - walks through
                                      pick / theme / reset, press the pad
                                      button you want for each (S skips one,
                                      Esc cancels)
    H                                 show the current button mapping
    F                                 load a different roster .txt
    O                                 toggle always-on-top
    Left-drag                         move the window
    Drag the corner grip              resize (everything scales with it)
    + / - / 0                         grow / shrink / reset the size
    Esc / window close                quit

Run:
    python mini_picker.py
    python mini_picker.py path/to/roster.txt      # override the roster once
    python mini_picker.py --theme dracula
"""

import json
import math
import os
import random
import sys

# SDL delivers joystick events only to a window that has input focus, and the
# picker never has it while you present - you click the slides to drive them,
# which is exactly when the pad has to work. This opts into background events.
# It must be set before pygame.init(), because SDL reads the hint when the
# joystick subsystem starts; setdefault so the environment can still override.
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame
from pygame._sdl2 import video

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:      # the keyboard backup is optional; the pad still works
    pynput_keyboard = None

# Posted from pynput's thread when the global hotkey fires. The callback does
# nothing but post this - picker state belongs to the main loop.
HOTKEY_NEXT = pygame.USEREVENT + 1


def log(message):
    """print() that cannot take the picker down.

    run_picker.cmd starts the picker with pythonw.exe, which can leave
    sys.stdout as None; printing then raises and kills the app on a path that
    was only trying to warn about something minor.
    """
    try:
        print(message)
    except (AttributeError, OSError, ValueError):
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "mini_config.json")
THEMES_DIR = os.path.join(BASE_DIR, "themes")

IDLE, SPINNING, RESULT = "idle", "spinning", "result"

SPIN_MIN_INTERVAL = 40    # ms between name swaps at the start of a spin
SPIN_MAX_INTERVAL = 190   # ms between name swaps at the end

# A full-screen slideshow (PowerPoint, Keynote, a browser in presentation mode)
# makes itself topmost when it starts, which drops us behind it. Setting the
# flag once at startup is not enough, so re-assert it on this interval.
TOPMOST_REASSERT_MS = 2000

# Shown when the last student in a round is called; the pool refills itself.
ROUND_OVER_MESSAGE = "That's everyone - starting a fresh round"

# How often to re-stat the roster file so edits show up without a restart.
ROSTER_POLL_MS = 1500

# Resizing. The window is borderless, so there is no OS-drawn resize edge; we
# draw our own grip in the bottom-right corner and drag that instead.
MIN_WIN_W, MIN_WIN_H = 220, 90
GRIP_BASE = 18            # grip square in theme-design pixels, scaled at runtime
RESIZE_STEP = 1.1         # keyboard / ctrl-wheel zoom per press

# Window tweaks (opacity, borderless, move, resize) are best-effort: SDL raises
# on backends that do not support them, and pygame.error and the _sdl2 error
# class are separate types that both derive from RuntimeError.
WINDOW_ERRORS = (AttributeError, TypeError, ValueError, RuntimeError)

# Standard SDL pad layout, used only to label buttons in messages.
BUTTON_NAMES = {
    0: "A", 1: "B", 2: "X", 3: "Y", 4: "BACK", 5: "GUIDE", 6: "START",
    7: "L-STICK", 8: "R-STICK", 9: "LB", 10: "RB",
    11: "D-UP", 12: "D-DOWN", 13: "D-LEFT", 14: "D-RIGHT",
}

# (config key, wizard prompt, short name) in the order the L wizard asks.
# NEXT is the only button the picker actually needs: the pool refills itself,
# so reset is a convenience rather than part of the normal flow.
MAPPABLE = (("pick_button", "call the NEXT student", "Next"),
            ("theme_button", "change the THEME", "Theme"),
            ("reset_button", "RESET the round early", "Reset"))


def hotkey_spec(text):
    """'ctrl+space' -> '<ctrl>+<space>', the form GlobalHotKeys parses.

    Single printable characters stay bare ('x' stays 'x'); named keys and
    modifiers get wrapped.
    """
    parts = []
    for part in str(text).lower().split("+"):
        part = part.strip()
        if not part:
            continue
        parts.append(part if len(part) == 1 and part.isalnum() else f"<{part}>")
    return "+".join(parts)


def button_label(index):
    """'Y (3)' for a known pad button, '(3)' for one we have no name for."""
    if index is None:
        return "unmapped"
    name = BUTTON_NAMES.get(index)
    return f"{name} ({index})" if name else f"button {index}"


# --------------------------------------------------------------------------
# config + theme loading
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "students_file": "students.txt",
    "theme": "experimental",
    "controller": {"pick_button": 10, "theme_button": 3, "reset_button": 2,
                   "joystick_index": 0},
    "window": {"x": None, "y": None, "width": None, "height": None,
               "always_on_top": True},
    "hotkey": {"next": "x", "enabled": True},
    "spin_ms": 1400,
    "no_repeats": True,
}

DEFAULT_THEME = {
    "name": "Fallback",
    "window": {"width": 560, "height": 190, "borderless": True, "opacity": 1.0,
               "padding": 14, "corner_radius": 10, "border_width": 3},
    "font": {"candidates": ["Segoe UI", "Arial", "sans"],
             "name_size": 50, "small_size": 15, "bold": True,
             "uppercase": False, "fill_window": True, "fill": 0.94},
    "colors": {"bg_top": [12, 12, 16], "bg_bottom": [24, 24, 30],
               "border": [200, 200, 210], "border_flash": [255, 255, 255],
               "name": [240, 240, 245], "name_winner": [255, 255, 255],
               "muted": [130, 130, 145], "glow": [200, 200, 210]},
    "glow": {"enabled": False, "radius": 0, "alpha": 0},
    "footer": {"show_counter": True},
    "background": {"gradient": True,
                   "spotlight": {"enabled": False},
                   "rays": {"enabled": False},
                   "motes": {"enabled": False},
                   "vignette": {"enabled": False},
                   "grid": {"enabled": False},
                   "scanlines": {"enabled": False},
                   "scanbar": {"enabled": False}},
    "name_fx": {"glitch": {"enabled": False}},
}


def _merge(base, override):
    """Recursively overlay `override` onto a copy of `base`, ignoring _comment keys."""
    out = dict(base)
    for key, value in override.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config():
    """Read mini_config.json, filling in anything missing from the defaults."""
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return _merge(DEFAULT_CONFIG, json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[mini_picker] could not read mini_config.json ({exc}); using defaults")
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    """Write settings back, preserving the _comment documentation already in the file."""
    on_disk = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
        except (OSError, json.JSONDecodeError):
            on_disk = {}

    def blend(old, new):
        merged = dict(old)
        for key, value in new.items():
            if isinstance(value, dict) and isinstance(old.get(key), dict):
                merged[key] = blend(old[key], value)
            else:
                merged[key] = value
        return merged

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(blend(on_disk, cfg), f, indent=2)
            f.write("\n")
    except OSError as exc:
        log(f"[mini_picker] could not save mini_config.json ({exc})")


def list_themes():
    """Return the theme names (filenames without .json) available in themes/."""
    if not os.path.isdir(THEMES_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(THEMES_DIR) if f.endswith(".json"))


def load_theme(name):
    """Load themes/<name>.json, filled in from DEFAULT_THEME for any missing key."""
    path = os.path.join(THEMES_DIR, f"{name}.json")
    if not os.path.exists(path):
        log(f"[mini_picker] theme '{name}' not found; using fallback")
        return dict(DEFAULT_THEME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _merge(DEFAULT_THEME, json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[mini_picker] could not read theme '{name}' ({exc}); using fallback")
        return dict(DEFAULT_THEME)


def resolve_path(path):
    """Turn a possibly-relative roster path into an absolute one under BASE_DIR."""
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def load_students(path):
    """Return de-duplicated names from `path`, skipping blanks and a 'Name' header."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        names = [line.strip() for line in f if line.strip()]
    seen, unique = set(), []
    for name in names:
        if name.lower() != "name" and name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def choose_students_file(start_dir):
    """Native file dialog for picking a roster .txt. Returns a path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Select students .txt file",
        initialdir=start_dir,
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    root.destroy()
    return path or None


# --------------------------------------------------------------------------
# window helpers
# --------------------------------------------------------------------------

_topmost_warned = False


def position_is_on_screen(x, y):
    """True if (x, y) falls on a connected monitor.

    A position saved while a projector was plugged in can land far outside the
    desktop once it is unplugged, which would open the window somewhere the
    user cannot see or reach. Windows-only; assume fine elsewhere.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        MONITOR_DEFAULTTONULL = 0
        return bool(user32.MonitorFromPoint(POINT(int(x), int(y)),
                                            MONITOR_DEFAULTTONULL))
    except (AttributeError, OSError, ValueError):
        return True


def set_always_on_top(enabled):
    """Pin the window above other windows. Windows-only; a no-op elsewhere.

    Declaring argtypes matters here: an HWND is 64-bit, and ctypes would
    otherwise marshal it as a C int and silently pass a truncated handle,
    so SetWindowPos reports success while doing nothing.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = pygame.display.get_wm_info()["window"]
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
        return bool(user32.SetWindowPos(
            hwnd, HWND_TOPMOST if enabled else HWND_NOTOPMOST,
            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))
    except (KeyError, AttributeError, OSError) as exc:
        global _topmost_warned
        if not _topmost_warned:          # the loop re-asserts; warn once, not forever
            log(f"[mini_picker] always-on-top unavailable ({exc})")
            _topmost_warned = True
        return False


class FontBook:
    """Caches sized fonts for one theme so we can shrink text without re-loading."""

    def __init__(self, theme):
        spec = theme["font"]
        self.bold = bool(spec.get("bold", True))
        self.family = None
        for candidate in spec.get("candidates", []):
            if pygame.font.match_font(candidate):
                self.family = candidate
                break
        self._cache = {}
        self.name_size = int(spec.get("name_size", 50))
        self.small_size = int(spec.get("small_size", 15))
        # Themes with a technical/robotic face read better in caps; the roster
        # file stays untouched, only what we draw is upper-cased.
        self.uppercase = bool(spec.get("uppercase", False))
        # With fill_window on (the default) the name is sized to the space it
        # has rather than to `name_size`, so it fills the panel; name_size is
        # then only the fallback for themes that switch this off.
        self.fill_window = bool(spec.get("fill_window", True))
        self.fill = float(spec.get("fill", 0.94))
        self._box_cache = {}

    def at(self, size):
        size = max(8, int(size))
        if size not in self._cache:
            if self.family:
                self._cache[size] = pygame.font.SysFont(self.family, size, bold=self.bold)
            else:
                self._cache[size] = pygame.font.Font(None, size + 4)
        return self._cache[size]

    def fit(self, text, max_width, start_size, min_size=12):
        """Largest font at or below start_size that renders `text` inside max_width."""
        size = start_size
        while size > min_size and self.at(size).size(text)[0] > max_width:
            size -= 1
        return self.at(size)

    def fit_box(self, text, max_width, max_height, min_size=10):
        """Largest font whose *ink* fits in max_width x max_height.

        Measured off the rendered bounding box, not the font's line box: a
        line box carries descender room that all-caps text never uses, and
        sizing to it would leave the name visibly short of the space it has.
        Returns (font, dy) where dy re-centers the ink, since the glyphs sit
        high in their line box for the same reason.
        """
        key = (text, max_width, max_height)
        hit = self._box_cache.get(key)
        if hit is None:
            lo, hi, best = min_size, max(min_size, int(max_height * 2) + 8), min_size
            while lo <= hi:
                mid = (lo + hi) // 2
                font = self.at(mid)
                ink = font.render(text, True, (255, 255, 255)).get_bounding_rect()
                if font.size(text)[0] <= max_width and ink.height <= max_height:
                    best, lo = mid, mid + 1
                else:
                    hi = mid - 1
            font = self.at(best)
            surf = font.render(text, True, (255, 255, 255))
            ink = surf.get_bounding_rect()
            dy = round(surf.get_height() / 2 - (ink.y + ink.height / 2))
            if len(self._box_cache) > 512:
                self._box_cache.clear()
            hit = self._box_cache[key] = (best, dy)
        size, dy = hit
        return self.at(size), dy


def lerp_ramp(colors, f):
    """Colour at position `f` (0-1) along a list of stops, blended linearly."""
    if len(colors) == 1:
        return colors[0]
    span = f * (len(colors) - 1)
    i = min(int(span), len(colors) - 2)
    t = span - i
    a, b = colors[i], colors[i + 1]
    return tuple(round(a[c] + (b[c] - a[c]) * t) for c in range(3))


def fill_gradient(surface, top, bottom):
    """Paint a vertical gradient from `top` to `bottom` across `surface`."""
    width, height = surface.get_size()
    for y in range(height):
        f = y / max(1, height - 1)
        pygame.draw.line(
            surface,
            (int(top[0] + (bottom[0] - top[0]) * f),
             int(top[1] + (bottom[1] - top[1]) * f),
             int(top[2] + (bottom[2] - top[2]) * f)),
            (0, y), (width, y))


def radial_surface(size, color, alpha_at, steps=40):
    """A radial gradient of `color`, sized to `size`.

    `alpha_at(f)` gives the alpha at radius fraction f (0 at the centre, 1 at
    the edge). Drawn small as concentric circles and smoothscaled up, which is
    far cheaper than evaluating every pixel in Python.
    """
    src = pygame.Surface((steps * 2, steps * 2), pygame.SRCALPHA)
    for i in range(steps, 0, -1):
        alpha = max(0, min(255, int(alpha_at(i / steps))))
        pygame.draw.circle(src, (*color, alpha), (steps, steps), i)
    return pygame.transform.smoothscale(
        src, (max(1, int(size[0])), max(1, int(size[1]))))


class Ray:
    """A drifting vertical band of light that sweeps across the background.

    Geometry is kept as fractions of the window so a resize just rebuilds the
    band image instead of scattering the rays.
    """

    def __init__(self, spec):
        lo, hi = spec.get("width", [0.02, 0.06])
        self.width_f = random.uniform(float(lo), float(hi))
        lo, hi = spec.get("speed", [0.02, 0.07])
        self.speed_f = random.uniform(float(lo), float(hi)) * random.choice((-1, 1))
        lo, hi = spec.get("alpha", [40, 95])
        self.base_alpha = random.randint(int(lo), int(hi))
        self.color = tuple(spec.get("color", [255, 255, 255]))
        self.phase = random.uniform(0, 6.28)
        self.x_f = random.random()
        self.image = None
        self._built_for = None

    def _build(self, size):
        width, height = size
        band = max(2, int(self.width_f * width))
        self.image = pygame.Surface((band, height), pygame.SRCALPHA)
        for x in range(band):
            # Soft edges: fade out toward both sides of the band.
            edge = 1 - abs((x / max(1, band - 1)) * 2 - 1)
            pygame.draw.line(self.image, (*self.color, int(200 * edge)),
                             (x, 0), (x, height))
        self._built_for = size

    def update(self, dt):
        self.x_f = (self.x_f + self.speed_f * dt) % 1.0

    def draw(self, surface, t):
        size = surface.get_size()
        if size != self._built_for:
            self._build(size)
        pulse = 0.6 + 0.4 * math.sin(t * 2 + self.phase)
        self.image.set_alpha(int(self.base_alpha * pulse))
        x = self.x_f * (size[0] + self.image.get_width()) - self.image.get_width()
        surface.blit(self.image, (int(x), 0))


class Mote:
    """A slow speck of light drifting upward and twinkling."""

    def __init__(self, spec):
        self.color = tuple(spec.get("color", [255, 255, 255]))
        self.max_alpha = int(spec.get("alpha", 150))
        self.speed_range = spec.get("speed", [0.03, 0.10])
        self.size_range = spec.get("size", [1, 2])
        self.reset(anywhere=True)

    def reset(self, anywhere=False):
        self.x_f = random.random()
        self.y_f = random.random() if anywhere else 1.05
        self.speed_f = random.uniform(*(float(v) for v in self.speed_range))
        self.drift_f = random.uniform(-0.02, 0.02)
        self.radius = random.randint(int(self.size_range[0]), int(self.size_range[1]))
        self.phase = random.uniform(0, 6.28)

    def update(self, dt):
        self.y_f -= self.speed_f * dt
        self.x_f = (self.x_f + self.drift_f * dt) % 1.0
        if self.y_f < -0.05:
            self.reset()

    def draw(self, surface, t, scale=1.0):
        width, height = surface.get_size()
        twinkle = 0.5 + 0.5 * math.sin(t * 4 + self.phase)
        radius = max(1, int(self.radius * scale))
        dot = pygame.Surface((radius * 2 + 1, radius * 2 + 1), pygame.SRCALPHA)
        pygame.draw.circle(dot, (*self.color, int(self.max_alpha * twinkle)),
                           (radius, radius), radius)
        surface.blit(dot, (int(self.x_f * width), int(self.y_f * height)))


class Background:
    """The themed backdrop: gradient, spotlight, light rays, motes, vignette.

    Everything that does not move is rendered once into a cached surface and
    rebuilt only when the window size or the theme changes.
    """

    def __init__(self, theme, size):
        self.configure(theme, size)

    def configure(self, theme, size):
        self.colors = theme["colors"]
        self.spec = theme.get("background", {})
        self.size = size
        rays = self.spec.get("rays", {})
        self.rays = ([Ray(rays) for _ in range(int(rays.get("count", 0)))]
                     if rays.get("enabled") else [])
        motes = self.spec.get("motes", {})
        self.motes = ([Mote(motes) for _ in range(int(motes.get("count", 0)))]
                      if motes.get("enabled") else [])
        self._build()

    def resize(self, size):
        if size != self.size:
            self.size = size
            self._build()

    def _build(self):
        width, height = self.size
        self.base = pygame.Surface(self.size)
        if self.spec.get("gradient", True):
            fill_gradient(self.base, self.colors["bg_top"], self.colors["bg_bottom"])
        else:
            self.base.fill(self.colors["bg_bottom"])

        spot = self.spec.get("spotlight", {})
        if spot.get("enabled"):
            spread = float(spot.get("spread", 1.3))
            alpha = float(spot.get("alpha", 70))
            size = (width * spread, height * spread)
            # Falloff is gentle (^1.6) and the ellipse is drawn larger than
            # the window, so what shows is the bright middle of a pool of
            # light rather than a hard-edged oval sitting on the background.
            self.spotlight = radial_surface(
                size, tuple(spot.get("color", self.colors["glow"])),
                lambda f: alpha * (1 - f) ** 1.6, steps=64)
            self.spotlight_pos = ((width - int(size[0])) // 2,
                                  (height - int(size[1])) // 2)
        else:
            self.spotlight = None

        grid = self.spec.get("grid", {})
        if grid.get("enabled"):
            cell = max(4, int(float(grid.get("cell", 0.12)) * height))
            alpha = int(grid.get("alpha", 40))
            color = tuple(grid.get("color", [0, 255, 255]))
            # One extra cell of height so it can scroll without showing a seam.
            self.grid = pygame.Surface((width, height + cell), pygame.SRCALPHA)
            for x in range(0, width + cell, cell):
                pygame.draw.line(self.grid, (*color, alpha), (x, 0),
                                 (x, height + cell))
            for y in range(0, height + cell, cell):
                pygame.draw.line(self.grid, (*color, alpha), (0, y), (width, y))
            self.grid_cell = cell
        else:
            self.grid = None

        scan = self.spec.get("scanlines", {})
        if scan.get("enabled"):
            gap = max(2, int(float(scan.get("spacing", 0.02)) * height))
            alpha = int(scan.get("alpha", 38))
            color = tuple(scan.get("color", [0, 0, 0]))
            self.scanlines = pygame.Surface((width, height + gap), pygame.SRCALPHA)
            for y in range(0, height + gap, gap):
                pygame.draw.line(self.scanlines, (*color, alpha), (0, y), (width, y))
            self.scan_gap = gap
        else:
            self.scanlines = None

        bar = self.spec.get("scanbar", {})
        if bar.get("enabled"):
            band = max(2, int(float(bar.get("height", 0.10)) * height))
            alpha = int(bar.get("alpha", 60))
            # `colors` is a list the band blends through top to bottom, so one
            # sweep carries the whole palette past the name; `color` is the
            # older single-colour form and still works.
            ramp = [tuple(c) for c in bar.get("colors", [])]
            if not ramp:
                ramp = [tuple(bar.get("color", [0, 255, 255]))]
            self.scanbar = pygame.Surface((width, band), pygame.SRCALPHA)
            for y in range(band):
                f = y / max(1, band - 1)
                # brightest through the middle of the band, fading to nothing
                edge = 1 - abs(f * 2 - 1)
                color = lerp_ramp(ramp, f)
                pygame.draw.line(self.scanbar, (*color, int(alpha * edge)),
                                 (0, y), (width, y))
            self.scanbar_period = float(bar.get("period", 4.0))
        else:
            self.scanbar = None

        vign = self.spec.get("vignette", {})
        if vign.get("enabled"):
            alpha = float(vign.get("alpha", 110))
            # Drawn larger than the window for the same reason as the
            # spotlight: an ellipse inscribed exactly in the frame reads as a
            # drawn oval, while an oversized one just darkens the corners.
            spread = float(vign.get("spread", 1.5))
            size = (width * spread, height * spread)
            self.vignette = radial_surface(
                size, tuple(vign.get("color", [0, 0, 0])),
                lambda f: alpha * f ** 2.5, steps=64)
            self.vignette_pos = ((width - int(size[0])) // 2,
                                 (height - int(size[1])) // 2)
        else:
            self.vignette = None

    def update(self, dt):
        for ray in self.rays:
            ray.update(dt)
        for mote in self.motes:
            mote.update(dt)

    def draw(self, surface, t, scale=1.0):
        surface.blit(self.base, (0, 0))
        if self.spotlight is not None:
            surface.blit(self.spotlight, self.spotlight_pos)
        for ray in self.rays:
            ray.draw(surface, t)
        if self.grid is not None:
            speed = float(self.spec.get("grid", {}).get("speed", 0.0))
            offset = int((t * speed * self.grid_cell) % self.grid_cell)
            surface.blit(self.grid, (0, offset - self.grid_cell))
        for mote in self.motes:
            mote.draw(surface, t, scale)
        if self.scanbar is not None:
            height = surface.get_height()
            travel = (t % self.scanbar_period) / self.scanbar_period
            surface.blit(self.scanbar,
                         (0, int(travel * (height + self.scanbar.get_height()))
                          - self.scanbar.get_height()))
        if self.scanlines is not None:
            speed = float(self.spec.get("scanlines", {}).get("speed", 0.0))
            offset = int((t * speed * self.scan_gap) % self.scan_gap)
            surface.blit(self.scanlines, (0, offset - self.scan_gap))
        if self.vignette is not None:
            surface.blit(self.vignette, self.vignette_pos)


def blit_glow(surface, font, text, center, core, glow, radius, alpha):
    """Draw `text` centered at `center`, optionally with a bloom behind it.

    A radius of 0 - what every shipped theme uses - skips the halo entirely and
    renders the text crisp.
    """
    if radius > 0 and alpha > 0:
        halo = font.render(text, True, glow)
        halo.set_alpha(alpha)
        rect = halo.get_rect(center=center)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx or dy:
                    surface.blit(halo, rect.move(dx, dy))
    body = font.render(text, True, core)
    surface.blit(body, body.get_rect(center=center))


def draw_glitch_name(surface, font, text, center, core, spec, now, scale=1.0):
    """Render `text` as a brief hardware-glitch burst.

    Two colour-fringed ghosts are thrown left and right, then the name itself
    is redrawn in horizontal slices at random offsets. The slice offsets are
    seeded from a coarse clock so they hold for a few frames at a time and read
    as discrete glitch steps rather than per-frame noise.
    """
    shift = max(1, int(spec.get("shift", 10) * scale))
    colors = spec.get("colors", [[255, 0, 90], [0, 255, 255]])
    alpha = int(spec.get("alpha", 150))

    base = font.render(text, True, core)
    rect = base.get_rect(center=center)

    for i, col in enumerate(colors[:2]):
        ghost = font.render(text, True, tuple(col))
        ghost.set_alpha(alpha)
        surface.blit(ghost, rect.move(shift if i == 0 else -shift,
                                      (i * 2 - 1) * max(1, shift // 3)))

    rng = random.Random(now // max(1, int(spec.get("step_ms", 55))))
    height = base.get_height()
    slices = max(1, int(spec.get("slices", 6)))
    band = max(1, height // slices)
    for top in range(0, height, band):
        piece = base.subsurface((0, top, base.get_width(),
                                 min(band, height - top)))
        surface.blit(piece, (rect.x + rng.randint(-shift, shift), rect.y + top))


def glitch_active(spec, now):
    """True while a glitch burst should be showing."""
    if not spec.get("enabled"):
        return False
    period = max(1, int(spec.get("period_ms", 2400)))
    return (now % period) < int(spec.get("duration_ms", 190))


def ease_out(t):
    """t in [0,1] -> eased value that decelerates toward the end."""
    return 1 - (1 - t) * (1 - t)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv, cfg):
    """Apply `roster.txt` and `--theme NAME` overrides from the command line.

    Returns (cfg, cli_keys). Keys named on the command line are one-off
    overrides for this run, so they are excluded from what gets saved back
    to mini_config.json unless the user changes them in the window.
    """
    cli_keys = set()
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg in ("--theme", "-t") and args:
            cfg["theme"] = args.pop(0)
            cli_keys.add("theme")
        elif arg in ("--students", "-s") and args:
            cfg["students_file"] = args.pop(0)
            cli_keys.add("students_file")
        elif not arg.startswith("-"):
            cfg["students_file"] = arg
            cli_keys.add("students_file")
    return cfg, cli_keys


def main():
    cfg, cli_keys = parse_args(sys.argv[1:], load_config())
    changed_in_app = set()   # settings the user edited in the window this run

    def persist():
        """Save settings, minus one-off CLI overrides the user did not touch."""
        save_config({k: v for k, v in cfg.items()
                     if k not in cli_keys or k in changed_in_app})

    themes = list_themes()
    theme_name = cfg["theme"] if cfg["theme"] in themes else (themes[0] if themes else "")
    theme = load_theme(theme_name)

    pygame.init()
    pygame.display.set_caption("Student Picker")

    win_spec = theme["window"]
    # The theme size is the design size: everything is drawn for these
    # dimensions and then scaled by however much the window differs from them.
    base_w, base_h = int(win_spec["width"]), int(win_spec["height"])
    width = int(cfg["window"].get("width") or base_w)
    height = int(cfg["window"].get("height") or base_h)
    flags = pygame.RESIZABLE
    if win_spec.get("borderless", True):
        flags |= pygame.NOFRAME
    saved_x, saved_y = cfg["window"].get("x"), cfg["window"].get("y")
    if (saved_x is not None and saved_y is not None
            and position_is_on_screen(saved_x, saved_y)):
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{saved_x},{saved_y}"
    else:
        if saved_x is not None:
            log("[mini_picker] saved window position is off-screen; centering")
            cfg["window"]["x"] = cfg["window"]["y"] = None
        os.environ["SDL_VIDEO_CENTERED"] = "1"
    screen = pygame.display.set_mode((width, height), flags)

    window = video.Window.from_display_module()
    try:
        window.opacity = float(win_spec.get("opacity", 1.0))
    except WINDOW_ERRORS:
        pass   # some video backends do not support per-window opacity

    on_top = bool(cfg["window"].get("always_on_top", True))
    topmost_ok = set_always_on_top(on_top)

    clock = pygame.time.Clock()
    fonts = FontBook(theme)
    background = Background(theme, (width, height))

    # --- roster ---
    students_path = resolve_path(cfg["students_file"])
    all_students = load_students(students_path)
    source_name = os.path.basename(students_path)
    remaining = list(all_students)
    random.shuffle(remaining)

    def roster_stamp():
        """Modification time of the roster file, or None if it is not there."""
        try:
            return os.path.getmtime(students_path)
        except OSError:
            return None

    roster_mtime = roster_stamp()

    # --- controller ---
    pygame.joystick.init()
    joystick = None

    def connect_joystick():
        """(Re)open the configured pad. Held open so its button events keep arriving."""
        nonlocal joystick
        index = int(cfg["controller"].get("joystick_index", 0))
        if pygame.joystick.get_count() > index:
            joystick = pygame.joystick.Joystick(index)
            joystick.init()
        else:
            joystick = None

    connect_joystick()

    # --- keyboard backup ---
    # A global hook, because the picker is unfocused exactly when it is needed:
    # if the pad dies mid-lecture this is what still calls a student. It only
    # observes - the key is not consumed, so it reaches your slides as usual.
    hotkeys = None
    hk_cfg = cfg.get("hotkey", {})
    hk_next = hk_cfg.get("next") if hk_cfg.get("enabled", True) else None
    if hk_next and pynput_keyboard is not None:
        try:
            hotkeys = pynput_keyboard.GlobalHotKeys({
                hotkey_spec(hk_next):
                    lambda: pygame.event.post(pygame.event.Event(HOTKEY_NEXT))})
            hotkeys.start()
        except (ValueError, OSError) as exc:
            log(f"[mini_picker] keyboard backup off - bad hotkey {hk_next!r} ({exc})")
            hotkeys = None
    elif hk_next:
        log("[mini_picker] keyboard backup off - pynput is not installed")

    state = IDLE
    display_name = ""
    winner = ""
    round_done = False         # the last pick completed a full round
    spin_start = next_swap = 0
    mapping_step = None        # index into MAPPABLE while the L wizard is running
    mapping_locked = {}        # button index -> action label, settled this run
    message = ""               # transient status line, e.g. "Bound button 3"
    message_until = 0
    dragging = False
    drag_offset = (0, 0)
    resizing = False
    resize_grab = (0, 0)   # pointer offset from the bottom-right corner

    def notify(text, ms=2200):
        nonlocal message, message_until
        message = text
        message_until = pygame.time.get_ticks() + ms

    def reset_pool():
        nonlocal remaining, state, display_name, winner, round_done
        remaining = list(all_students)
        random.shuffle(remaining)
        state, display_name, winner = IDLE, "", ""
        round_done = False

    def pool():
        """Names eligible for the next draw."""
        return remaining if cfg.get("no_repeats", True) else all_students

    def finish_spin():
        """Land on the winner, and start a fresh round if that was the last one."""
        nonlocal state, display_name, round_done
        display_name = winner
        state = RESULT
        if cfg.get("no_repeats", True) and winner in remaining:
            remaining.remove(winner)
            if not remaining:
                # Everyone has had a turn. Refill straight away so NEXT keeps
                # working - the winner stays on screen, only the pool resets.
                remaining.extend(all_students)
                random.shuffle(remaining)
                round_done = True
                notify(ROUND_OVER_MESSAGE, 5000)

    def start_spin():
        nonlocal state, winner, spin_start, next_swap, display_name, round_done
        candidates = pool()
        if not candidates:
            return
        # Refilling the pool can otherwise call the same student twice running.
        choices = [n for n in candidates if n != winner] or candidates
        round_done = False
        winner = random.choice(choices)
        if int(cfg.get("spin_ms", 1400)) <= 0:
            finish_spin()
            return
        spin_start = next_swap = pygame.time.get_ticks()
        display_name = random.choice(candidates)
        state = SPINNING

    def on_pick():
        if state in (IDLE, RESULT) and pool():
            start_spin()

    def reload_roster_if_changed():
        """Pick up edits to the roster file without needing a restart."""
        nonlocal all_students, roster_mtime
        stamp = roster_stamp()
        if stamp == roster_mtime:
            return
        roster_mtime = stamp
        loaded = load_students(students_path)
        if not loaded or loaded == all_students:
            return
        all_students = loaded
        reset_pool()
        notify(f"Roster reloaded - {len(all_students)} names")

    def swap_roster(path):
        nonlocal all_students, students_path, source_name, roster_mtime
        loaded = load_students(path)
        if not loaded:
            notify("That file had no names")
            return
        all_students = loaded
        students_path = path
        roster_mtime = roster_stamp()
        source_name = os.path.basename(path)
        cfg["students_file"] = path
        changed_in_app.add("students_file")
        persist()
        reset_pool()
        notify(f"Loaded {source_name}")

    def cycle_theme():
        nonlocal theme, theme_name, fonts, base_w, base_h
        if len(themes) < 2:
            notify("Only one theme in themes/")
            return
        theme_name = themes[(themes.index(theme_name) + 1) % len(themes)]
        theme = load_theme(theme_name)
        fonts = FontBook(theme)
        background.configure(theme, (width, height))
        spec = theme["window"]
        base_w, base_h = int(spec["width"]), int(spec["height"])
        # A size the user chose by hand outranks the theme's own; otherwise
        # adopt the incoming theme's design size.
        if cfg["window"].get("width") is None:
            apply_size(base_w, base_h, remember=False)
        try:
            window.borderless = bool(spec.get("borderless", True))
        except WINDOW_ERRORS:
            pass
        try:
            window.opacity = float(spec.get("opacity", 1.0))
        except WINDOW_ERRORS:
            pass
        set_always_on_top(on_top)
        cfg["theme"] = theme_name
        changed_in_app.add("theme")
        persist()
        notify(f"Theme: {theme.get('name', theme_name)}")

    def scale_factor():
        """How much bigger the window is than the theme's design size."""
        return min(width / base_w, height / base_h)

    def grip_rect():
        """The drag-to-resize square in the bottom-right corner."""
        g = max(10, round(GRIP_BASE * scale_factor()))
        return pygame.Rect(width - g, height - g, g, g)

    def apply_size(new_w, new_h, remember=True):
        """Resize the window, keeping it where it is, and remember the size.

        set_mode can recreate the underlying window, which drops both the
        position and the topmost flag, so both are restored afterwards.
        """
        nonlocal width, height, screen, window
        new_w = max(MIN_WIN_W, int(new_w))
        new_h = max(MIN_WIN_H, int(new_h))
        try:
            desktops = pygame.display.get_desktop_sizes()
            if desktops:
                new_w = min(new_w, desktops[0][0])
                new_h = min(new_h, desktops[0][1])
        except (AttributeError, pygame.error):
            pass
        if (new_w, new_h) == (width, height):
            return
        try:
            pos = window.position
        except WINDOW_ERRORS:
            pos = None
        width, height = new_w, new_h
        screen = pygame.display.set_mode((width, height), flags)
        window = video.Window.from_display_module()
        if pos is not None:
            try:
                window.position = pos
            except WINDOW_ERRORS:
                pass
        if on_top:
            set_always_on_top(True)
        background.resize((width, height))
        if remember:
            cfg["window"]["width"], cfg["window"]["height"] = width, height

    def zoom(factor):
        """Grow or shrink the window about its current size."""
        apply_size(round(width * factor), round(height * factor))
        notify(f"{width} x {height}")

    def mapping_summary():
        """One line describing what each controller button currently does."""
        return "   ".join(
            f"{short}: {button_label(cfg['controller'].get(key))}"
            for key, _prompt, short in MAPPABLE)

    def start_mapping():
        nonlocal mapping_step
        mapping_step = 0
        mapping_locked.clear()
        prompt_mapping()

    def prompt_mapping():
        """Ask for the button for the current step, or finish if we ran off the end."""
        nonlocal mapping_step
        if mapping_step is None:
            return
        if mapping_step >= len(MAPPABLE):
            mapping_step = None
            persist()
            notify(f"Saved.  {mapping_summary()}", 4000)
            return
        _, prompt, _short = MAPPABLE[mapping_step]
        notify(f"Press the button to {prompt}   (S skip, Esc cancel)", 60000)

    def assign_button(index):
        """Bind `index` to the current wizard step and move on.

        A button already settled earlier in this run is refused rather than
        quietly stolen - otherwise pressing the same button twice would
        silently unmap the action the user had just assigned. Buttons still
        held by an action we have not reached yet are fair game; that action
        gets its own turn to be assigned.
        """
        nonlocal mapping_step
        if index in mapping_locked:
            notify(f"{button_label(index)} is already {mapping_locked[index]} "
                   f"- try another", 4000)
            return
        key, _prompt, short = MAPPABLE[mapping_step]
        for other, _p, _s in MAPPABLE:
            if other != key and cfg["controller"].get(other) == index:
                cfg["controller"][other] = None
        cfg["controller"][key] = index
        mapping_locked[index] = short
        mapping_step += 1
        prompt_mapping()

    def skip_mapping():
        """Leave this action as it is and move on, keeping its button reserved."""
        nonlocal mapping_step
        key, _prompt, short = MAPPABLE[mapping_step]
        current = cfg["controller"].get(key)
        if current is not None:
            mapping_locked[current] = short
        mapping_step += 1
        prompt_mapping()

    def remember_position():
        try:
            x, y = window.position
        except WINDOW_ERRORS:
            return
        cfg["window"]["x"], cfg["window"]["y"] = int(x), int(y)

    running = True
    next_topmost = 0
    next_roster_check = ROSTER_POLL_MS
    while running:
        now = pygame.time.get_ticks()

        if now >= next_roster_check:
            next_roster_check = now + ROSTER_POLL_MS
            reload_roster_if_changed()

        # Keep ourselves pinned above whatever the slideshow does.
        if on_top and topmost_ok and now >= next_topmost:
            set_always_on_top(True)
            next_topmost = now + TOPMOST_REASSERT_MS

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if mapping_step is not None:
                        mapping_step = None
                        notify("Mapping cancelled")
                    else:
                        running = False
                elif event.key == pygame.K_x:
                    on_pick()
                elif event.key == pygame.K_r:
                    reset_pool()
                elif event.key == pygame.K_t:
                    cycle_theme()
                elif event.key == pygame.K_l:
                    start_mapping()
                elif event.key == pygame.K_s and mapping_step is not None:
                    skip_mapping()
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS,
                                   pygame.K_KP_PLUS):
                    zoom(RESIZE_STEP)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    zoom(1 / RESIZE_STEP)
                elif event.key in (pygame.K_0, pygame.K_KP0):
                    apply_size(base_w, base_h)
                    notify(f"Reset to {width} x {height}")
                elif event.key == pygame.K_h:
                    notify(mapping_summary(), 5000)
                elif event.key == pygame.K_o:
                    on_top = not on_top
                    topmost_ok = set_always_on_top(on_top)
                    cfg["window"]["always_on_top"] = on_top
                    persist()
                    notify(f"Always on top: {'on' if on_top else 'off'}")
                elif event.key == pygame.K_f:
                    chosen = choose_students_file(os.path.dirname(students_path) or BASE_DIR)
                    set_always_on_top(on_top)   # dialog steals topmost; re-assert
                    if chosen:
                        swap_roster(chosen)

            elif event.type == HOTKEY_NEXT:
                # No focus test: when the picker does have focus the same key
                # also arrives as a KEYDOWN, but on_pick() only acts from
                # IDLE/RESULT, so the second call lands mid-spin and is ignored.
                on_pick()

            elif event.type == pygame.JOYBUTTONDOWN:
                bound = cfg["controller"]
                if mapping_step is not None:
                    assign_button(event.button)
                elif event.button == bound.get("pick_button"):
                    on_pick()
                elif event.button == bound.get("theme_button"):
                    cycle_theme()
                elif event.button == bound.get("reset_button"):
                    reset_pool()

            elif event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                connect_joystick()

            elif event.type == pygame.VIDEORESIZE and not resizing:
                apply_size(event.w, event.h)

            elif (event.type == pygame.MOUSEWHEEL
                  and pygame.key.get_mods() & pygame.KMOD_CTRL):
                zoom(RESIZE_STEP if event.y > 0 else 1 / RESIZE_STEP)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if grip_rect().collidepoint(event.pos):
                    resizing = True
                    resize_grab = (width - event.pos[0], height - event.pos[1])
                else:
                    dragging = True
                    drag_offset = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if resizing:
                    resizing = False
                    notify(f"{width} x {height}")
                    persist()
                elif dragging:
                    dragging = False
                    remember_position()
                    persist()
            elif event.type == pygame.MOUSEMOTION and resizing:
                apply_size(event.pos[0] + resize_grab[0],
                           event.pos[1] + resize_grab[1])
            elif event.type == pygame.MOUSEMOTION and dragging:
                try:
                    wx, wy = window.position
                    window.position = (int(wx + event.pos[0] - drag_offset[0]),
                                       int(wy + event.pos[1] - drag_offset[1]))
                except WINDOW_ERRORS:
                    dragging = False

        # --- spin animation ---
        if state == SPINNING:
            elapsed = now - spin_start
            spin_ms = int(cfg.get("spin_ms", 1400))
            if elapsed >= spin_ms:
                finish_spin()
            elif now >= next_swap:
                interval = (SPIN_MIN_INTERVAL
                            + (SPIN_MAX_INTERVAL - SPIN_MIN_INTERVAL)
                            * ease_out(elapsed / spin_ms))
                candidates = [n for n in pool() if n != display_name] or pool()
                display_name = random.choice(candidates)
                next_swap = now + int(interval)

        # --- draw ---
        colors = theme["colors"]
        glow_spec = theme["glow"]
        spec = theme["window"]
        show_counter = theme["footer"].get("show_counter", True)

        # Every measurement below is authored at the theme's design size and
        # multiplied by `scale`, so the whole layout grows and shrinks together
        # with the window instead of leaving text stranded at a fixed size.
        scale = scale_factor()
        pad = max(3, round(spec.get("padding", 14) * scale))
        radius = max(0, round(spec.get("corner_radius", 10) * scale))
        border_w = max(1, round(spec.get("border_width", 3) * scale))
        name_size = max(10, round(fonts.name_size * scale))
        small_size = max(8, round(fonts.small_size * scale))
        glow_radius = max(0, round(int(glow_spec.get("radius", 0)) * scale))

        background.update(clock.get_time() / 1000.0)
        background.draw(screen, now / 1000.0, scale)

        border_color = colors["border"]
        if state == RESULT and (now // 220) % 2 == 0:
            border_color = colors["border_flash"]
        inset = max(1, border_w // 2)
        pygame.draw.rect(screen, border_color,
                         pygame.Rect(inset, inset, width - inset * 2, height - inset * 2),
                         width=border_w, border_radius=radius)

        # The name gets everything the border and the footer line don't need.
        # The footer sits in just its own text height plus a hairline of gap,
        # so the panel reads as one big name with a caption tucked under it.
        footer_h = (small_size + round(3 * scale)) if show_counter else 0
        name_top = border_w + max(2, round(3 * scale))
        name_bottom = height - border_w - footer_h - max(1, round(2 * scale))
        name_h = max(12, name_bottom - name_top)
        name_center = (width // 2, (name_top + name_bottom) // 2)
        max_text_w = width - pad * 2 - border_w * 2

        hint = ""
        if not all_students:
            font = fonts.at(small_size + round(3 * scale))
            blit_glow(screen, font, f"No names in {source_name}", name_center,
                      colors["muted"], colors["glow"], 0, 0)
            hint = "Press F to load a roster"
        elif state == IDLE and not display_name:
            prompt = f"Press NEXT  ({button_label(cfg['controller'].get('pick_button'))} or Space)"
            font = fonts.fit(prompt, max_text_w,
                             small_size + round(5 * scale), min_size=8)
            blit_glow(screen, font, prompt, name_center,
                      colors["muted"], colors["glow"], 0, 0)
        else:
            is_winner = state == RESULT
            label = display_name.upper() if fonts.uppercase else display_name
            if fonts.fill_window:
                font, dy = fonts.fit_box(label, max_text_w,
                                         round(name_h * fonts.fill))
                center = (name_center[0], name_center[1] + dy)
            else:
                font, center = fonts.fit(label, max_text_w, name_size), name_center
            core = colors["name_winner"] if is_winner else colors["name"]
            glitch_spec = theme.get("name_fx", {}).get("glitch", {})
            if glitch_active(glitch_spec, now):
                draw_glitch_name(screen, font, label, center,
                                 core, glitch_spec, now, scale)
            else:
                blit_glow(
                    screen, font, label, center, core,
                    colors["glow"],
                    glow_radius if (glow_spec.get("enabled") and is_winner) else 0,
                    int(glow_spec.get("alpha", 0)))

        # Footer: transient message wins, then a hint, then the counter.
        footer_text = ""
        if message and now < message_until:
            footer_text = message
        elif hint:
            footer_text = hint
        elif show_counter and all_students:
            if cfg.get("no_repeats", True):
                footer_text = f"{len(remaining)} of {len(all_students)} left"
            else:
                footer_text = f"{len(all_students)} names"
        if footer_text:
            small = fonts.fit(footer_text, max_text_w, small_size, min_size=8)
            img = small.render(footer_text, True, colors["muted"])
            screen.blit(img, img.get_rect(
                center=(width // 2, height - border_w - footer_h // 2
                        - max(1, round(2 * scale)))))

        # Resize grip: three diagonal ticks in the bottom-right corner.
        grip = grip_rect()
        edge = border_w + max(2, round(2 * scale))   # keep clear of the border
        for i in range(3):
            off = edge + round((i + 1) * grip.width / 5)
            pygame.draw.line(screen, colors["muted"],
                             (grip.right - off, grip.bottom - edge),
                             (grip.right - edge, grip.bottom - off),
                             max(1, round(scale)))

        pygame.display.flip()
        clock.tick(60)

    remember_position()
    persist()
    if hotkeys is not None:
        hotkeys.stop()
    pygame.quit()


if __name__ == "__main__":
    main()
