"""
GameSir Cyclone 2 -> keyboard/mouse presentation remote.

Reads a gamepad with pygame and synthesizes keyboard/mouse events with pynput so
you can drive slides (and a bit of mouse) from the controller while lecturing.

Usage:
    python controller_remote.py            # run the remote
    python controller_remote.py --diagnose # print button/axis numbers as you press them
    python controller_remote.py --axes     # live readout of every axis value at once
    python controller_remote.py --setup    # calibrate deadzone/axis range for your controller
    python controller_remote.py --test     # live readout of the computed sensitivity zones

Edit config.json to remap inputs. Press Ctrl+C in the terminal to quit.
"""

import argparse
import json
import os
import sys
import time

import pygame
from pynput.keyboard import Controller as Keyboard, Key
from pynput.mouse import Button, Controller as Mouse

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

keyboard = Keyboard()
mouse = Mouse()

# Action strings (from config) -> what they do.
# Keyboard taps map to a pynput key; "click" is handled specially.
KEY_ACTIONS = {
    "left": Key.left,
    "right": Key.right,
    "up": Key.up,
    "down": Key.down,
    "pageup": Key.page_up,
    "pagedown": Key.page_down,
    "f5": Key.f5,
    "esc": Key.esc,
    "space": Key.space,
    "home": Key.home,
    "end": Key.end,
    "b": "b",  # PowerPoint/Slides black-screen toggle
    "w": "w",  # PowerPoint white-screen toggle
    "f": "f",  # full screen
}


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Normalize json string keys to ints where we index by number.
    cfg["buttons"] = {int(k): v for k, v in cfg.get("buttons", {}).items()}
    cfg["bumpers"] = {int(k): v for k, v in cfg.get("bumpers", {}).items()}
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


def tap(action):
    """Perform a one-shot action (key tap or mouse click)."""
    if action == "click":
        mouse.click(Button.left, 1)
        return
    key = KEY_ACTIONS.get(action)
    if key is None:
        print(f"[warn] unknown action: {action!r} (see README for valid actions)")
        return
    keyboard.press(key)
    keyboard.release(key)


def init_joystick():
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No controller detected. Connect the GameSir Cyclone 2 (USB or Bluetooth) "
              "and try again.")
        sys.exit(1)
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"Controller: {js.get_name()}")
    print(f"  buttons={js.get_numbuttons()}  axes={js.get_numaxes()}  hats={js.get_numhats()}")
    return js


def diagnose(js):
    """Print every input as it changes so you can find the right numbers."""
    print("\nDiagnostic mode. Press buttons / move sticks to see their numbers.")
    print("Press Ctrl+C to quit.\n")
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                print(f"button {event.button} pressed")
            elif event.type == pygame.JOYHATMOTION:
                print(f"hat {event.hat} -> {event.value}")
            elif event.type == pygame.JOYAXISMOTION:
                if abs(event.value) > 0.5:
                    print(f"axis {event.axis} = {event.value:+.2f}")
        clock.tick(60)


def axis_monitor(js):
    """Live readout of every axis at once, so stick pairs are easy to spot."""
    print("\nAxis monitor. Move one stick at a time and watch which numbers change.")
    print("A trigger rests at -1.00; an idle stick rests near 0.00.")
    print("Press Ctrl+C to quit.\n")
    n = js.get_numaxes()
    clock = pygame.time.Clock()
    while True:
        pygame.event.pump()
        row = "  ".join(f"{i}:{js.get_axis(i):+.2f}" for i in range(n))
        print(row)
        clock.tick(5)


def setup_calibration(js):
    """Guided first-time calibration: measure resting noise (deadzone) and
    true full-deflection range (axis_max) for each stick axis, then write
    them into config.json."""
    axis_names = {"move_x": 0, "move_y": 1, "scroll_x": 2, "scroll_y": 3}
    cfg = load_config()
    cfg_axes = cfg.get("axes", {})
    indices = {name: cfg_axes.get(name, default) for name, default in axis_names.items()}
    n = js.get_numaxes()
    clock = pygame.time.Clock()

    print("\nCalibration step 1/2: leave both sticks centered (don't touch them).")
    input("Press Enter, then wait ~2 seconds...")
    max_noise = 0.0
    t_end = time.time() + 2.0
    while time.time() < t_end:
        pygame.event.pump()
        for idx in indices.values():
            if idx is not None and idx < n:
                max_noise = max(max_noise, abs(js.get_axis(idx)))
        clock.tick(60)
    deadzone = min(max(max_noise + 0.02, 0.05), 0.35)
    print(f"  measured rest noise = {max_noise:.3f}  ->  deadzone = {deadzone:.3f}")

    print("\nCalibration step 2/2: push each stick fully in every direction")
    print("(circle both sticks around their full range) for ~4 seconds.")
    input("Press Enter, then move the sticks...")
    axis_max = {name: 0.0 for name in axis_names}
    t_end = time.time() + 4.0
    while time.time() < t_end:
        pygame.event.pump()
        for name, idx in indices.items():
            if idx is not None and idx < n:
                axis_max[name] = max(axis_max[name], abs(js.get_axis(idx)))
        clock.tick(60)
    for name in axis_max:
        if axis_max[name] < deadzone + 0.05:
            axis_max[name] = 1.0  # didn't see real movement; fall back to full range
        print(f"  {name}: max deflection = {axis_max[name]:.3f}")

    save_config_fields({"deadzone": round(deadzone, 3), "axis_max": {k: round(v, 3) for k, v in axis_max.items()}})
    print("\nSaved deadzone and axis_max to config.json. Run with --test to verify the feel.")


def test_zones(js, cfg):
    """Live readout of the *computed* sensitivity zones (deadzone/percent/
    output speed), so you can sweep the stick through center, deadzone edge,
    quarter, half, and full push and confirm the mapping feels right."""
    deadzone = cfg.get("deadzone", 0.15)
    speed = cfg.get("mouse_speed", 18)
    axis_max = cfg.get("axis_max", {})
    ax_x = cfg.get("axes", {}).get("move_x", 0)
    ax_y = cfg.get("axes", {}).get("move_y", 1)
    n = js.get_numaxes()

    print("\nZone test mode. Move the left stick through center, just past the")
    print("deadzone edge, quarter, half, and full push in each direction.")
    print("Press Ctrl+C to quit.\n")
    clock = pygame.time.Clock()
    while True:
        pygame.event.pump()
        raw_x = js.get_axis(ax_x) if ax_x < n else 0.0
        raw_y = js.get_axis(ax_y) if ax_y < n else 0.0
        sx = scale_axis(raw_x, deadzone, axis_max.get("move_x", 1.0))
        sy = scale_axis(raw_y, deadzone, axis_max.get("move_y", 1.0))
        zone_x = "DEADZONE" if sx == 0.0 else f"{abs(sx) * 100:5.1f}%"
        zone_y = "DEADZONE" if sy == 0.0 else f"{abs(sy) * 100:5.1f}%"
        print(
            f"x: raw={raw_x:+.2f} zone={zone_x:>8} px/tick={int(sx * speed):+4d}   "
            f"y: raw={raw_y:+.2f} zone={zone_y:>8} px/tick={int(sy * speed):+4d}"
        )
        clock.tick(10)


def run(js, cfg):
    deadzone = cfg.get("deadzone", 0.15)
    speed = cfg.get("mouse_speed", 18)
    poll_hz = cfg.get("poll_hz", 60)
    buttons = cfg["buttons"]
    bumpers = cfg["bumpers"]
    hat_map = cfg.get("hat", {})
    ax_x = cfg.get("axes", {}).get("move_x", 0)
    ax_y = cfg.get("axes", {}).get("move_y", 1)
    ax_scroll_x = cfg.get("axes", {}).get("scroll_x", 2)
    ax_scroll_y = cfg.get("axes", {}).get("scroll_y", 3)
    scroll_speed = cfg.get("scroll_speed", 12)
    scroll_invert = cfg.get("scroll_invert", False)
    scroll_invert_x = cfg.get("scroll_invert_x", False)
    axis_max = cfg.get("axis_max", {})
    max_move_x = axis_max.get("move_x", 1.0)
    max_move_y = axis_max.get("move_y", 1.0)
    max_scroll_x = axis_max.get("scroll_x", 1.0)
    max_scroll_y = axis_max.get("scroll_y", 1.0)

    # Track previous pressed-state so each press fires exactly once.
    prev_buttons = {}
    prev_hat = (0, 0)
    # Fractional scroll carried between frames so slow stick tilts still scroll.
    scroll_accum_x = 0.0
    scroll_accum_y = 0.0

    print("\nRemote active. Ctrl+C to quit.\n")
    clock = pygame.time.Clock()
    while True:
        pygame.event.pump()

        # --- Buttons (edge-triggered) ---
        for idx, action in {**buttons, **bumpers}.items():
            if idx >= js.get_numbuttons():
                continue
            pressed = js.get_button(idx) == 1
            if pressed and not prev_buttons.get(idx, False):
                tap(action)
            prev_buttons[idx] = pressed

        # --- D-pad / hat (edge-triggered) ---
        if js.get_numhats() > 0:
            hx, hy = js.get_hat(0)
            if (hx, hy) != prev_hat:
                if hx == -1 and "left" in hat_map:
                    tap(hat_map["left"])
                elif hx == 1 and "right" in hat_map:
                    tap(hat_map["right"])
                if hy == 1 and "up" in hat_map:
                    tap(hat_map["up"])
                elif hy == -1 and "down" in hat_map:
                    tap(hat_map["down"])
                prev_hat = (hx, hy)

        # --- Left stick -> mouse move (continuous) ---
        if ax_x < js.get_numaxes() and ax_y < js.get_numaxes():
            vx = scale_axis(js.get_axis(ax_x), deadzone, max_move_x)
            vy = scale_axis(js.get_axis(ax_y), deadzone, max_move_y)
            if vx or vy:
                mouse.move(int(vx * speed), int(vy * speed))

        # --- Right stick -> scroll wheel (continuous, both directions) ---
        dx = dy = 0
        if ax_scroll_x is not None and ax_scroll_x < js.get_numaxes():
            vs = scale_axis(js.get_axis(ax_scroll_x), deadzone, max_scroll_x)
            if vs == 0.0:
                scroll_accum_x = 0.0
            else:
                # Stick right reads positive, which scrolls the page right.
                step = vs * scroll_speed / poll_hz
                if scroll_invert_x:
                    step = -step
                scroll_accum_x += step
                dx = int(scroll_accum_x)
                scroll_accum_x -= dx
        if ax_scroll_y is not None and ax_scroll_y < js.get_numaxes():
            vs = scale_axis(js.get_axis(ax_scroll_y), deadzone, max_scroll_y)
            if vs == 0.0:
                scroll_accum_y = 0.0
            else:
                # Stick up reads negative, so negate to scroll the page up.
                step = -vs * scroll_speed / poll_hz
                if scroll_invert:
                    step = -step
                scroll_accum_y += step
                dy = int(scroll_accum_y)
                scroll_accum_y -= dy
        if dx or dy:
            mouse.scroll(dx, dy)

        clock.tick(poll_hz)


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

    js = init_joystick()
    try:
        if args.axes:
            axis_monitor(js)
        elif args.diagnose:
            diagnose(js)
        elif args.setup:
            setup_calibration(js)
        elif args.test:
            test_zones(js, load_config())
        else:
            cfg = load_config()
            run(js, cfg)
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
