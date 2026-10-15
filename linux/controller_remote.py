"""
GameSir Cyclone 2 -> keyboard/mouse presentation remote (Linux).

Reads the gamepad straight from evdev and types through a virtual uinput
keyboard + mouse, so every app sees the input - native Wayland windows
included, which pynput's X11 backend cannot reach.

Button/axis numbers match what pygame (SDL) reports on Linux, so
linux/config.json and the --diagnose numbers line up with the picker. Note they differ from
Windows: on Linux the D-pad is a hat, and the right stick is axes 3/4
(axis 2 is the L2 trigger).

The loop sleeps on the controller's file descriptor and only wakes on input,
plus a steady tick while a stick is held for mouse move/scroll. If the
controller is off or drops its Bluetooth link, the remote waits for it.

Usage:
    python controller_remote.py            # run the remote
    python controller_remote.py --diagnose # print button/axis numbers as you press them
    python controller_remote.py --axes     # live readout of every axis value at once
    python controller_remote.py --setup    # calibrate deadzone/axis range for your controller
    python controller_remote.py --test     # live readout of the computed sensitivity zones

Edit linux/config.json to remap inputs. With "controller_profile" set, inputs
can be named ("LB") rather than numbered; the names come from
controllers/<profile>.json, which map_controller.py at the repo root records.
Press Ctrl+C in the terminal to quit.
"""

import argparse
import json
import os
import select
import sys
import time

import evdev
from evdev import ecodes as e

# Each OS folder has its own config.json, next to this script. Controller
# profiles (button names) are shared, in controllers/ at the repo root.
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import controllers  # noqa: E402

# How often to look for the controller while it is off or disconnected.
RECONNECT_SECONDS = 2.0

# Action strings (from config) -> the key the virtual keyboard taps.
# "click" is handled specially by the virtual mouse.
KEY_ACTIONS = {
    "left": e.KEY_LEFT,
    "right": e.KEY_RIGHT,
    "up": e.KEY_UP,
    "down": e.KEY_DOWN,
    "pageup": e.KEY_PAGEUP,
    "pagedown": e.KEY_PAGEDOWN,
    "f5": e.KEY_F5,
    "esc": e.KEY_ESC,
    "space": e.KEY_SPACE,
    "home": e.KEY_HOME,
    "end": e.KEY_END,
    "b": e.KEY_B,  # PowerPoint/Slides black-screen toggle
    "w": e.KEY_W,  # PowerPoint white-screen toggle
    "f": e.KEY_F,  # full screen
}

# Linux defaults where they differ from Windows: right stick is axes 3/4, and
# the D-pad is a hat rather than buttons 13/14.
DEFAULT_SCROLL_X = 3
DEFAULT_SCROLL_Y = 4
DEFAULT_HAT = {"left": "left", "right": "right"}

# One wheel notch in REL_*_HI_RES units (kernel convention).
HI_RES_PER_NOTCH = 120


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    profile = controllers.load_profile_or_warn(cfg.get("controller_profile"))
    cfg["profile"] = profile

    def resolve(lookup, ref):
        try:
            return lookup(ref)
        except ValueError as exc:
            print(f"[warn] {exc}")
            return None

    # Keys may be numbers ("4") or profile names ("LB"); index by number.
    for section in ("buttons", "bumpers"):
        resolved = {}
        for ref, action in cfg.get(section, {}).items():
            index = resolve(profile.button, ref)
            if index is not None:
                resolved[index] = action
        cfg[section] = resolved
    cfg["axes"] = {role: resolve(profile.axis, ref) for role, ref in cfg.get("axes", {}).items()}
    return cfg


def save_config_fields(fields):
    """Read-modify-write just the given top-level keys into config.json."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.update(fields)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def scale_axis(value, deadzone, axis_max):
    """Rescale a raw [-1, 1] axis value so output ramps linearly from 0%
    at the deadzone edge to 100% at axis_max, instead of jumping straight
    to `deadzone`% the instant the stick clears the deadzone."""
    av = abs(value)
    if av < deadzone:
        return 0.0
    span = max(axis_max - deadzone, 1e-6)
    normalized = min((av - deadzone) / span, 1.0)
    return normalized if value >= 0 else -normalized


# --- Controller input -------------------------------------------------------

def is_gamepad(dev):
    caps = dev.capabilities()
    keys = caps.get(e.EV_KEY, [])
    # Excludes the DS4-style "Motion Sensors" and "Touchpad" sibling devices.
    return e.EV_ABS in caps and (e.BTN_GAMEPAD in keys or e.BTN_JOYSTICK in keys)


def find_gamepad():
    for path in sorted(evdev.list_devices()):
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        if is_gamepad(dev):
            return dev
        dev.close()
    return None


class Gamepad:
    """An evdev gamepad with pygame/SDL-compatible button, axis and hat numbers."""

    HAT_CODES = range(e.ABS_HAT0X, e.ABS_HAT3Y + 1)

    def __init__(self, dev):
        self.dev = dev
        self.fd = dev.fd
        caps = dev.capabilities()
        keys = caps.get(e.EV_KEY, [])
        abs_codes = [code for code, _ in caps.get(e.EV_ABS, [])]

        # Same enumeration order as SDL's Linux joystick driver.
        ordered = sorted(c for c in keys if c >= e.BTN_JOYSTICK) + \
            sorted(c for c in keys if e.BTN_MISC <= c < e.BTN_JOYSTICK)
        self.button_index = {code: i for i, code in enumerate(ordered)}
        self.button_codes = ordered
        axes = sorted(c for c in abs_codes if c not in self.HAT_CODES)
        self.axis_index = {code: i for i, code in enumerate(axes)}
        self.axis_range = {}
        for code in axes:
            info = dev.absinfo(code)
            self.axis_range[code] = (info.min, max(info.max - info.min, 1))
        self.has_hat = e.ABS_HAT0X in abs_codes and e.ABS_HAT0Y in abs_codes

        self.axes = [0.0] * len(axes)
        self.hat = (0, 0)  # pygame convention: x right = 1, y up = 1
        self.resync()

    @property
    def name(self):
        return self.dev.name

    def num_buttons(self):
        return len(self.button_codes)

    def num_axes(self):
        return len(self.axes)

    def _norm(self, code, raw):
        lo, span = self.axis_range[code]
        return (raw - lo) * 2.0 / span - 1.0

    def resync(self):
        """Read the current state directly (startup, or after SYN_DROPPED)."""
        self.pressed = {self.button_index[c] for c in self.dev.active_keys() if c in self.button_index}
        for code, i in self.axis_index.items():
            self.axes[i] = self._norm(code, self.dev.absinfo(code).value)
        if self.has_hat:
            self.hat = (self.dev.absinfo(e.ABS_HAT0X).value, -self.dev.absinfo(e.ABS_HAT0Y).value)

    def read(self):
        """Drain pending events. Returns a list of ("button", index) presses
        and ("hat", (x, y)) changes; axis values update in self.axes."""
        out = []
        try:
            for ev in self.dev.read():
                if ev.type == e.EV_KEY and ev.code in self.button_index:
                    idx = self.button_index[ev.code]
                    if ev.value == 1 and idx not in self.pressed:
                        self.pressed.add(idx)
                        out.append(("button", idx))
                    elif ev.value == 0:
                        self.pressed.discard(idx)
                elif ev.type == e.EV_ABS:
                    if ev.code in self.axis_index:
                        self.axes[self.axis_index[ev.code]] = self._norm(ev.code, ev.value)
                    elif ev.code == e.ABS_HAT0X:
                        self.hat = (ev.value, self.hat[1])
                        out.append(("hat", self.hat))
                    elif ev.code == e.ABS_HAT0Y:
                        self.hat = (self.hat[0], -ev.value)
                        out.append(("hat", self.hat))
                elif ev.type == e.EV_SYN and ev.code == e.SYN_DROPPED:
                    self.resync()
        except BlockingIOError:
            pass
        return out

    def pump(self):
        """Non-blocking: apply whatever events are waiting."""
        if select.select([self.fd], [], [], 0)[0]:
            self.read()

    def close(self):
        try:
            self.dev.close()
        except OSError:
            pass


def wait_for_gamepad():
    dev = find_gamepad()
    if dev is None:
        print("No controller detected. Turn on the GameSir Cyclone 2 (USB or Bluetooth) - waiting...")
        while dev is None:
            time.sleep(RECONNECT_SECONDS)
            dev = find_gamepad()
    pad = Gamepad(dev)
    print(f"Controller: {pad.name}  ({dev.path})")
    print(f"  buttons={pad.num_buttons()}  axes={pad.num_axes()}  hats={int(pad.has_hat)}")
    return pad


# --- Virtual keyboard / mouse -----------------------------------------------

class VirtualInput:
    """A uinput keyboard and mouse. Two devices so the compositor classifies
    each one cleanly."""

    def __init__(self):
        try:
            self.kbd = evdev.UInput({e.EV_KEY: sorted(set(KEY_ACTIONS.values()))},
                                    name="controller-remote keyboard")
            self.mouse = evdev.UInput({
                e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
                e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL,
                           e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES],
            }, name="controller-remote mouse")
        except (PermissionError, evdev.UInputError) as exc:
            print(f"Cannot open /dev/uinput ({exc}).")
            print("Load the module with 'sudo modprobe uinput', and give your user access, e.g.:")
            print('  echo \'KERNEL=="uinput", TAG+="uaccess"\' | sudo tee /etc/udev/rules.d/60-uinput.rules')
            print("  sudo udevadm control --reload && sudo udevadm trigger /dev/uinput")
            sys.exit(1)
        self.move_accum_x = self.move_accum_y = 0.0
        self.scroll_accum_x = self.scroll_accum_y = 0.0
        self.notch_accum_x = self.notch_accum_y = 0

    def tap(self, action):
        """Perform a one-shot action (key tap or mouse click)."""
        if action == "click":
            dev, code = self.mouse, e.BTN_LEFT
        else:
            code = KEY_ACTIONS.get(action)
            if code is None:
                print(f"[warn] unknown action: {action!r} (see README for valid actions)")
                return
            dev = self.kbd
        dev.write(e.EV_KEY, code, 1)
        dev.syn()
        dev.write(e.EV_KEY, code, 0)
        dev.syn()

    def move(self, dx, dy):
        """Relative move; fractional pixels carry over so slow tilts still move."""
        self.move_accum_x += dx
        self.move_accum_y += dy
        ix, iy = int(self.move_accum_x), int(self.move_accum_y)
        self.move_accum_x -= ix
        self.move_accum_y -= iy
        if ix:
            self.mouse.write(e.EV_REL, e.REL_X, ix)
        if iy:
            self.mouse.write(e.EV_REL, e.REL_Y, iy)
        if ix or iy:
            self.mouse.syn()

    def _scroll_axis(self, notches, accum, notch_accum, hi_code, lo_code):
        # Hi-res units give smooth scrolling in apps that support it; the
        # classic wheel event goes out each time a whole notch has built up.
        accum += notches * HI_RES_PER_NOTCH
        hi = int(accum)
        accum -= hi
        sent = False
        if hi:
            self.mouse.write(e.EV_REL, hi_code, hi)
            notch_accum += hi
            whole = int(notch_accum / HI_RES_PER_NOTCH)
            if whole:
                self.mouse.write(e.EV_REL, lo_code, whole)
                notch_accum -= whole * HI_RES_PER_NOTCH
            sent = True
        return accum, notch_accum, sent

    def scroll(self, notches_x, notches_y):
        """Scroll by (possibly fractional) notches; +x is right, +y is up."""
        self.scroll_accum_x, self.notch_accum_x, sx = self._scroll_axis(
            notches_x, self.scroll_accum_x, self.notch_accum_x, e.REL_HWHEEL_HI_RES, e.REL_HWHEEL)
        self.scroll_accum_y, self.notch_accum_y, sy = self._scroll_axis(
            notches_y, self.scroll_accum_y, self.notch_accum_y, e.REL_WHEEL_HI_RES, e.REL_WHEEL)
        if sx or sy:
            self.mouse.syn()

    def reset_scroll(self, x, y):
        if x:
            self.scroll_accum_x, self.notch_accum_x = 0.0, 0
        if y:
            self.scroll_accum_y, self.notch_accum_y = 0.0, 0

    def close(self):
        self.kbd.close()
        self.mouse.close()


# --- Modes --------------------------------------------------------------------

def diagnose(pad, profile):
    """Print every input as it changes so you can find the right numbers,
    with the configured profile's name for each one."""
    names = profile.button_names()
    axis_names = {i: n for n, i in profile.axes.items()}
    print("\nDiagnostic mode. Press buttons / move sticks to see their numbers.")
    print("Press Ctrl+C to quit.\n")
    last_axis = {}
    while True:
        select.select([pad.fd], [], [])
        for kind, value in pad.read():
            if kind == "button":
                name = f"{names[value]}, " if value in names else ""
                print(f"button {value} pressed ({name}{e.BTN.get(pad.button_codes[value], '?')})")
            else:
                print(f"hat 0 -> {value}")
        for i, v in enumerate(pad.axes):
            # Report each axis once per push past halfway, not on every event.
            past = v > 0.5 or v < -0.5
            if past and not last_axis.get(i):
                label = f" ({axis_names[i]})" if i in axis_names else ""
                print(f"axis {i}{label} = {v:+.2f}")
            last_axis[i] = past


def axis_monitor(pad):
    """Live readout of every axis at once, so stick pairs are easy to spot."""
    print("\nAxis monitor. Move one stick at a time and watch which numbers change.")
    print("A trigger rests at -1.00; an idle stick rests near 0.00.")
    print("Press Ctrl+C to quit.\n")
    while True:
        pad.pump()
        print("  ".join(f"{i}:{v:+.2f}" for i, v in enumerate(pad.axes)))
        time.sleep(0.2)


def sample(pad, seconds, fn):
    t_end = time.monotonic() + seconds
    while (remaining := t_end - time.monotonic()) > 0:
        if select.select([pad.fd], [], [], remaining)[0]:
            pad.read()
            fn()


def setup_calibration(pad):
    """Guided first-time calibration: measure resting noise (deadzone) and
    true full-deflection range (axis_max) for each stick axis, then write
    them into config.json."""
    cfg = load_config()
    cfg_axes = cfg.get("axes", {})
    axis_names = {"move_x": 0, "move_y": 1, "scroll_x": DEFAULT_SCROLL_X, "scroll_y": DEFAULT_SCROLL_Y}
    indices = {name: cfg_axes.get(name, default) for name, default in axis_names.items()}
    indices = {name: idx for name, idx in indices.items() if idx is not None and idx < pad.num_axes()}

    print("\nCalibration step 1/2: leave both sticks centered (don't touch them).")
    input("Press Enter, then wait ~2 seconds...")
    pad.resync()
    max_noise = max((abs(pad.axes[i]) for i in indices.values()), default=0.0)

    def track_noise():
        nonlocal max_noise
        max_noise = max(max_noise, *(abs(pad.axes[i]) for i in indices.values()))
    sample(pad, 2.0, track_noise)
    deadzone = min(max(max_noise + 0.02, 0.05), 0.35)
    print(f"  measured rest noise = {max_noise:.3f}  ->  deadzone = {deadzone:.3f}")

    print("\nCalibration step 2/2: push each stick fully in every direction")
    print("(circle both sticks around their full range) for ~4 seconds.")
    input("Press Enter, then move the sticks...")
    axis_max = {name: 0.0 for name in axis_names}

    def track_max():
        for name, idx in indices.items():
            axis_max[name] = max(axis_max[name], abs(pad.axes[idx]))
    sample(pad, 4.0, track_max)
    for name in axis_max:
        if axis_max[name] < deadzone + 0.05:
            axis_max[name] = 1.0  # didn't see real movement; fall back to full range
        print(f"  {name}: max deflection = {axis_max[name]:.3f}")

    save_config_fields({"deadzone": round(deadzone, 3), "axis_max": {k: round(v, 3) for k, v in axis_max.items()}})
    print("\nSaved deadzone and axis_max to config.json. Run with --test to verify the feel.")


def test_zones(pad, cfg):
    """Live readout of the *computed* sensitivity zones (deadzone/percent/
    output speed), so you can sweep the stick through center, deadzone edge,
    quarter, half, and full push and confirm the mapping feels right."""
    deadzone = cfg.get("deadzone", 0.15)
    speed = cfg.get("mouse_speed", 18)
    axis_max = cfg.get("axis_max", {})
    ax_x = cfg.get("axes", {}).get("move_x", 0)
    ax_y = cfg.get("axes", {}).get("move_y", 1)
    n = pad.num_axes()

    print("\nZone test mode. Move the left stick through center, just past the")
    print("deadzone edge, quarter, half, and full push in each direction.")
    print("Press Ctrl+C to quit.\n")
    while True:
        pad.pump()
        raw_x = pad.axes[ax_x] if ax_x < n else 0.0
        raw_y = pad.axes[ax_y] if ax_y < n else 0.0
        sx = scale_axis(raw_x, deadzone, axis_max.get("move_x", 1.0))
        sy = scale_axis(raw_y, deadzone, axis_max.get("move_y", 1.0))
        zone_x = "DEADZONE" if sx == 0.0 else f"{abs(sx) * 100:5.1f}%"
        zone_y = "DEADZONE" if sy == 0.0 else f"{abs(sy) * 100:5.1f}%"
        print(
            f"x: raw={raw_x:+.2f} zone={zone_x:>8} px/tick={int(sx * speed):+4d}   "
            f"y: raw={raw_y:+.2f} zone={zone_y:>8} px/tick={int(sy * speed):+4d}"
        )
        time.sleep(0.1)


def drive(pad, out, cfg):
    """Translate controller input into virtual key/mouse events until the
    controller disconnects (raises OSError)."""
    deadzone = cfg.get("deadzone", 0.15)
    speed = cfg.get("mouse_speed", 18)
    poll_hz = cfg.get("poll_hz", 60)
    actions = {**cfg["buttons"], **cfg["bumpers"]}
    hat_map = cfg.get("hat", DEFAULT_HAT)
    axes_cfg = cfg.get("axes", {})
    ax_x = axes_cfg.get("move_x", 0)
    ax_y = axes_cfg.get("move_y", 1)
    ax_scroll_x = axes_cfg.get("scroll_x", DEFAULT_SCROLL_X)
    ax_scroll_y = axes_cfg.get("scroll_y", DEFAULT_SCROLL_Y)
    scroll_speed = cfg.get("scroll_speed", 12)
    scroll_invert = cfg.get("scroll_invert", False)
    scroll_invert_x = cfg.get("scroll_invert_x", False)
    axis_max = cfg.get("axis_max", {})
    max_move_x = axis_max.get("move_x", 1.0)
    max_move_y = axis_max.get("move_y", 1.0)
    max_scroll_x = axis_max.get("scroll_x", 1.0)
    max_scroll_y = axis_max.get("scroll_y", 1.0)

    n = pad.num_axes()
    def axis(idx, limit):
        return scale_axis(pad.axes[idx], deadzone, limit) if idx is not None and idx < n else 0.0

    interval = 1.0 / poll_hz
    next_tick = None  # set while a stick is deflected
    prev_hat = pad.hat

    while True:
        timeout = None if next_tick is None else max(0.0, next_tick - time.monotonic())
        if select.select([pad.fd], [], [], timeout)[0]:
            for kind, value in pad.read():
                # --- Buttons (edge-triggered) ---
                if kind == "button":
                    if value in actions:
                        out.tap(actions[value])
                # --- D-pad / hat (edge-triggered) ---
                elif value != prev_hat:
                    hx, hy = value
                    if hx != prev_hat[0]:
                        if hx == -1 and "left" in hat_map:
                            out.tap(hat_map["left"])
                        elif hx == 1 and "right" in hat_map:
                            out.tap(hat_map["right"])
                    if hy != prev_hat[1]:
                        if hy == 1 and "up" in hat_map:
                            out.tap(hat_map["up"])
                        elif hy == -1 and "down" in hat_map:
                            out.tap(hat_map["down"])
                    prev_hat = value

        vx, vy = axis(ax_x, max_move_x), axis(ax_y, max_move_y)
        sx, sy = axis(ax_scroll_x, max_scroll_x), axis(ax_scroll_y, max_scroll_y)
        out.reset_scroll(sx == 0.0, sy == 0.0)
        if not (vx or vy or sx or sy):
            next_tick = None  # sticks centered: sleep until the next event
            continue

        now = time.monotonic()
        if next_tick is None:
            next_tick = now  # first tick fires immediately
        if now < next_tick:
            continue
        # Skip missed ticks instead of bursting to catch up.
        next_tick = max(next_tick + interval, now)

        # --- Left stick -> mouse move (continuous) ---
        if vx or vy:
            out.move(vx * speed, vy * speed)

        # --- Right stick -> scroll wheel (continuous, both directions) ---
        # Stick right reads positive, which scrolls the page right; stick up
        # reads negative, so negate to scroll the page up.
        step_x = sx * scroll_speed / poll_hz
        step_y = -sy * scroll_speed / poll_hz
        if scroll_invert_x:
            step_x = -step_x
        if scroll_invert:
            step_y = -step_y
        if step_x or step_y:
            out.scroll(step_x, step_y)


def run(cfg):
    out = VirtualInput()
    try:
        while True:
            pad = wait_for_gamepad()
            print("\nRemote active. Ctrl+C to quit.\n")
            try:
                drive(pad, out, cfg)
            except OSError:
                print("Controller disconnected.")
            finally:
                pad.close()
    finally:
        out.close()


def main():
    parser = argparse.ArgumentParser(description="GameSir Cyclone 2 presentation remote")
    parser.add_argument("--diagnose", action="store_true",
                        help="print button/axis numbers as you press them")
    parser.add_argument("--axes", action="store_true",
                        help="live readout of every axis value at once")
    parser.add_argument("--setup", action="store_true",
                        help="calibrate deadzone/axis range for your controller")
    parser.add_argument("--test", action="store_true",
                        help="live readout of the computed sensitivity zones")
    args = parser.parse_args()

    try:
        if args.axes or args.diagnose or args.setup or args.test:
            pad = wait_for_gamepad()
            try:
                if args.axes:
                    axis_monitor(pad)
                elif args.diagnose:
                    diagnose(pad, load_config()["profile"])
                elif args.setup:
                    setup_calibration(pad)
                else:
                    test_zones(pad, load_config())
            finally:
                pad.close()
        else:
            run(load_config())
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    main()
