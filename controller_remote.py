"""
GameSir Cyclone 2 -> keyboard/mouse presentation remote.

Reads a gamepad with pygame and synthesizes keyboard/mouse events with pynput so
you can drive slides (and a bit of mouse) from the controller while lecturing.

Usage:
    python controller_remote.py            # run the remote
    python controller_remote.py --diagnose # print button/axis numbers as you press them
    python controller_remote.py --axes     # live readout of every axis value at once

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
            vx = js.get_axis(ax_x)
            vy = js.get_axis(ax_y)
            if abs(vx) < deadzone:
                vx = 0.0
            if abs(vy) < deadzone:
                vy = 0.0
            if vx or vy:
                mouse.move(int(vx * speed), int(vy * speed))

        # --- Right stick -> scroll wheel (continuous, both directions) ---
        dx = dy = 0
        if ax_scroll_x is not None and ax_scroll_x < js.get_numaxes():
            vs = js.get_axis(ax_scroll_x)
            if abs(vs) < deadzone:
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
            vs = js.get_axis(ax_scroll_y)
            if abs(vs) < deadzone:
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
    args = parser.parse_args()

    js = init_joystick()
    try:
        if args.axes:
            axis_monitor(js)
        elif args.diagnose:
            diagnose(js)
        else:
            cfg = load_config()
            run(js, cfg)
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
