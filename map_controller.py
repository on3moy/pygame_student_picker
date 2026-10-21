"""
Map a controller's buttons by pressing them.

The default is a window with a drawing of a pad and the list of standard
names: press something on the pad, type its name (A, LB, l1 = LB...), Enter.
Ctrl+S names the template and saves it, Ctrl+O loads the next saved one.
Holding a mapped input lights it up, so loading a template also tests it.

Two terminal modes stay for when there is no screen: --terminal names each
control in turn - "Press LB - left bumper" - and you press it; --free is
press anything, then type its name.

The result is saved to controllers/<profile>.json for this OS, and the
configs then say "LB" instead of a number that may belong to another button.

Usage:
    uv run map_controller.py                    # window; pick a template inside it
    uv run map_controller.py gamesir_cyclone2   # window, starting on that template
    uv run map_controller.py --terminal gamesir_cyclone2   # guided, in the terminal
    uv run map_controller.py --free gamesir_cyclone2       # press anything, type its name
    uv run map_controller.py --list             # show the profiles in controllers/
    uv run map_controller.py --show gamesir_cyclone2
    uv run map_controller.py --use gamesir_cyclone2   # point this OS's configs at a profile

Nothing is written until you save (Ctrl+S in the window, or confirm at the
end in the terminal).

Numbers come from pygame, the same as the picker; on Linux pygame is told to
use the kernel driver so they also match controller_remote.py.
"""

import argparse
import json
import os
import select
import sys
import time

import controllers
from controllers import OS_KEY, STANDARD, STANDARD_NAMES

# Same order as controller_remote.py's evdev numbering on Linux, rather than
# SDL's HIDAPI drivers, which number some pads differently.
if OS_KEY == "linux":
    os.environ.setdefault("SDL_JOYSTICK_HIDAPI", "0")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# The video driver is chosen in main(): none for the terminal modes, native
# Wayland for the window. SDL reads these hints at pygame.init(), not import.

import pygame  # noqa: E402  (after the SDL hints above)

from controllers.capture import Burst, assign, held, rest_values, what_was  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OS_DIR = os.path.join(ROOT, OS_KEY)
REMOTE_CONFIG = os.path.join(OS_DIR, "config.json")
PICKER_CONFIG = os.path.join(OS_DIR, "mini_config.json")


def ask(prompt, default=""):
    try:
        reply = input(prompt).strip()
    except EOFError:
        return default
    return reply or default


def yes(prompt, default=True):
    reply = ask(f"{prompt} [{'Y/n' if default else 'y/N'}] ").lower()
    return default if not reply else reply.startswith("y")


def open_pad(index):
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No controller detected - waiting (Ctrl+C to quit)...")
        while pygame.joystick.get_count() == 0:
            pygame.event.pump()
            time.sleep(0.5)
            pygame.joystick.quit()
            pygame.joystick.init()
    if index >= pygame.joystick.get_count():
        sys.exit(f"Only {pygame.joystick.get_count()} controller(s) connected; no joystick {index}.")
    pad = pygame.joystick.Joystick(index)
    pad.init()
    return pad


def device_info(pad):
    info = {"name": pad.get_name(), "guid": pad.get_guid()}
    print(f"Controller: {info['name']}  buttons={pad.get_numbuttons()} "
          f"axes={pad.get_numaxes()} hats={pad.get_numhats()}")
    return info


def keyboard_line():
    """A line typed in the terminal, or None if nothing is waiting.
    End of input reads as 'q'."""
    if os.name == "nt":
        import msvcrt
        return input().strip() if msvcrt.kbhit() else None
    if select.select([sys.stdin], [], [], 0)[0]:
        line = sys.stdin.readline()
        return line.strip() if line else "q"
    return None


def wait_for_input(pad, rest, keyboard=False):
    """Block until the pad does something - or, with keyboard=True, until a
    line is typed. Returns (typed, buttons, axes, hat_seen)."""
    pygame.event.clear()
    burst = Burst(rest)
    while True:
        if keyboard and not burst.started:
            typed = keyboard_line()
            if typed is not None:
                return typed, [], [], False
        for ev in pygame.event.get():
            burst.feed(ev)
        got = burst.ready()
        if got:
            return (None, *got)
        time.sleep(0.01)


def wait_for_release(pad, rest):
    """Let go of everything before the next prompt, so a held stick does
    not immediately count as the next input."""
    while True:
        pygame.event.pump()
        if not held(pad, rest):
            return
        time.sleep(0.02)


def describe(table, index):
    names = [n for n, i in table.items() if i == index]
    return f" (now {'/'.join(names)})" if names else ""


def guided_session(pad, buttons, axes):
    """Ask for each standard control in turn and record what the pad sends."""
    rest = rest_values(pad)
    print("\nPress each control as it is asked for.")
    print("Enter skips one (keeps what it had), 'q' + Enter finishes, Ctrl+C finishes.\n")
    taken = {}  # ("button" | "axis", number) -> name, settled this session
    try:
        for step, (name, kind, desc) in enumerate(STANDARD, 1):
            while True:
                print(f"[{step:2}/{len(STANDARD)}] Press {name:<4}  {desc}: ", end="", flush=True)
                typed, pressed, moved, hat = wait_for_input(pad, rest, keyboard=True)
                if typed is not None:
                    if typed.lower() == "q":
                        print("finished")
                        return
                    print("skipped")
                    break
                got_buttons = pressed if kind in ("button", "trigger") else []
                got_axes = moved[:1] if kind in ("axis", "trigger") else []
                wait_for_release(pad, rest)
                if not got_buttons and not got_axes:
                    expected = "a stick" if kind == "axis" else "a button"
                    print(f"got {what_was(pressed, moved, hat)}, expected {expected} - try again")
                    continue
                inputs = [("button", b) for b in got_buttons] + [("axis", a) for a in got_axes]
                clash = next((taken[i] for i in inputs if i in taken), None)
                if clash:
                    print(f"{what_was(got_buttons, got_axes, False)} is already {clash} - try again")
                    continue
                for b in got_buttons:
                    assign(buttons, name, b)
                for a in got_axes:
                    assign(axes, name, a)
                taken.update({i: name for i in inputs})
                print(what_was(got_buttons, got_axes, False))
                break
    except KeyboardInterrupt:
        print()


def ask_name(prompt, aliases):
    """A standard name for what was just pressed, '' to skip, 'q' to finish.
    Aliases are translated (l1 -> LB); anything else needs a confirmation."""
    while True:
        typed = ask(prompt)
        if typed.lower() in ("", "q"):
            return typed.lower()
        name = controllers.canonical(typed, aliases)
        if name:
            if name != typed.upper():
                print(f"  {typed} -> {name}")
            return name
        print(f"  '{typed}' is not a standard name. Use one of: {' '.join(STANDARD_NAMES)}")
        if yes(f"  Keep '{typed.upper()}' anyway as a custom name?", default=False):
            return typed.upper()


def free_session(pad, buttons, axes, aliases):
    """Press anything, then type its name."""
    rest = rest_values(pad)
    print("\nPress a button, pull a trigger or push a stick, then type its name.")
    print(f"Names: {' '.join(STANDARD_NAMES)}  (aliases like L1, START work too)")
    print("Enter on an empty name skips it, 'q' finishes, Ctrl+C finishes.\n")
    hat_noted = False
    try:
        while True:
            print("Waiting for the pad...", end="", flush=True)
            _typed, pressed, moved, hat = wait_for_input(pad, rest)
            print("\r" + " " * 24 + "\r", end="")
            if hat and not pressed and not moved:
                if not hat_noted:
                    print("D-pad: that is a hat (directions, not buttons) - nothing to name.")
                    hat_noted = True
                wait_for_release(pad, rest)
                continue
            moved = moved[:1]  # a diagonal push counts as its main axis
            parts = [f"button {b}{describe(buttons, b)}" for b in pressed]
            parts += [f"axis {a}{describe(axes, a)}" for a in moved]
            name = ask_name(f"{' + '.join(parts)} -> name: ", aliases)
            if name == "q":
                break
            if name:
                for b in pressed:
                    assign(buttons, name, b)
                for a in moved:
                    assign(axes, name, a)
                print(f"  saved {name}")
            wait_for_release(pad, rest)
    except KeyboardInterrupt:
        print()


def print_layout(buttons, axes):
    print("  buttons: " + ("  ".join(f"{n}={i}" for n, i in sorted(buttons.items(), key=lambda kv: kv[1])) or "none"))
    print("  axes:    " + ("  ".join(f"{n}={i}" for n, i in sorted(axes.items(), key=lambda kv: kv[1])) or "none"))


def edit_json(path, change):
    """Read-modify-write a config, keeping its other keys and comments."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    change(cfg)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def use_profile(key):
    """Point this OS's remote and picker configs at the profile."""
    controllers.load_profile(key)  # fail loudly on a typo before writing anything
    done = []
    if os.path.exists(REMOTE_CONFIG):
        edit_json(REMOTE_CONFIG, lambda cfg: cfg.__setitem__("controller_profile", key))
        done.append(os.path.relpath(REMOTE_CONFIG, ROOT))
    if os.path.exists(PICKER_CONFIG):
        edit_json(PICKER_CONFIG, lambda cfg: cfg.setdefault("controller", {}).__setitem__("profile", key))
        done.append(os.path.relpath(PICKER_CONFIG, ROOT))
    print(f"Using {key} in: {', '.join(done) or 'no configs found'}")
    return done


def current_profile_key():
    """The profile this OS's configs already use, if any."""
    for path, get in ((REMOTE_CONFIG, lambda c: c.get("controller_profile")),
                      (PICKER_CONFIG, lambda c: c.get("controller", {}).get("profile"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = get(json.load(f))
        except (OSError, ValueError):
            continue
        if key:
            return key
    return None


def main():
    parser = argparse.ArgumentParser(description="Map controller buttons to names, saved in controllers/")
    parser.add_argument("profile", nargs="?", help="profile name (file in controllers/ without .json)")
    parser.add_argument("--terminal", action="store_true",
                        help="guided mapping in the terminal (it names each control, you press it)")
    parser.add_argument("--free", action="store_true",
                        help="in the terminal: press anything, then type its name")
    parser.add_argument("--list", action="store_true", help="list the profiles in controllers/")
    parser.add_argument("--show", metavar="PROFILE", help="print a profile's layout for this OS")
    parser.add_argument("--use", metavar="PROFILE", help="point this OS's configs at PROFILE")
    parser.add_argument("--joystick", type=int, default=0, help="which pad, if several are connected")
    args = parser.parse_args()

    if args.list:
        for key in controllers.list_profiles():
            print(f"{key:24} {controllers.load_profile(key).title}")
        return
    if args.show:
        p = controllers.load_profile(args.show)
        print(f"{p.title} ({OS_KEY}):")
        print_layout(p.buttons, p.axes)
        return
    if args.use:
        use_profile(args.use)
        return

    if OS_KEY == "linux" and os.system("pgrep -f controller_remote.py >/dev/null 2>&1") == 0:
        print("Note: controller_remote.py is running, so pad presses will also type keys here.")
        print("      Stop it (Ctrl+C in its terminal) for a cleaner mapping session.\n")

    window = not (args.terminal or args.free)
    if not window:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # no window needed
    elif os.environ.get("WAYLAND_DISPLAY"):
        # pygame 2.6's SDL would otherwise go through XWayland.
        os.environ.setdefault("SDL_VIDEODRIVER", "wayland")

    pad = open_pad(args.joystick)
    device = device_info(pad)

    if window:
        from controllers import mapper_window
        mapper_window.run(pad, device, args.profile or current_profile_key(),
                          save=controllers.save_layout, use=use_profile,
                          in_use=current_profile_key)
        return

    key = args.profile
    if not key:
        existing = controllers.list_profiles()
        default = current_profile_key() or controllers.slugify(device["name"])
        print(f"Profiles in controllers/: {', '.join(existing) or 'none yet'}")
        key = controllers.slugify(ask(f"Profile to map [{default}]: ", default))

    try:
        profile = controllers.load_profile(key)
        print(f"Updating {profile.title} ({key}.json), {OS_KEY} section. Current:")
        print_layout(profile.buttons, profile.axes)
        title = None
    except OSError:
        print(f"New profile controllers/{key}.json")
        profile = controllers.Profile(key, {})
        title = ask(f"Controller name [{device['name']}]: ", device["name"])

    buttons, axes = dict(profile.buttons), dict(profile.axes)
    if args.free:
        free_session(pad, buttons, axes, profile.aliases)
    else:
        guided_session(pad, buttons, axes)

    print("\nResult:")
    print_layout(buttons, axes)
    if (buttons, axes) == (profile.buttons, profile.axes):
        print("No changes.")
    elif yes(f"Save to controllers/{key}.json?"):
        path = controllers.save_layout(key, buttons, axes, title=title,
                                       device={"name": device["name"]})
        print(f"Saved {os.path.relpath(path, ROOT)}")
    else:
        print("Not saved.")
        return

    if current_profile_key() != key and yes(f"Use {key} in {OS_KEY}/config.json and {OS_KEY}/mini_config.json?"):
        use_profile(key)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
