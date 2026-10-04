# LinguaFix — project memory

## Build / test
- Python venv at `.venv`; run `.venv/bin/python -m pytest`. `make check` = ruff + black + mypy --strict + pytest with `--cov-fail-under=85`.
- Baseline after the trigger/scancode work: 392 tests, ~85.8% coverage. CI runs 3.10/3.11/3.12, all green.

## Key invariants (easy to regress)
- The daemon tracks the current word as **scancodes** (`daemon._scancodes`), not just characters. `TextInjector.replace_text(backspace_count: int, new: str, layout: str)`. The daemon passes `len(self._scancodes)`. A string-based backspace count reintroduces the `рhello` truncation bug (first char left behind).
- `uinput` replace = two flushes: backspaces (one `syn`), sleep `backspace_settle_ms` (default 30), then replacement (second `syn`). Single-batch raced Chromium/Electron async Backspace.
- Word-boundary triggers (`on_space`/`on_enter` on by default, `on_tab`/`on_punctuation` off) flush+fix inside the same keystroke. `analysis_timeout` default 0.8 is only the idle fallback for unseparated words.
- Token with an internal separator (`.` `@` `/` `\` `:` `_` `-`) is never rewritten (URLs, e-mails, paths, versions, hyphenated ids). Guard sits AFTER conversion in `_process_buffer_inner` — the privacy test's secret contains `_` and needs the convert path to run.
- Config TOML is **flat** (no `[sections]`), despite the task prompt suggesting `[trigger]`/`[timing]`. `Config.to_dict` has a fixed key set asserted by tests.

## Environment quirks
- `evdev` installed but has no `__version__`. Real target: Debian 13 trixie + GNOME 48 + Wayland (outside declared 42–45 range, still works).
- No `/dev/uinput` access or real keyboard in the dev container; tests monkeypatch `evdev.UInput` with a recording fake and `TextInjector._uinput_available`.
- Tray (AppIndicator3) absent in dev; not a blocker.

## Repo / process
- PR #1 stays in draft; branch `feat/linguafix-initial-implementation`. Use `create_pr` tool only when asked.
