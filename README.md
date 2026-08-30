# Pygame Student Picker

A small always-on-top random student picker for lecturing. It floats over your
slides showing one name at a time, and a single controller button calls the next
student. No repeats until everyone has been picked, then it starts a fresh round
on its own.

This project uses [**uv**](https://docs.astral.sh/uv/) for environment and dependency
management.

## Setup

```sh
uv sync
```

## Run

Double-click **`run_picker.cmd`**, or make a desktop shortcut to it. That is the
one to use while teaching — see [no console window](#no-console-window) below.

From a terminal:

```sh
uv run mini_picker.py
```

Because `mini_picker.py` has a PEP 723 inline-dependency header, you can also run it
without `uv sync` from anywhere:

```sh
uv run --script mini_picker.py
```

### No console window

`python.exe` is a console program, so launching the picker from a terminal — or
from a shortcut that points at `uv` or `python` — leaves a black console window
sitting behind it for the whole lecture.

`run_picker.cmd` starts the picker with `pythonw.exe` instead: the same
interpreter with no console attached. The picker window appears on its own,
with nothing else on screen. Run `uv sync` once first so `.venv` exists.

The picker itself never opens a terminal, a dialog, or any other window on its
own. The only window it can create besides its own is the file-open dialog, and
only when you press `F`.

The controller presentation remote:

```sh
uv run controller_remote.py
uv run controller_remote.py --diagnose   # print button/axis numbers
```

## The picker

`mini_picker.py` is a small borderless window that floats over your slides and
shows nothing but the name.

```sh
uv run mini_picker.py                        # uses mini_config.json
uv run mini_picker.py rosters/is640.txt      # one-off roster for this run
uv run mini_picker.py --theme dracula        # one-off theme for this run
```

The roster can be given as a bare path or with `--students` / `-s`; the theme
takes `--theme` or `-t`. Arguments passed on the command line apply to that run
only; they are not written back to `mini_config.json`.

### Controls

| Input | Action |
| --- | --- |
| `Space` / pad **RB** (10) | **NEXT** — call a student |
| `T` / pad **Y** (3) | Cycle to the next theme in `themes/` |
| `R` / pad **X** (2) | Start a fresh round early (rarely needed — see below) |
| `L` | Map your controller buttons (see below) |
| `H` | Show the current button mapping |
| `F` | Load a different roster `.txt` |
| `O` | Toggle always-on-top |
| Left-drag | Move the window (its position is remembered) |
| Drag the corner grip | Resize the window |
| `+` / `-` | Grow / shrink the window |
| `0` | Reset to the theme's design size |
| `Ctrl` + mouse wheel | Grow / shrink the window |
| `Esc` | Quit |

## One button: NEXT

In normal use there is only one thing to press. **NEXT** calls a student, and
that is the whole loop — you never have to reset anything.

Nobody is called twice until everyone has had a turn. When the last student in
a round is called, the picker says

```
That's everyone - starting a fresh round
```

refills the pool on the spot, and carries on. The next press starts the new
round immediately, and it will not call the same student twice across that
boundary. `R` (or pad **X**) still starts a fresh round early if you want one
mid-way, but you never need it.

## Where the controller buttons are mapped

Three actions can be driven from the pad — **pick a name**, **change theme**,
and **reset the pool**. There are two places to set them.

### 1. In the window (easiest)

Press `L`. The picker walks you through the three actions one at a time,
showing a prompt along the bottom:

```
Press the button to PICK a name   (S skip, Esc cancel)
```

Press the pad button you want and it moves on to the next action. `S` skips an
action and leaves its current button alone, `Esc` cancels the whole thing. When
you reach the end it saves to `mini_config.json` and shows the result:

```
Saved.   Pick: RB (10)   Change: Y (3)   Reset: X (2)
```

Press `H` any time to see that summary again. A button already used by an
action you set earlier in the same run is refused (`Y (3) is already Pick — try
another`) rather than silently taken away from it.

### 2. In `mini_config.json` (by hand)

```json
"controller": {
  "pick_button": 10,
  "theme_button": 3,
  "reset_button": 2,
  "joystick_index": 0
}
```

`null` leaves an action unmapped. `joystick_index` picks which pad to listen to
if you have more than one plugged in. The standard SDL button numbers are:

| # | Button | # | Button | # | Button |
| --- | --- | --- | --- | --- | --- |
| 0 | A | 5 | GUIDE | 10 | RB |
| 1 | B | 6 | START | 11 | D-pad up |
| 2 | X | 7 | Left stick | 12 | D-pad down |
| 3 | Y | 8 | Right stick | 13 | D-pad left |
| 4 | BACK | 9 | LB | 14 | D-pad right |

Numbers can differ between controllers. If yours does not match, use `L` — it
reads whatever your pad actually sends — or run
`uv run controller_remote.py --diagnose` to print the index of each button as
you press it.

Note that `controller_remote.py` has its own separate mapping in `config.json`;
the two are unrelated.

## mini_config.json

Behavior — which roster, which buttons, where the window sits
(see [button mapping](#where-the-controller-buttons-are-mapped) above):

| Key | Meaning |
| --- | --- |
| `students_file` | Roster path. Relative paths resolve next to the script. |
| `theme` | Filename (no `.json`) of a theme in `themes/`. |
| `controller.pick_button` | Button that draws a name. |
| `controller.theme_button` | Button that cycles to the next theme. |
| `controller.reset_button` | Button that resets the pool; `null` to disable. |
| `controller.joystick_index` | Which pad to listen to, if several are plugged in. |
| `window.x` / `window.y` | Saved screen position; `null` centers the window. |
| `window.width` / `window.height` | Saved window size; `null` uses the theme's design size. |
| `window.always_on_top` | Keep the window above your slides. |
| `spin_ms` | Shuffle duration before landing. `0` jumps straight to the name. |
| `no_repeats` | `true` drops a picked name until everyone has been called. |

The file is rewritten when you rebind a button, cycle the theme, move the window,
or load a roster with `F`. Comment keys (`_comment`, `_theme`, …) are preserved.

## Themes

Looks live in `themes/*.json` — one file per theme, and `T` (or pad **Y**)
cycles through every file in the folder.

| Theme | Look |
| --- | --- |
| `cyberpunk` | 2077 livery: yellow caps on a flat hot-red ground, dead still except the name, which glitches |
| `dracula` | Dracula purple and pink, cyan glitch fringe, purple bar |
| `monokai` | Monokai's dark olive ground, acid-green name, pink bar |
| `vscode` | VS Code Dark+ — `#1E1E1E` ground with `#007ACC` blue light |
| `csulb` | Charcoal with warm orange light |
| `stranger_things` | Blood-red on near-black, drifting light rays and floating motes |
| `experimental` | Flat and quiet: no lighting effects at all, just type |

Every theme now sets the name as large as the panel allows — see
[filling the window](#filling-the-window) below.

The first five also share one type treatment: names in caps in a technical face
(Orbitron or Rajdhani if you have them, otherwise Windows' Bahnschrift), and
the same glitch on the name, fringed in each theme's own accent colors. Four of
them share one animation — a wide band that blends through every color in that
theme's palette, sweeping down the panel every five seconds — and nothing else
moves. `cyberpunk` runs with no background animation at all.

`stranger_things` and `experimental` keep their own type and their own
backgrounds: Stranger Things its serif with drifting rays and motes,
`experimental` plain.

All but `cyberpunk` and `experimental` are lit: a soft pool of light behind the
name and darkened corners, both of which sit still, plus whatever that theme
animates on top. `experimental` turns all of it off, and `cyberpunk` does too —
its panel is a flat red fill, so the glitching name is the only thing on screen
that moves.

The lighting is all *behind* the name — the name itself renders crisp, with no
halo. The `glow` block controls that halo and ships disabled in every theme;
set `enabled: true` with a `radius` of 2–3 if you ever want the bloom back.

To make your own, copy any of them, edit the numbers, and save it under a new
name in `themes/`. A theme owns the window size, the fonts, the colors, and the
lighting:

```json
{
  "name": "My Theme",
  "window": { "width": 560, "height": 190, "borderless": true, "opacity": 1.0,
              "padding": 14, "corner_radius": 10, "border_width": 3 },
  "font":   { "candidates": ["Georgia", "serif"], "name_size": 52,
              "small_size": 15, "bold": true, "uppercase": false },
  "colors": { "bg_top": [8, 0, 2], "bg_bottom": [30, 2, 6],
              "border": [228, 16, 22], "border_flash": [255, 90, 94],
              "name": [236, 224, 220], "name_winner": [255, 60, 64],
              "muted": [150, 70, 74], "glow": [220, 14, 20] },
  "glow":   { "enabled": false, "radius": 0, "alpha": 0 },
  "background": {
    "gradient":  true,
    "spotlight": { "enabled": true, "color": [255, 40, 44], "alpha": 62,
                   "spread": 2.0 },
    "rays":      { "enabled": true, "count": 6, "color": [220, 14, 20],
                   "alpha": [40, 95], "width": [0.02, 0.06],
                   "speed": [0.015, 0.055] },
    "motes":     { "enabled": true, "count": 28, "color": [255, 90, 90],
                   "alpha": 165, "size": [1, 2], "speed": [0.03, 0.10] },
    "vignette":  { "enabled": true, "color": [0, 0, 0], "alpha": 102,
                   "spread": 1.6 }
  },
  "footer": { "show_counter": true }
}
```

Colors are `[R, G, B]`, 0–255. `font.candidates` is tried in order and the
first family installed on the machine wins. `font.uppercase` draws every name
in caps without touching the roster file — the technical faces read better that
way.

### Filling the window

The name is sized to the room it has, not to a number: `font.fill_window` is on
by default, and the picker grows each name until it runs out of either width or
height. `font.fill` (default `0.94`) is the fraction of the available height it
may use. Short names come out enormous and long ones settle smaller — that is
the trade for using the whole panel, and if you would rather have one constant
size, set `fill_window` to `false` and the theme falls back to `name_size` as
before.

The counter line under the name is given only its own text height plus a
hairline of gap, so nearly all the panel belongs to the name. `font.small_size`
is what to change if you want that line bigger or smaller.

Sizing is measured off each name's rendered ink rather than the font's line
box, because a line box reserves descender room that all-caps text never uses —
measuring it would leave every name visibly short of the space it has. `footer.show_counter` is the small line
under the name — `12 of 24 left` during a round — and setting it `false` drops
the line and re-centers the name in the full window.

The `background` block is the lighting, and every part of it is optional —
omit a section or set `enabled: false` and it simply does not draw:

| Key | What it does |
| --- | --- |
| `gradient` | `false` fills flat with `bg_bottom` instead of blending to `bg_top`. |
| `spotlight` | Soft pool of light behind the name. `spread` is a multiple of the window size — keep it above ~1.8 so the ellipse edge stays off-screen. |
| `rays` | Drifting vertical bands of light. `width` and `speed` are fractions of the window, so they look right at any size. `alpha` is a `[min, max]` range picked per ray. |
| `motes` | Slow floating specks that twinkle. |
| `vignette` | Darkens the corners. `spread` above ~1.4 keeps it from reading as a drawn oval. |
| `grid` | Scrolling neon lattice. `cell` is a fraction of the window height, `speed` is cells per second. |
| `scanbar` | A bright band sweeping down the panel. `height` is a fraction of the window, `period` is seconds per sweep. Give it `colors` — a list — and the band blends through all of them top to bottom, so one sweep carries a whole palette past the name; `color` (singular) still works for a plain band. |
| `scanlines` | CRT lines. `spacing` is a fraction of the window height, `speed` is lines per second. |

There is one more block outside `background`. `name_fx.glitch` tears the name
itself for a short burst on a timer — colour-fringed ghosts thrown either side,
then the name redrawn in sliced horizontal offsets. `cyberpunk` is the only
shipped theme that uses it:

```json
"name_fx": {
  "glitch": { "enabled": true, "period_ms": 2300, "duration_ms": 200,
              "step_ms": 55, "slices": 7, "shift": 11,
              "colors": [[255, 40, 160], [0, 255, 240]], "alpha": 165 }
}
```

It fires for `duration_ms` every `period_ms` — about 9% of the time at those
numbers, so it reads as an occasional hardware fault rather than a permanent
wobble. `step_ms` is how long each set of slice offsets holds, which keeps it
stepping in discrete jumps instead of dissolving into per-frame noise.

Two notes from tuning these: draw `spotlight` and `vignette` *larger* than the
window, or their elliptical edge shows up as a visible oval sitting on the
background; and a strongly colored spotlight tints everything, so if a theme's
name color is close to its light color, use a neutral light instead (that is
why `monokai` lights with off-white rather than green).

## Resizing

Drag the grip in the **bottom-right corner** to resize. The window is
borderless, so there is no window-manager edge to grab — the grip is drawn in
instead, as three small diagonal ticks. `+` and `-` resize from the keyboard,
`0` snaps back to the theme's design size, and `Ctrl` + mouse wheel works too.
Dragging anywhere *other* than the grip still moves the window.

Everything scales with the window. Each theme declares the size it was designed
at (`window.width` / `window.height`), and the picker scales the font, padding,
corner radius, border width, and glow by however much your window differs from
that — so a name in a 1000px-wide window is genuinely bigger, not the same text
floating in more empty space. Long names still shrink to fit, so you can make
the window narrow without the text spilling out.

Your size is saved to `window.width` / `window.height` in `mini_config.json`
and survives restarts. A size you set by hand outranks the theme's own, so
switching themes with `T` keeps your window the size you left it; delete those
two keys (set them back to `null`) to go back to following the theme.

## Always on top

The window is pinned above everything else by default (`window.always_on_top`),
which is the point of the mini picker — it stays visible over your slides.

Setting that flag once at startup is not enough in practice: a full-screen
slideshow (PowerPoint, Keynote, a browser in presentation mode) makes *itself*
topmost when it starts and pushes everything else down. So the picker re-asserts
the flag every two seconds, and comes back to the front on its own if a
slideshow buries it.

Press `O` to toggle it off if it ever gets in the way. This uses a Win32 call
(`SetWindowPos` with `HWND_TOPMOST`) and is a no-op on other platforms;
everything else works cross-platform.

If a saved window position turns out to be off-screen the next time you start —
you dragged it onto a projector, then unplugged the projector — the picker
notices and centers itself instead of opening somewhere you cannot reach.

## Students list

The roster comes from whatever `students_file` points at in `mini_config.json`
— `students.txt` by default, one name per line. Blank lines, duplicates, and a
leading `Name` header line are ignored.

You do not have to restart to change it. The picker re-reads the file about
once a second, so you can edit the roster while it is running and it reloads
the moment you save:

```
Roster reloaded - 24 names
```

`F` still opens a file dialog if you would rather point it at a different file,
and that choice is saved back to `mini_config.json`.

## Adding dependencies

```sh
uv add <package>
```
