# Pygame Student Picker

A small pixel-art random student picker. Loads names from `students.txt`, and on a
controller A-button or Spacebar press plays a ~2-second slot-machine animation that
lands on a random student. No repeats until everyone is picked (or you reset).

This project uses [**uv**](https://docs.astral.sh/uv/) for environment and dependency
management.

## Setup

```sh
uv sync
```

## Run

The picker:

```sh
uv run student_picker.py
```

Because `student_picker.py` has a PEP 723 inline-dependency header, you can also run it
without `uv sync` from anywhere:

```sh
uv run --script student_picker.py
```

The controller presentation remote:

```sh
uv run controller_remote.py
uv run controller_remote.py --diagnose   # print button/axis numbers
```

## Controls (picker)

| Input | Action |
| --- | --- |
| `Space` / Controller **A** (button 0) | Pick a student / continue to next |
| `R` / Controller **B** (button 1) | Reset the pool |
| `Esc` / close window | Quit |

## Students list

Edit `students.txt` — one name per line. Blank lines are ignored.

## Adding dependencies

```sh
uv add <package>
```
