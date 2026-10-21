"""
Reading what a pad does, shared by map_controller.py's terminal modes and the
mapper window. Needs pygame imported (and its joystick module initialised) by
the caller, after any SDL hints are set.
"""

import time

import pygame

AXIS_TRIGGER = 0.6     # how far an axis must move from rest to count
SETTLE_SECONDS = 0.25  # gather the burst one press makes (LT = button + axis)


def rest_values(pad):
    """Each axis's idle value (triggers rest at -1, sticks near 0)."""
    for _ in range(10):
        pygame.event.pump()
        time.sleep(0.02)
    return [pad.get_axis(i) for i in range(pad.get_numaxes())]


class Burst:
    """Collects the events one press makes. Feed it pygame events; ready()
    returns (buttons, axes, hat_seen) once SETTLE_SECONDS have passed since
    the first one, so a trigger that sends both a button and an axis comes
    back as one press. Axes are listed largest move first."""

    def __init__(self, rest):
        self.rest = rest
        self.clear()

    def clear(self):
        self.buttons, self.moved, self.hat = [], {}, False
        self.deadline = None

    def feed(self, ev):
        rest = self.rest
        if ev.type == pygame.JOYBUTTONDOWN and ev.button not in self.buttons:
            self.buttons.append(ev.button)
        elif ev.type == pygame.JOYAXISMOTION and ev.axis < len(rest) \
                and abs(ev.value - rest[ev.axis]) > AXIS_TRIGGER:
            self.moved[ev.axis] = max(self.moved.get(ev.axis, 0), abs(ev.value - rest[ev.axis]))
        elif ev.type == pygame.JOYHATMOTION and ev.value != (0, 0):
            self.hat = True
        else:
            return
        if self.deadline is None:
            self.deadline = time.monotonic() + SETTLE_SECONDS

    @property
    def started(self):
        return self.deadline is not None

    def ready(self):
        """(buttons, axes, hat) once the burst has settled, else None."""
        if self.deadline is None or time.monotonic() < self.deadline:
            return None
        out = (self.buttons, sorted(self.moved, key=self.moved.get, reverse=True), self.hat)
        self.clear()
        return out


def held(pad, rest):
    """True while any button is down or any axis is off rest."""
    if any(pad.get_button(i) for i in range(pad.get_numbuttons())):
        return True
    return any(abs(pad.get_axis(i) - rest[i]) > AXIS_TRIGGER / 2 for i in range(len(rest)))


def assign(table, name, index):
    """name -> index, dropping any other name that pointed at index."""
    for other in [n for n, i in table.items() if i == index and n != name]:
        del table[other]
    table[name] = index


def what_was(pressed, moved, hat):
    parts = [f"button {b}" for b in pressed] + [f"axis {a}" for a in moved]
    return " + ".join(parts) or ("the D-pad" if hat else "nothing")
