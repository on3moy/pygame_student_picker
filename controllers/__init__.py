"""
Controller profiles: one JSON file per controller in this folder, naming the
pad's buttons and axes so configs can say "LB" instead of a raw number.

    controllers/gamesir_cyclone2.json
    {
      "name": "GameSir Cyclone 2",
      "aliases": {"L1": "LB", ...},          # optional extra names
      "linux":   {"buttons": {"A": 0, ...}, "axes": {"LX": 0, ...}},
      "windows": {"buttons": {"A": 0, ...}, "axes": {"LX": 0, ...}}
    }

Numbers are what pygame reports (on Linux that is also what
controller_remote.py reads from evdev). They differ per OS, so each OS has
its own section. Create or fix a profile with map_controller.py at the repo
root: press a button, type its name.

Configs refer to a profile by its filename without .json, e.g.
"controller_profile": "gamesir_cyclone2". Button and axis references may then
be names ("RB") or plain numbers (5); numbers always work, profile or not.
"""

import json
import os
import re
import sys

CONTROLLERS_DIR = os.path.dirname(os.path.abspath(__file__))
OS_KEY = "windows" if sys.platform.startswith("win") else "linux"


def _norm(name):
    return str(name).strip().upper()


# The names configs use, in the order map_controller.py asks for them.
# kind: "button", "axis" (a stick direction), or "trigger" (button and/or axis).
STANDARD = (
    ("A", "button", "bottom face button"),
    ("B", "button", "right face button"),
    ("X", "button", "left face button"),
    ("Y", "button", "top face button"),
    ("LB", "button", "left bumper (top-left shoulder)"),
    ("RB", "button", "right bumper (top-right shoulder)"),
    ("LT", "trigger", "left trigger - pull it all the way"),
    ("RT", "trigger", "right trigger - pull it all the way"),
    ("VIEW", "button", "small middle-left button (View / Select / -)"),
    ("MENU", "button", "small middle-right button (Menu / Start / +)"),
    ("HOME", "button", "logo / Home button"),
    ("L3", "button", "click the left stick down"),
    ("R3", "button", "click the right stick down"),
    ("LX", "axis", "left stick - push it fully RIGHT"),
    ("LY", "axis", "left stick - push it fully DOWN"),
    ("RX", "axis", "right stick - push it fully RIGHT"),
    ("RY", "axis", "right stick - push it fully DOWN"),
)
STANDARD_NAMES = tuple(name for name, _kind, _desc in STANDARD)

# Other names people use for the same buttons; each profile can add more.
STANDARD_ALIASES = {
    "L1": "LB", "R1": "RB", "L2": "LT", "R2": "RT",
    "BACK": "VIEW", "SELECT": "VIEW",
    "START": "MENU", "OPTIONS": "MENU",
    "GUIDE": "HOME", "PS": "HOME",
    "L-STICK": "L3", "R-STICK": "R3", "LS": "L3", "RS": "R3",
}


def canonical(name, aliases=None):
    """'l1' -> 'LB'; a standard name, or None if `name` is not one."""
    name = _norm(name)
    name = {**STANDARD_ALIASES, **(aliases or {})}.get(name, name)
    return name if name in STANDARD_NAMES else None


def profile_path(key):
    return os.path.join(CONTROLLERS_DIR, f"{key}.json")


def slugify(text):
    """'GameSir Cyclone 2' -> 'gamesir_cyclone_2', a safe profile filename."""
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "controller"


def list_profiles():
    """Profile keys (filenames without .json) in this folder, sorted."""
    return sorted(f[:-5] for f in os.listdir(CONTROLLERS_DIR) if f.endswith(".json"))


class Profile:
    """One controller's names -> numbers for the current OS."""

    def __init__(self, key, data):
        self.key = key
        self.data = data
        self.title = data.get("name", key)
        layout = data.get(OS_KEY, {})
        self.buttons = {_norm(n): int(i) for n, i in layout.get("buttons", {}).items()}
        self.axes = {_norm(n): int(i) for n, i in layout.get("axes", {}).items()}
        self.aliases = {**STANDARD_ALIASES,
                        **{_norm(a): _norm(n) for a, n in data.get("aliases", {}).items()}}

    def _lookup(self, table, ref, kind):
        """Resolve a name or number to a number. None for null; ValueError
        for a name this profile does not know."""
        if ref is None or isinstance(ref, int):
            return ref
        text = str(ref).strip()
        if text.lstrip("-").isdigit():
            return int(text)
        name = _norm(text)
        name = name if name in table else self.aliases.get(name, name)
        if name not in table:
            raise ValueError(f"{self.key} has no {kind} named {ref!r} "
                             f"(known: {', '.join(table) or 'none'})")
        return table[name]

    def button(self, ref):
        return self._lookup(self.buttons, ref, "button")

    def axis(self, ref):
        return self._lookup(self.axes, ref, "axis")

    def button_names(self):
        """{number: name}, the first name wins if two share a number."""
        out = {}
        for name, index in self.buttons.items():
            out.setdefault(index, name)
        return out


class _NoProfile(Profile):
    """Stands in when no profile is configured: numbers only."""

    def __init__(self):
        super().__init__(None, {})


NO_PROFILE = _NoProfile()


def load_profile(key):
    """The named profile, or NO_PROFILE if key is empty. Raises OSError /
    ValueError if the file is missing or unreadable."""
    if not key:
        return NO_PROFILE
    with open(profile_path(key), "r", encoding="utf-8") as f:
        return Profile(key, json.load(f))


def load_profile_or_warn(key, warn=print):
    """load_profile(), falling back to numbers-only with a warning."""
    try:
        return load_profile(key)
    except (OSError, ValueError) as exc:
        warn(f"[controllers] could not load profile {key!r} ({exc}); using raw numbers")
        return NO_PROFILE


def save_layout(key, buttons, axes, title=None, device=None):
    """Write this OS's buttons/axes into controllers/<key>.json, keeping the
    other OS's section, aliases and comments."""
    path = profile_path(key)
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("name", title or key)
    section = data.setdefault(OS_KEY, {})
    section["_comment"] = "Recorded with map_controller.py" + (
        f" from '{device['name']}'." if device else ".")
    section["buttons"] = dict(sorted(buttons.items(), key=lambda kv: kv[1]))
    section["axes"] = dict(sorted(axes.items(), key=lambda kv: kv[1]))
    if device:
        devices = section.setdefault("devices", [])
        if not any(d.get("name") == device.get("name") for d in devices):
            devices.append(device)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return path
