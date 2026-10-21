"""
The window map_controller.py opens by default: a drawing of a pad, the list
of standard names, and a prompt. Press something on the pad, type its name,
Enter. Ctrl+S names the template and saves it; Ctrl+O loads the next saved
one; Ctrl+N starts a blank one; Ctrl+T swaps the pad between the white and
black Cyclone 2 (the drawing lives in pad_art.py). Holding a mapped input lights it up, so a
loaded template can be checked at a glance.

Everything is drawn on a fixed 900x560 canvas and scaled to the window.
"""

import pygame

import controllers
from controllers import OS_KEY, STANDARD_NAMES
from controllers.capture import AXIS_TRIGGER, Burst, assign, held, rest_values, what_was
from controllers.pad_art import LAYOUT, PadArt

W, H = 900, 560

BG = (24, 26, 32)
OUTLINE = (90, 96, 110)
IDLE = (56, 60, 72)
DIM = (120, 126, 140)
TEXT = (230, 235, 245)
MAPPED = (40, 92, 144)
LIVE = (90, 200, 120)
MATCH = (240, 200, 80)
BAR = (34, 37, 45)

MESSAGE_MS = 3500


class Mapper:
    def __init__(self, pad, device, key, save, use, in_use):
        self.pad, self.device = pad, device
        self.save_cb, self.use_cb, self.in_use = save, use, in_use
        self.canvas = pygame.Surface((W, H))
        self.font = pygame.font.Font(None, 22)
        self.small = pygame.font.Font(None, 17)
        self.big = pygame.font.Font(None, 32)
        self.art = PadArt((W, H), dict(BG=BG, TEXT=TEXT, DIM=DIM, IDLE=IDLE, MAPPED=MAPPED,
                                       LIVE=LIVE, MATCH=MATCH, OUTLINE=OUTLINE))
        self.rest = rest_values(pad)
        self.burst = Burst(self.rest)
        self.wait_release = False
        self.mode = "map"       # map | custom | name | use | quit
        self.text = ""          # name being typed for the pending input
        self.name_text = ""     # template name while saving
        self.custom = None      # non-standard name awaiting confirmation
        self.pending = None     # (buttons, axes) pressed, not yet named
        self.armed = None       # Ctrl+O / Ctrl+N pressed once over unsaved changes
        self.swallow = False    # drop the text event of a Y/N answer
        self.message, self.message_until = "", 0
        self.running = True
        self.load(key)

    # --- template state ---------------------------------------------------

    def load(self, key):
        self.key, self.exists = key, False
        profile = controllers.Profile(key, {})
        if key:
            try:
                profile = controllers.load_profile(key)
                self.exists = True
            except (OSError, ValueError):
                pass
        self.title = profile.title if self.exists else None
        self.aliases = profile.aliases
        self.buttons, self.axes = dict(profile.buttons), dict(profile.axes)
        self.saved = (dict(self.buttons), dict(self.axes))
        self.pending, self.text = None, ""

    @property
    def dirty(self):
        return (self.buttons, self.axes) != self.saved

    def key_for(self, text):
        """Keep the current file when the name is unchanged, else a new slug."""
        text = text.strip()
        if self.exists and text == self.title:
            return self.key
        return controllers.slugify(text)

    def numbers(self, name):
        parts = [str(self.buttons[name])] if name in self.buttons else []
        parts += [f"a{self.axes[name]}"] if name in self.axes else []
        return "/".join(parts)

    def custom_names(self):
        return sorted(n for n in {*self.buttons, *self.axes} if n not in STANDARD_NAMES)

    def live(self, name):
        """True while the input mapped to name is held."""
        pad = self.pad
        b, a = self.buttons.get(name), self.axes.get(name)
        if b is not None and b < pad.get_numbuttons() and pad.get_button(b):
            return True
        return a is not None and a < len(self.rest) and \
            abs(pad.get_axis(a) - self.rest[a]) > AXIS_TRIGGER / 2

    def hat_held(self):
        return any(self.pad.get_hat(i) != (0, 0) for i in range(self.pad.get_numhats()))

    def matches(self):
        typed = self.text.strip().upper()
        if not typed:
            return set()
        names = {*STANDARD_NAMES, *LAYOUT, *self.custom_names()}
        out = {n for n in names if n.startswith(typed)}
        exact = controllers.canonical(typed, self.aliases)
        return out | {exact} if exact else out

    def say(self, text):
        self.message, self.message_until = text, pygame.time.get_ticks() + MESSAGE_MS

    # --- actions ----------------------------------------------------------

    def on_press(self, buttons, axes, hat):
        if not buttons and not axes:
            if hat:
                self.say("D-pad is a hat here - nothing to name")
            return
        self.pending = (buttons, axes[:1])  # a diagonal push counts as its main axis
        if self.mode == "custom":
            self.mode = "map"

    def assign_name(self, name):
        pressed, moved = self.pending
        for b in pressed:
            assign(self.buttons, name, b)
        for a in moved:
            assign(self.axes, name, a)
        self.say(f"{name} = {what_was(pressed, moved, False)}")
        self.pending, self.text, self.mode = None, "", "map"

    def submit_name(self):
        if not self.pending:
            self.say("Press a pad input first")
            return
        if not self.text.strip():
            self.say("Type a name")
            return
        name = controllers.canonical(self.text, self.aliases)
        if name:
            self.assign_name(name)
        else:
            self.custom, self.mode = self.text.strip().upper(), "custom"

    def start_save(self):
        if not self.buttons and not self.axes:
            self.say("Nothing mapped yet")
            return
        self.name_text = self.title if self.exists else (self.key or self.device["name"])
        self.mode = "name"

    def finish_save(self):
        name = self.name_text.strip()
        if not name:
            return
        key = self.key_for(name)
        try:
            self.save_cb(key, self.buttons, self.axes, title=name,
                         device={"name": self.device["name"]})
        except (OSError, ValueError) as exc:
            self.say(f"Not saved: {exc}")
            self.mode = "map"
            return
        self.load(key)
        if self.in_use() != key:
            self.mode = "use"
        else:
            self.mode = "map"
            self.say(f"Saved {key}.json")

    def guarded(self, action, fn):
        """Run fn, but ask for a second press first if it would drop changes."""
        if self.dirty and self.armed != action:
            self.armed = action
            self.say("Unsaved changes - press again to discard")
            return
        self.armed = None
        fn()

    def load_next(self):
        keys = controllers.list_profiles()
        if not keys:
            self.say("No saved templates")
            return
        i = keys.index(self.key) + 1 if self.key in keys else 0
        self.load(keys[i % len(keys)])
        self.say(f"Loaded {self.title}")

    def new_template(self):
        self.load(None)
        self.say("New template")

    def quit(self):
        if self.dirty:
            self.mode = "quit"
        else:
            self.running = False

    # --- input ------------------------------------------------------------

    def on_key(self, ev):
        ctrl = ev.mod & pygame.KMOD_CTRL
        enter = ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
        if ev.key not in (pygame.K_o, pygame.K_n):
            self.armed = None
        if self.mode in ("use", "quit"):
            self.swallow = ev.key in (pygame.K_y, pygame.K_n)
            if ev.key == pygame.K_y:
                if self.mode == "use":
                    done = self.use_cb(self.key)
                    self.say(f"Using {self.key} in {', '.join(done) or 'no configs'}")
                else:
                    self.running = False
                self.mode = "map"
            elif ev.key in (pygame.K_n, pygame.K_ESCAPE):
                if self.mode == "use":
                    self.say(f"Saved {self.key}.json")
                self.mode = "map"
            return
        if self.mode == "custom":
            if enter:
                self.assign_name(self.custom)
            elif ev.key == pygame.K_ESCAPE:
                self.mode = "map"
            return
        if self.mode == "name":
            if enter:
                self.finish_save()
            elif ev.key == pygame.K_ESCAPE:
                self.mode = "map"
            elif ev.key == pygame.K_BACKSPACE:
                self.name_text = self.name_text[:-1]
            return
        # map mode
        if ctrl and ev.key == pygame.K_s:
            self.start_save()
        elif ctrl and ev.key == pygame.K_o:
            self.guarded("load", self.load_next)
        elif ctrl and ev.key == pygame.K_n:
            self.guarded("new", self.new_template)
        elif ctrl and ev.key == pygame.K_t:
            self.art.next_skin()
        elif enter:
            self.submit_name()
        elif ev.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        elif ev.key == pygame.K_ESCAPE:
            if self.pending or self.text:
                self.pending, self.text = None, ""
            else:
                self.quit()

    def on_text(self, ev):
        if self.swallow or pygame.key.get_mods() & pygame.KMOD_CTRL:
            self.swallow = False
            return
        if self.mode == "map" and len(self.text) < 24:
            self.text += ev.text
        elif self.mode == "name" and len(self.name_text) < 40:
            self.name_text += ev.text

    def ours(self, ev):
        return getattr(ev, "instance_id", None) in (None, self.pad.get_instance_id())

    def pump(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.quit()
            elif ev.type == pygame.KEYDOWN:
                self.on_key(ev)
            elif ev.type == pygame.TEXTINPUT:
                self.on_text(ev)
            elif ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION, pygame.JOYHATMOTION) \
                    and self.ours(ev) and not self.wait_release and self.mode in ("map", "custom"):
                self.burst.feed(ev)
        got = self.burst.ready()
        if got:
            self.wait_release = True
            self.on_press(*got)
        elif self.wait_release and not held(self.pad, self.rest) and not self.hat_held():
            self.wait_release = False

    # --- drawing ----------------------------------------------------------

    def label(self, text, font, color, center):
        img = font.render(text, True, color)
        self.canvas.blit(img, img.get_rect(center=center))

    def draw_pad(self, matches):
        def state(name):
            mapped = name in self.buttons or name in self.axes
            return mapped, mapped and self.live(name), name in matches, self.numbers(name)
        hat = self.pad.get_hat(0) if self.pad.get_numhats() else (0, 0)
        self.art.draw(self.canvas, state, hat)

    def draw_list(self, matches):
        c, x, y = self.canvas, 630, 66
        self.canvas.blit(self.font.render("Inputs", True, DIM), (x, y))
        y += 26
        rows = [(n, True) for n in STANDARD_NAMES]
        customs = self.custom_names()
        if customs:
            rows.append((None, False))
            rows += [(n, False) for n in customs]
        for name, _standard in rows:
            if name is None:
                y += 8
                continue
            mapped = name in self.buttons or name in self.axes
            if mapped and self.live(name):
                pygame.draw.rect(c, LIVE, (x - 6, y - 2, 262, 18), border_radius=4)
            color = MATCH if name in matches else TEXT if mapped else DIM
            if mapped:
                pygame.draw.circle(c, MAPPED, (x + 5, y + 7), 5)
            else:
                pygame.draw.circle(c, OUTLINE, (x + 5, y + 7), 5, 1)
            c.blit(self.font.render(name, True, color), (x + 18, y))
            nums = self.numbers(name)
            if nums:
                img = self.font.render(nums, True, color)
                c.blit(img, (x + 250 - img.get_width(), y))
            y += 19

    def describe_pending(self):
        pressed, moved = self.pending
        parts = []
        for kind, table, nums in (("button", self.buttons, pressed), ("axis", self.axes, moved)):
            for i in nums:
                now = [n for n, j in table.items() if j == i]
                parts.append(f"{kind} {i}" + (f" ({'/'.join(now)})" if now else ""))
        return " + ".join(parts)

    def draw_bar(self):
        c = self.canvas
        pygame.draw.rect(c, BAR, (0, 496, W, 64))
        cursor = "_" if pygame.time.get_ticks() // 500 % 2 else " "
        if self.mode == "custom":
            prompt, hint = f"{self.custom} isn't standard. Keep it?", "Enter keep · Esc edit"
        elif self.mode == "name":
            key = self.key_for(self.name_text) if self.name_text.strip() else "?"
            prompt = f"Template name: {self.name_text}{cursor}"
            hint = f"saves controllers/{key}.json · Enter save · Esc cancel"
        elif self.mode == "use":
            prompt, hint = f"Saved. Use {self.key} in {OS_KEY} configs?", "Y / N"
        elif self.mode == "quit":
            prompt, hint = "Unsaved changes. Quit anyway?", "Y / N"
        else:
            if self.pending:
                prompt = f"{self.describe_pending()}  ->  name: {self.text}{cursor}"
            elif self.text:
                prompt = f"Press a pad input for: {self.text}{cursor}"
            else:
                prompt = "Press a pad input, then type its name"
            hint = "Enter assign · Esc clear/quit · Ctrl+S save · Ctrl+O load · Ctrl+N new · Ctrl+T look"
        c.blit(self.big.render(prompt, True, TEXT), (20, 506))
        c.blit(self.small.render(hint, True, DIM), (20, 538))

    def draw(self):
        c = self.canvas
        c.fill(BG)
        title = self.title or "New template"
        c.blit(self.big.render(title + (" *" if self.dirty else ""), True, TEXT), (20, 16))
        sub = f"controllers/{self.key}.json · {OS_KEY}" if self.exists else "not saved yet"
        c.blit(self.small.render(sub, True, DIM), (20, 46))
        dev = self.small.render(self.device["name"], True, DIM)
        c.blit(dev, (W - 20 - dev.get_width(), 22))
        matches = self.matches() if self.mode == "map" else set()
        self.draw_pad(matches)
        self.draw_list(matches)
        if self.message and pygame.time.get_ticks() < self.message_until:
            c.blit(self.font.render(self.message, True, MATCH), (20, 462))
        self.draw_bar()

        screen = pygame.display.get_surface()
        sw, sh = screen.get_size()
        scale = min(sw / W, sh / H)
        screen.fill(BG)
        if abs(scale - 1) < 0.01:
            screen.blit(c, ((sw - W) // 2, (sh - H) // 2))
        else:
            size = (max(1, int(W * scale)), max(1, int(H * scale)))
            img = pygame.transform.smoothscale(c, size)
            screen.blit(img, ((sw - size[0]) // 2, (sh - size[1]) // 2))
        pygame.display.flip()

    def loop(self):
        clock = pygame.time.Clock()
        while self.running:
            self.pump()
            self.draw()
            clock.tick(60)


def run(pad, device, key, save, use, in_use):
    """Open the mapper window on template `key` (None for a new one).
    save(key, buttons, axes, title=, device=) writes a template, use(key)
    points this OS's configs at it and returns the files it changed, and
    in_use() is the key the configs use now."""
    pygame.display.set_mode((W, H), pygame.RESIZABLE)
    pygame.display.set_caption("Controller mapper")
    pygame.key.start_text_input()
    try:
        Mapper(pad, device, key, save, use, in_use).loop()
    finally:
        pygame.display.quit()
