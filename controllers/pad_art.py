"""
A front view of a GameSir Cyclone 2, drawn with pygame for the mapper window.

Xbox layout: left stick top-left in a red ring, a gold plus D-pad in a
textured well, the right stick bottom-right, ABXY top-right. Home (logo, with
a lit ring) sits top centre between View and Menu, Share below it, then the
four player LEDs and the M button between the D-pad and the right stick.
Gold bumpers and clear triggers on top. Two skins: the frosted white edition
and the black one.

The shell is drawn once per skin at 2x and scaled down (cheap anti-aliasing);
the buttons are drawn every frame because their state changes.
"""

import pygame
from pygame import gfxdraw

SS = 2  # supersampling for the static shell

SKINS = {
    "white": dict(
        shell=(234, 237, 241), glow=(172, 202, 238), edge=(158, 168, 184), seam=(204, 210, 220),
        well=(220, 225, 232), ring=(206, 44, 44), rim=(248, 248, 250), cap=(196, 196, 190),
        knurl=(172, 172, 166), face=(216, 218, 216), letter=(118, 120, 126),
        dpad=(186, 148, 84), dpad_hi=(216, 182, 120), bumper=(184, 146, 86), bumper_text=(255, 248, 232),
        trigger=(206, 220, 234), trigger_text=(84, 96, 114), small=(214, 218, 226),
        home=(226, 230, 236), led=(104, 192, 255), logo=(146, 154, 168)),
    "black": dict(
        shell=(44, 47, 55), glow=(32, 58, 98), edge=(84, 90, 104), seam=(70, 76, 88),
        well=(34, 36, 43), ring=(26, 28, 32), rim=(66, 118, 196), cap=(54, 57, 64),
        knurl=(40, 42, 48), face=(34, 36, 42), letter=(216, 222, 230),
        dpad=(36, 38, 44), dpad_hi=(64, 68, 78), bumper=(50, 53, 60), bumper_text=(216, 222, 230),
        trigger=(58, 66, 80), trigger_text=(202, 208, 218), small=(30, 32, 38),
        home=(36, 38, 45), led=(104, 192, 255), logo=(118, 126, 140)),
}

STICK_R, FACE_R, HOME_R = 38, 15, 17
DPAD_C, DPAD_S = (262, 282), 24  # centre and arm width
L_STICK, R_STICK = (205, 215), (385, 282)

# name -> (kind, geometry, badge position or None). Circles are (cx, cy, r),
# everything else a rect. The D-pad arms are only named on pads that send them
# as buttons (Windows); on Linux the D-pad is a hat and lights up by itself.
_dx, _dy = DPAD_C[0] - DPAD_S // 2, DPAD_C[1] - DPAD_S // 2
LAYOUT = {
    "LT": ("trigger", (160, 96, 100, 36), None),
    "RT": ("trigger", (380, 96, 100, 36), None),
    "LB": ("bumper", (148, 128, 124, 24), None),
    "RB": ("bumper", (368, 128, 124, 24), None),
    "VIEW": ("small", (262, 184, 22, 12), (273, 207)),
    "MENU": ("small", (356, 184, 22, 12), (367, 207)),
    "HOME": ("home", (320, 176, HOME_R), (320, 150)),
    "L3": ("stick", (*L_STICK, STICK_R), None),
    "R3": ("stick", (*R_STICK, STICK_R), None),
    "Y": ("face", (448, 185, FACE_R), (448, 163)),
    "X": ("face", (418, 215, FACE_R), (418, 239)),
    "B": ("face", (478, 215, FACE_R), (478, 239)),
    "A": ("face", (448, 245, FACE_R), (448, 266)),
    "LX": ("tag", (112, 206, 44, 18), None),
    "LY": ("tag", (183, 257, 44, 18), None),
    "RX": ("tag", (432, 282, 44, 18), None),
    "RY": ("tag", (363, 324, 44, 18), None),
    "D-UP": ("dpad", (_dx, _dy - DPAD_S, DPAD_S, DPAD_S), None),
    "D-DOWN": ("dpad", (_dx, _dy + DPAD_S, DPAD_S, DPAD_S), None),
    "D-LEFT": ("dpad", (_dx - DPAD_S, _dy, DPAD_S, DPAD_S), None),
    "D-RIGHT": ("dpad", (_dx + DPAD_S, _dy, DPAD_S, DPAD_S), None),
}
HAT_ARMS = {(0, 1): "D-UP", (0, -1): "D-DOWN", (-1, 0): "D-LEFT", (1, 0): "D-RIGHT"}

# Right half of the shell outline, top centre round to bottom centre; the
# left half is its mirror. Smoothed with a Catmull-Rom spline.
_RIGHT = [(320, 148), (390, 146), (455, 150), (510, 162), (545, 185), (565, 225),
          (580, 285), (597, 355), (608, 410), (600, 445), (572, 460), (540, 450),
          (510, 415), (482, 375), (450, 352), (400, 345)]
_SQUEEZE = 0.93  # narrow it a little so the list fits beside it
_GRIP = 0.8      # and shorten the grips, so they clear the message line


def _outline():
    pts = _RIGHT + [(320, 346)] + [(640 - x, y) for x, y in reversed(_RIGHT[1:])]
    pts = [(320 + (x - 320) * _SQUEEZE, y if y < 285 else 285 + (y - 285) * _GRIP)
           for x, y in pts]
    out, n = [], len(pts)
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        for s in range(8):
            t = s / 8
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t
                                    + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3)
                             for k in (0, 1)))
    return out


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render_shell(skin, size):
    """The static body: shell with its glow, wells, seams, Share, M, LEDs and
    the wordmark. Returns a size-sized SRCALPHA surface."""
    k = SKINS[skin]
    w, h = size
    big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
    pts = [(x * SS, y * SS) for x, y in _outline()]

    # Shell: a vertical gradient (solid at the top, glowing toward the grips),
    # cut to the outline by multiplying with a mask.
    shade = pygame.Surface(big.get_size(), pygame.SRCALPHA)
    top, bottom = 150 * SS, 425 * SS
    for y in range(top, bottom + 1):
        t = max(0.0, (y - 280 * SS) / (bottom - 280 * SS))
        pygame.draw.line(shade, (*_lerp(k["shell"], k["glow"], t), 255), (0, y), (w * SS, y))
    mask = pygame.Surface(big.get_size(), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), pts)
    shade.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    big.blit(shade, (0, 0))
    pygame.draw.polygon(big, k["edge"], pts, 2 * SS)

    def P(x, y):
        return int(x * SS), int(y * SS)

    # Panel seams running out from Home.
    for line in (((236, 152), (300, 170)), ((404, 152), (340, 170)),
                 ((292, 240), (320, 228), (348, 240)), ((320, 194), (320, 228))):
        pygame.draw.lines(big, k["seam"], False, [P(*p) for p in line], SS)

    # Stick wells and the textured D-pad well.
    for c in (L_STICK, R_STICK):
        pygame.draw.circle(big, k["well"], P(*c), 46 * SS)
    pygame.draw.circle(big, k["well"], P(*DPAD_C), 46 * SS)
    for r in range(30, 46, 3):
        pygame.draw.circle(big, k["seam"], P(*DPAD_C), r * SS, 1)

    # Share (below Home), M (between the D-pad and the right stick), LEDs.
    pygame.draw.rect(big, k["small"], (*P(310, 205), 20 * SS, 9 * SS), border_radius=5 * SS)
    pygame.draw.rect(big, k["edge"], (*P(310, 205), 20 * SS, 9 * SS), SS, border_radius=5 * SS)
    pygame.draw.rect(big, k["small"], (*P(312, 301), 22 * SS, 11 * SS), border_radius=6 * SS)
    pygame.draw.rect(big, k["edge"], (*P(312, 301), 22 * SS, 11 * SS), SS, border_radius=6 * SS)
    font = pygame.font.Font(None, 11 * SS)
    m = font.render("M", True, k["logo"])
    big.blit(m, m.get_rect(center=P(323, 307)))
    for i in range(4):
        pygame.draw.rect(big, k["led"], (*P(317, 244 + i * 8), 12 * SS, 3 * SS), border_radius=SS)

    # Wordmark on the bottom edge, letter-spaced, with the little rules.
    font = pygame.font.Font(None, 13 * SS)
    letters = [font.render(ch, True, k["logo"]) for ch in "GAMESIR"]
    width = sum(l.get_width() for l in letters) + 3 * SS * (len(letters) - 1)
    x, y = P(320, 325)
    x -= width // 2
    pygame.draw.line(big, k["logo"], (x - 20 * SS, y), (x - 6 * SS, y), SS)
    pygame.draw.line(big, k["logo"], (x + width + 6 * SS, y), (x + width + 20 * SS, y), SS)
    for l in letters:
        big.blit(l, (x, y - l.get_height() // 2))
        x += l.get_width() + 3 * SS

    return pygame.transform.smoothscale(big, size)


def _circle(surf, color, c, r):
    gfxdraw.filled_circle(surf, int(c[0]), int(c[1]), int(r), color)
    gfxdraw.aacircle(surf, int(c[0]), int(c[1]), int(r), color)


def _ring(surf, color, c, r, width):
    for i in range(width):
        gfxdraw.aacircle(surf, int(c[0]), int(c[1]), int(r + i), color)


def _overlay(surf, kind, geo, color, alpha):
    """Tint a control's shape (dim it, or light it up)."""
    layer = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    if kind in ("stick", "face", "home"):
        cx, cy, r = geo
        pygame.draw.circle(layer, (*color, alpha), (cx, cy), r + (2 if kind == "home" else 0))
    else:
        pygame.draw.rect(layer, (*color, alpha), geo, border_radius=_radius(kind))
    surf.blit(layer, (0, 0))


def _outline_shape(surf, kind, geo, color):
    if kind in ("stick", "face", "home"):
        cx, cy, r = geo
        _ring(surf, color, (cx, cy), r + 2, 3)
    else:
        pygame.draw.rect(surf, color, pygame.Rect(geo).inflate(4, 4), 3,
                         border_radius=_radius(kind) + 2)


def _radius(kind):
    return {"trigger": 12, "bumper": 12, "small": 6, "tag": 9, "dpad": 3}.get(kind, 4)


class PadArt:
    """Draws the pad onto a canvas. state(name) -> (mapped, live, match, nums)."""

    def __init__(self, size, colors):
        self.size = size
        self.ui = colors  # dict with BG, TEXT, DIM, IDLE, MAPPED, LIVE, MATCH, OUTLINE
        self.skin = "white"
        self.shells = {}
        self.font = pygame.font.Font(None, 20)
        self.small = pygame.font.Font(None, 16)
        self.letter = pygame.font.Font(None, 22)

    def next_skin(self):
        names = list(SKINS)
        self.skin = names[(names.index(self.skin) + 1) % len(names)]

    def _label(self, surf, text, font, color, center):
        img = font.render(text, True, color)
        surf.blit(img, img.get_rect(center=center))

    def _badge(self, surf, text, center, color):
        img = self.small.render(text, True, color)
        box = img.get_rect(center=center).inflate(8, 4)
        pygame.draw.rect(surf, self.ui["BG"], box, border_radius=7)
        surf.blit(img, img.get_rect(center=center))

    def draw(self, surf, state, hat=(0, 0)):
        k = SKINS[self.skin]
        if self.skin not in self.shells:
            self.shells[self.skin] = render_shell(self.skin, self.size)

        # Triggers sit behind the bumpers, which sit on the shell's shoulders.
        for name in ("LT", "RT"):
            self._control(surf, name, state, k, hat)
        surf.blit(self.shells[self.skin], (0, 0))
        hub = pygame.Rect(DPAD_C[0] - DPAD_S // 2, DPAD_C[1] - DPAD_S // 2, DPAD_S, DPAD_S)
        pygame.draw.rect(surf, k["dpad"], hub)
        for name in LAYOUT:
            if name not in ("LT", "RT"):
                self._control(surf, name, state, k, hat)

    def _control(self, surf, name, state, k, hat):
        ui = self.ui
        kind, geo, badge = LAYOUT[name]
        mapped, live, match, nums = state(name)
        live = live or (kind == "dpad" and HAT_ARMS.get(tuple(hat)) == name)
        rect = None if kind in ("stick", "face", "home") else pygame.Rect(geo)

        if kind == "trigger":
            pygame.draw.rect(surf, k["trigger"], rect, border_radius=12)
            pygame.draw.rect(surf, k["edge"], rect, 1, border_radius=12)
            self._label(surf, f"{name} {nums}".strip(), self.font, k["trigger_text"],
                        (rect.centerx, rect.y + 15))
        elif kind == "bumper":
            pygame.draw.rect(surf, k["bumper"], rect, border_radius=12)
            pygame.draw.rect(surf, k["edge"], rect, 1, border_radius=12)
            self._label(surf, f"{name} {nums}".strip(), self.font, k["bumper_text"], rect.center)
        elif kind == "small":
            pygame.draw.rect(surf, k["small"], rect, border_radius=6)
            pygame.draw.rect(surf, k["edge"], rect, 1, border_radius=6)
        elif kind == "home":
            cx, cy, r = geo
            _circle(surf, k["led"], (cx, cy), r + 2)
            _circle(surf, k["home"], (cx, cy), r - 2)
            self._label(surf, "G", self.letter, k["letter"], (cx, cy + 1))
        elif kind == "stick":
            cx, cy, r = geo
            _circle(surf, k["rim"], (cx, cy), r)
            _circle(surf, k["ring"], (cx, cy), r - 4)
            _circle(surf, k["well"], (cx, cy), r - 9)
            _circle(surf, k["cap"], (cx, cy), r - 13)
            _ring(surf, k["knurl"], (cx, cy), r - 17, 1)
            self._label(surf, name, self.font, k["letter"], (cx, cy - (6 if nums else 0)))
            if nums:
                self._label(surf, nums, self.small, k["letter"], (cx, cy + 9))
        elif kind == "face":
            cx, cy, r = geo
            _circle(surf, k["face"], (cx, cy), r)
            _ring(surf, k["knurl"], (cx, cy), r, 1)
            self._label(surf, name, self.letter, k["letter"], (cx, cy + 1))
        elif kind == "dpad":
            pygame.draw.rect(surf, k["dpad"], rect, border_radius=3)
            pygame.draw.line(surf, k["dpad_hi"], (rect.x + 3, rect.y + 2), (rect.right - 4, rect.y + 2), 2)
        elif kind == "tag":
            fill = ui["MAPPED"] if mapped else ui["IDLE"]
            pygame.draw.rect(surf, fill, rect, border_radius=9)
            self._label(surf, f"{name} {nums}".strip(), self.small,
                        ui["TEXT"] if mapped else ui["DIM"], rect.center)

        if live:
            _overlay(surf, kind, geo, ui["LIVE"], 150)
        elif not mapped and kind != "tag":
            _overlay(surf, kind, geo, ui["BG"], 120)
        if live:
            _outline_shape(surf, kind, geo, ui["LIVE"])
        if match:
            _outline_shape(surf, kind, geo, ui["MATCH"])
        if badge:
            text = nums if kind == "face" else f"{name} {nums}".strip()
            if text:
                self._badge(surf, text, badge, ui["TEXT"] if mapped else ui["DIM"])
