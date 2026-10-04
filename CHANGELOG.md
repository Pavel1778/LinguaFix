# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-04

### Added

- Full 10 000-word frequency dictionaries for all five supported languages
  (`en`, `ru`, `uk`, `de`, `fr`), built from the FrequencyWords lists. The
  detector now loads any of them; `uk`/`de`/`fr` remain opt-in through
  `Config.languages`.
- A Ctrl/Alt chord abandons the word being typed, so `Ctrl+C` no longer leaves a
  stale word for the next Space to "correct". A Ctrl-based fix hotkey
  (`CTRL+F12`) and the `CTRL+CTRL` double tap still see the suspended word.
- A word taught in the user dictionary is honoured as a *converted* form before
  the false-positive guards run, so a brand typed in the wrong layout
  (`муксуд` -> `vercel`) is always fixed.
- Opt-in typo correction (T9). When the layout is already correct, a word within
  one edit (Damerau-Levenshtein) of exactly one dictionary word is replaced
  (`langauge` -> `language`, `teh` -> `the`). Ambiguous words, taught words and
  tokens with a separator are left alone. Toggle it in the GUI (**Advanced** ->
  **Typo correction (T9)**) or with `typo_correction = true`;
  `typo_max_distance` (1 or 2) and `typo_min_word_length` tune it.

### Changed

- Default undo hotkey `CTRL+Z` -> `SHIFT+BACKSPACE` (Ctrl+Z collides with the
  application's own undo).
- The systemd unit runs the daemon with `Nice=-10` and round-robin scheduling so
  a fix wins the race against the compositor's handling of the boundary key.
- `dictionary_size` truncation now keeps the most frequent words (the corpora
  are stored frequency-first) instead of an alphabetical slice.

### Fixed

- A user-taught brand whose source text looks plausible (`муксуд`) was rejected
  by the plausibility guard before the user dictionary was consulted.

## [0.1.0] - 2026-10-04

### Added

- Automatic keyboard-layout correction (`ru` <-> `en`; `uk`/`de`/`fr` opt-in).
- Word-boundary triggers: Space, Enter, Tab, punctuation, plus an idle timeout.
- Scancode-replay replacement with an atomic Backspace batch and
  `backspace_settle_ms` / `trigger_settle_ms` pauses for Chromium/Electron.
- GUI (GTK4 + libadwaita): big on/off toggle, mode switcher, autostart switch,
  user-dictionary page, per-app exceptions.
- Working modes `auto` / `manual` / `hybrid` with undo via `Ctrl+Z`.
- Manual fix hotkey bound to a double tap of Shift by default (configurable).
- Per-app exceptions, context analysis and a user dictionary.
- CLI: `start`, `stop`, `kill`, `status`, `config`, `fix`, `doctor`,
  `collect-logs`, `dict`, `gui`, `mode`, `undo`.
- Zero-config `.deb`: `uaccess` udev rule, systemd user service, autostart entry
  and an application-menu entry.

### Fixed

- Truncation when a fix was triggered by Space/Enter (`руддщ ` -> `рhello`):
  a boundary flush now waits `trigger_settle_ms` before deleting, so the
  boundary key is processed before the Backspaces arrive.
- `Ctrl+Shift+Shift` (and other chords) no longer fire the double-tap fix
  hotkey; a tap counts only when no other modifier family is held.
- Application menu entry appears immediately after install
  (`update-desktop-database` in the `.deb` postinst and `install.sh`).
- False-positive corrections on plausible text, hyphenated identifiers and
  tokens with internal separators.
- Multi-character undo is reliable through the daemon (`linguafix undo`).

### Known limitations

- Password-field detection is not possible on Wayland; stop words are the
  mitigation.
- The `wtype` and `xdotool` backends are not atomic (only `uinput` is).
- GNOME layout switching requires `g3kb-switch`.
- The `uk`/`de`/`fr` corpora are opt-in and have not been calibrated against
  live input.

[0.2.0]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.2.0
[0.1.0]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.1.0
