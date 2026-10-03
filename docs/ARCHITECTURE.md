# Architecture

This document explains how LinguaFix is put together, why the individual
components were chosen, and where the boundaries of the design are.

## Overview

LinguaFix is a background daemon with no main window. It observes raw keyboard
events, keeps a short buffer of what was typed, and — after a pause — decides
whether the text was typed in the wrong layout. When it is confident, it
rewrites the text and switches the active layout.

```
                       ┌──────────────────────────────────────────┐
                       │              LinguaFixDaemon             │
                       │                                          │
  /dev/input/event*    │  ┌────────────┐    ┌──────────────────┐  │
  ────────────────►    │  │  buffer    │    │  analysis timer  │  │
      evdev            │  │  "ghbdtn"  │───►│  (idle 1.5 s)    │  │
                       │  └────────────┘    └────────┬─────────┘  │
                       │                             │            │
                       │                             ▼            │
                       │                 ┌──────────────────────┐ │
                       │                 │  LanguageDetector    │ │
                       │                 │  n-grams + words     │ │
                       │                 └──────────┬───────────┘ │
                       │                            │             │
                       │              target layout │             │
                       │                            ▼             │
                       │        ┌──────────────┐  ┌──────────────┐│
                       │        │ LayoutSwitcher│ │ TextInjector ││
                       │        │ g3kb / setxkb │ │ uinput/wtype ││
                       │        └──────┬───────┘  └──────┬───────┘│
                       └───────────────┼─────────────────┼────────┘
                                       │                 │
                                       ▼                 ▼
                                GNOME Shell /       virtual kernel
                                setxkbmap           keyboard
```

## Data flow

1. **Capture.** The daemon opens every keyboard-like device under
   `/dev/input/event*` and waits in a `selectors` event loop. Only `EV_KEY`
   events for letter, space, backspace, enter and tab keys are considered;
   modifiers and `EV_MSC` (scancode) events are ignored.
2. **Buffer.** Printable characters are appended to `buffer`. Backspace removes
   the last character. Enter and Tab flush the buffer immediately.
3. **Analyse.** When no key has been pressed for `analysis_timeout` seconds the
   buffer is handed to the detector. The detector tokenises the buffer, scores
   each word against the Russian and English n-gram/word corpora and picks the
   most likely language.
4. **Decide.** If the detected language differs from the active layout, the
   converter produces the "other-layout" rendering of the buffer. If that
   rendering looks more like a real word, the daemon proceeds.
5. **Act.** The switcher changes the active layout and the injector deletes the
   buffered text with Backspace and retypes it in the new layout.

## Why evdev + uinput

- `evdev` reads events straight from the kernel, so LinguaFix sees the physical
  keys the user pressed regardless of the current layout or the toolkit the
  focused application uses. This is what makes detection possible at all: the
  application only ever sees the *translated* characters.
- `uinput` creates a virtual keyboard that lets the daemon synthesise
  Backspace and the corrected characters. Because the input goes through the
  same kernel path as a real keyboard it works in almost every application,
  including those that ignore synthetic X11/Wayland events.
- The combination works identically on X11 and Wayland, which is why it was
  chosen over toolkit-specific hooks.

## Why g3kb-switch

On GNOME Wayland there is no portable CLI to change the layout. `g3kb-switch`
talks to GNOME Shell over D-Bus and is the de-facto standard tool for this.
On X11 the daemon falls back to `setxkbmap`. The `LayoutSwitcher` abstracts the
two and caches the current layout for a short period to avoid spawning a
subprocess on every keystroke.

## Wayland limitations

Wayland deliberately hides the notion of "which widget has focus" from
unprivileged clients. LinguaFix therefore cannot know whether the caret is in a
password field, a terminal, or a game. The consequences are documented and
mitigated rather than solved:

- **Password fields.** The daemon cannot detect them. Mitigation: a stop-word
  list (`password`, `login`, `token`, …) suppresses corrections for those words.
- **Short words.** One- and two-character words carry almost no statistical
  signal. Mitigation: `min_word_length` (default 3) skips them.
- **Some applications.** A few games and Java/Swing applications intercept input
  in ways that defeat synthetic keystrokes. This is a known limitation.

## Extension points

- `LanguageDetector` — add a language by dropping `ngrams_<lang>.json` and a
  word list into `src/linguafix/data/` and extending the layout map.
- `LayoutConverter` — layouts live in `src/linguafix/data/layouts.json`; adding a
  pair is a data-only change.
- `TextInjector` — new backends implement `replace_text` and register in the
  backend-selection logic.
- `LayoutSwitcher` — new session types implement `get_current_layout` and
  `switch_to`.
- `tray.py` — optional; the daemon runs fine without PyGObject installed.

## Module map

| Module | Responsibility |
|---|---|
| `config.py` | `Config` dataclass, XDG paths, TOML load/save |
| `logging_setup.py` | Rotating file logger under `~/.local/state/linguafix/` |
| `converter.py` | Character maps between layouts (`us` ↔ `ru` ↔ `de`) |
| `detector.py` | Language detection, stop words, `should_fix` heuristic |
| `switcher.py` | `g3kb-switch` / `setxkbmap` layout control |
| `injector.py` | Text replacement via `uinput` / `wtype` / `xdotool` |
| `daemon.py` | `LinguaFixDaemon`: event loop, buffering, orchestration |
| `tray.py` | Optional AppIndicator icon |
| `cli.py` | `argparse` command-line interface |
