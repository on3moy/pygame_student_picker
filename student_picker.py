# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["pygame>=2.6.1"]
# ///
"""
Pixel-graphic random student picker.

Loads student names from students.txt, then plays a ~2-second slot-machine
animation and lands on a random student when you press the controller A-button
(button 0) or the Spacebar.

- No repeats: a picked student leaves the pool until everyone has been picked,
  or until you reset.
- Works keyboard-only if no controller is connected.

Controls:
    Space / Controller A (button 0)  -> pick a student (or continue to next)
    R     / Controller B (button 1)  -> reset the pool
    F     / Controller X (button 2)  -> choose a different students .txt file
    Esc / window close               -> quit

Run:
    python student_picker.py
"""

import math
import os
import random
import sys

import pygame

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STUDENTS_PATH = os.path.join(BASE_DIR, "students.txt")

# --- Display geometry ---
LOW_W, LOW_H = 320, 240          # low-res surface we draw to (pixel-art look)
SCALE = 3                        # upscale factor -> window is 960x720
WIN_W, WIN_H = LOW_W * SCALE, LOW_H * SCALE

# --- Stranger Things palette (R, G, B) ---
BG_TOP = (8, 0, 2)               # near-black, faint red
BG_BOTTOM = (28, 2, 6)           # very dark blood red
PANEL = (10, 1, 3)               # almost-black panel
PANEL_BORDER = (228, 16, 22)     # neon ST red
ACCENT = (255, 28, 32)           # bright logo red
WINNER = (255, 60, 64)           # glowing red winner
TEXT = (236, 224, 220)           # warm off-white
DIM = (150, 70, 74)              # dim red-grey
RAY_RED = (220, 14, 20)          # red light-ray color

# --- Timing ---
SPIN_MS = 2000                   # total spin duration
SPIN_MIN_INTERVAL = 40           # fastest name-swap interval (ms) at the start
SPIN_MAX_INTERVAL = 240          # slowest name-swap interval (ms) at the end

# --- Controller button mapping (matches config.json convention) ---
BTN_PICK = 0                     # A
BTN_RESET = 1                    # B
BTN_SELECT_FILE = 2              # X

# --- States ---
IDLE = "idle"
SPINNING = "spinning"
RESULT = "result"


def load_students(path=STUDENTS_PATH):
    """Return a list of student names from `path` (blank lines stripped)."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        names = [line.strip() for line in f if line.strip()]
    seen = set()
    unique = []
    for n in names:
        if n.lower() != "name" and n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


def choose_students_file():
    """Open a native file dialog for picking a .txt of student names.

    Returns the chosen path, or None if cancelled/unavailable. Uses tkinter
    only for the dialog window, then tears it down immediately so it doesn't
    interfere with the pygame window.
    """
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
        initialdir=BASE_DIR,
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    root.destroy()
    return path or None


def init_joystick():
    """Init the first joystick if present. Returns the Joystick or None."""
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        return None
    js = pygame.joystick.Joystick(0)
    js.init()
    return js


def make_fonts():
    """Pick a bold serif evoking the ITC Benguiat 'Stranger Things' logo.

    Returns (title_font, big_font, small_font). ITC Benguiat isn't normally
    installed, so we fall back through close serifs (Benguiat -> Georgia ->
    Garamond -> Times) before plain serif.
    """
    candidates = ("ITC Benguiat", "Benguiat", "Georgia", "Bookman Old Style",
                  "Garamond", "Times New Roman", "serif")
    chosen = None
    for name in candidates:
        if pygame.font.match_font(name):
            chosen = name
            break
    if chosen is None:
        return (pygame.font.Font(None, 34),
                pygame.font.Font(None, 30),
                pygame.font.Font(None, 16))
    return (
        pygame.font.SysFont(chosen, 30, bold=True),   # title (logo)
        pygame.font.SysFont(chosen, 26, bold=True),   # big (winner/spin)
        pygame.font.SysFont(chosen, 13, bold=True),   # small (prompts)
    )


def render_glow(font, text, core, glow, radius=2):
    """Render text with a neon red bloom (the Stranger Things logo look).

    Returns a SRCALPHA surface a bit larger than the text so the glow isn't
    clipped. `core` is the bright center color, `glow` the halo color.
    """
    base = font.render(text, True, core)
    pad = radius * 3 + 2
    surf = pygame.Surface((base.get_width() + pad * 2,
                           base.get_height() + pad * 2), pygame.SRCALPHA)
    halo = font.render(text, True, glow)
    halo.set_alpha(65)
    # Lay the halo down at several offsets to fake a blur/bloom.
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx or dy:
                surf.blit(halo, (pad + dx, pad + dy))
    surf.blit(base, (pad, pad))
    return surf


def ease_out(t):
    """t in [0,1] -> eased value in [0,1] that decelerates toward the end."""
    return 1 - (1 - t) * (1 - t)


def vgradient(surface, top, bottom):
    """Fill surface with a simple vertical gradient."""
    h = surface.get_height()
    for y in range(h):
        f = y / max(1, h - 1)
        color = (
            int(top[0] + (bottom[0] - top[0]) * f),
            int(top[1] + (bottom[1] - top[1]) * f),
            int(top[2] + (bottom[2] - top[2]) * f),
        )
        pygame.draw.line(surface, color, (0, y), (surface.get_width(), y))


class Ray(pygame.sprite.Sprite):
    """A drifting beam of red light that sweeps across the background.

    Each ray is a tall translucent vertical band, drawn once into its own
    surface and moved horizontally with a wrap-around. Alpha pulses over time
    so the rays breathe like the show's neon glow.
    """

    def __init__(self):
        super().__init__()
        self.w = random.randint(8, 26)
        self.image = pygame.Surface((self.w, LOW_H), pygame.SRCALPHA)
        # Soft-edged band: fade alpha toward both vertical edges.
        for x in range(self.w):
            edge = 1 - abs((x / (self.w - 1)) * 2 - 1)   # 0..1..0 across width
            a = int(70 * edge)
            pygame.draw.line(self.image, (*RAY_RED, a), (x, 0), (x, LOW_H))
        self.x = random.uniform(0, LOW_W)
        self.speed = random.uniform(6, 22) * random.choice((-1, 1))
        self.phase = random.uniform(0, 6.28)
        self.base_alpha = random.randint(40, 95)

    def update(self, dt, t):
        self.x = (self.x + self.speed * dt) % (LOW_W + self.w) - self.w
        pulse = 0.6 + 0.4 * math.sin(t * 2 + self.phase)
        self.image.set_alpha(int(self.base_alpha * pulse))
        self.rect = self.image.get_rect(topleft=(int(self.x), 0))


class Spore(pygame.sprite.Sprite):
    """A floating Upside-Down spore: a tiny red mote drifting upward, twinkling."""

    def __init__(self):
        super().__init__()
        self.reset(start_anywhere=True)

    def reset(self, start_anywhere=False):
        self.r = random.choice((1, 1, 2))
        self.fx = random.uniform(0, LOW_W)
        self.fy = random.uniform(0, LOW_H) if start_anywhere else LOW_H + 2
        self.vy = -random.uniform(4, 14)
        self.drift = random.uniform(-6, 6)
        self.phase = random.uniform(0, 6.28)

    def update(self, dt, t):
        self.fy += self.vy * dt
        self.fx = (self.fx + self.drift * dt) % LOW_W
        if self.fy < -2:
            self.reset()

    def draw(self, surface, t):
        twinkle = 0.5 + 0.5 * math.sin(t * 4 + self.phase)
        a = int(60 + 160 * twinkle)
        col = (255, int(40 + 60 * twinkle), int(40 + 60 * twinkle), a)
        s = pygame.Surface((self.r * 2 + 1, self.r * 2 + 1), pygame.SRCALPHA)
        pygame.draw.circle(s, col, (self.r, self.r), self.r)
        surface.blit(s, (int(self.fx), int(self.fy)))


def draw_centered(surface, font, text, color, cy, cx=None):
    """Blit text centered horizontally (and on cy vertically)."""
    img = font.render(text, True, color)
    rect = img.get_rect()
    rect.centery = cy
    rect.centerx = LOW_W // 2 if cx is None else cx
    surface.blit(img, rect)
    return rect


def fit_text(font, text, max_width):
    """Truncate text with an ellipsis so it fits within max_width pixels."""
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "...")[0] > max_width:
        text = text[:-1]
    return text + "..."


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Stranger Things — Student Picker")
    clock = pygame.time.Clock()
    canvas = pygame.Surface((LOW_W, LOW_H))
    title_font, big_font, small_font = make_fonts()

    # Pre-render the glowing logo-style title once.
    title_img = render_glow(title_font, "STUDENT PICKER", ACCENT, RAY_RED, radius=1)

    # Animated background sprites (red light rays + drifting spores).
    rays = pygame.sprite.Group(*[Ray() for _ in range(6)])
    spores = [Spore() for _ in range(40)]

    js = init_joystick()
    controller_name = js.get_name() if js else None

    all_students = load_students()
    remaining = list(all_students)
    random.shuffle(remaining)
    students_source = "students.txt"

    state = IDLE
    display_name = ""          # name currently shown in the panel
    winner = ""
    spin_start = 0
    next_swap = 0
    panel = pygame.Rect(30, 86, LOW_W - 60, 68)

    def start_spin():
        nonlocal state, winner, spin_start, next_swap, display_name
        if not remaining:
            return
        winner = random.choice(remaining)
        spin_start = pygame.time.get_ticks()
        next_swap = spin_start
        display_name = random.choice(remaining)
        state = SPINNING

    def do_reset():
        nonlocal remaining, state, display_name, winner
        remaining = list(all_students)
        random.shuffle(remaining)
        state = IDLE
        display_name = ""
        winner = ""

    def on_pick_button():
        # In IDLE or RESULT a pick advances; if pool empty it does nothing.
        if state in (IDLE, RESULT) and remaining:
            start_spin()

    def on_select_file():
        nonlocal all_students, students_source
        path = choose_students_file()
        if not path:
            return
        loaded = load_students(path)
        if not loaded:
            return
        all_students = loaded
        students_source = os.path.basename(path)
        do_reset()

    running = True
    while running:
        now = pygame.time.get_ticks()

        # --- Events ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    on_pick_button()
                elif event.key == pygame.K_r:
                    do_reset()
                elif event.key == pygame.K_f:
                    on_select_file()
            elif event.type == pygame.JOYBUTTONDOWN:
                if event.button == BTN_PICK:
                    on_pick_button()
                elif event.button == BTN_RESET:
                    do_reset()
                elif event.button == BTN_SELECT_FILE:
                    on_select_file()
            elif event.type == pygame.JOYDEVICEADDED:
                js = init_joystick()
                controller_name = js.get_name() if js else None

        # --- Update spin animation ---
        if state == SPINNING:
            elapsed = now - spin_start
            if elapsed >= SPIN_MS:
                display_name = winner
                state = RESULT
                if winner in remaining:
                    remaining.remove(winner)
            elif now >= next_swap:
                # ease-out: swap fast at first, slowing toward the end
                t = ease_out(elapsed / SPIN_MS)
                interval = SPIN_MIN_INTERVAL + (SPIN_MAX_INTERVAL - SPIN_MIN_INTERVAL) * t
                pool = [n for n in remaining if n != display_name] or remaining
                display_name = random.choice(pool)
                next_swap = now + int(interval)

        # --- Animate background ---
        t = now / 1000.0
        dt = clock.get_time() / 1000.0
        rays.update(dt, t)
        for sp in spores:
            sp.update(dt, t)

        # --- Draw to low-res canvas ---
        vgradient(canvas, BG_TOP, BG_BOTTOM)
        rays.draw(canvas)                      # red light rays behind everything
        for sp in spores:
            sp.draw(canvas, t)                 # floating spores

        # Glowing Stranger Things-style title.
        canvas.blit(title_img, title_img.get_rect(center=(LOW_W // 2, 26)))

        if not all_students:
            draw_centered(canvas, small_font, "students.txt not found or empty.",
                          TEXT, LOW_H // 2 - 8)
            draw_centered(canvas, small_font, "Press F to select a students file.",
                          DIM, LOW_H // 2 + 10)
        else:
            # Display panel
            pygame.draw.rect(canvas, PANEL, panel, border_radius=4)
            # Border blinks on RESULT for a little celebration.
            border_col = PANEL_BORDER
            if state == RESULT and (now // 200) % 2 == 0:
                border_col = WINNER
            pygame.draw.rect(canvas, border_col, panel, width=2, border_radius=4)

            if state == IDLE and not display_name:
                draw_centered(canvas, small_font, "Press SPACE / A to pick",
                              DIM, panel.centery)
            else:
                color = WINNER if state == RESULT else TEXT
                shown = fit_text(big_font, display_name, panel.width - 20)
                draw_centered(canvas, big_font, shown, color, panel.centery)

            # Footer / prompts
            if not remaining and state != SPINNING:
                draw_centered(canvas, small_font,
                              "Everyone picked!  Press R to reset.", ACCENT, 182)
            elif state == RESULT:
                draw_centered(canvas, small_font,
                              "Press SPACE / A for next", TEXT, 182)
            elif state == IDLE:
                draw_centered(canvas, small_font,
                              "Press SPACE / A for next", DIM, 182)

            draw_centered(canvas, small_font,
                          f"{len(remaining)} of {len(all_students)} left", DIM, 206)

        # Controller status line + loaded file (press F to change)
        status = controller_name if controller_name else "Keyboard only (no controller)"
        draw_centered(canvas, small_font, fit_text(small_font, status, LOW_W - 20),
                      DIM, 218)
        draw_centered(canvas, small_font,
                      fit_text(small_font, f"{students_source}  (F to change / X to select file)", LOW_W - 20),
                      DIM, 232)

        # --- Upscale to window ---
        pygame.transform.scale(canvas, (WIN_W, WIN_H), screen)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
