# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **GUI no longer freezes** ("Приложение не отвечает"). The home page probed
  `systemctl is-active`, `g3kb-switch -p` and `systemctl is-enabled` on the GTK
  main thread on every 1.5 s tick, each with a multi-second timeout; a hung
  systemd or g3kb-switch blocked the whole window. All daemon probes now run on
  a worker thread (`gui/async_tasks.py`) and deliver a single consistent
  `StatusSnapshot` back through `GLib.idle_add`. The toggle, the autostart
  switch, the app-detection buttons and the history read are all non-blocking.
- The header tab labels are no longer truncated to «Глав…». The window opens
  wide enough for the full labels and, below 600 sp, a `ViewSwitcherBar`
  breakpoint reveals them in the bottom bar.

### Added

- **Punctuation clean-up (part of T9)**, opt-in and off by default: `--` → `—`,
  `...` → `…`, spacing around `, . ! ? ; :`, and guillemets in Cyrillic layouts.
  It never changes a word, only the punctuation and spacing around it. Auto-
  capitalisation and a sentence-final period are separate opt-in toggles.
  Configured in the GUI (Advanced → «Пунктуация») or with the `punctuation_*`
  keys.
- The T9 settings and the punctuation settings are both editable in the GUI
  Advanced page.

- Landing page mobile audit (8 items): removed the leaked developer note
  «Плейсхолдер — замените реальным скриншотом» from all four mock-up SVGs;
  replaced the external shields.io footer badges (broken behind a slow/blocked
  CDN, and not proxied by the host) with self-hosted SVGs in
  `site/public/badges/`; the footer now names the single canonical host
  (linguafix.layero.app) instead of a mirror link that hit a login wall; code
  blocks now wrap instead of clipping
  at 375 px; the install tabs stack vertically on mobile; localised the
  «Privacy First» feature title to «Приватность»; softened the step-03 copy to
  «Атомарно, одной транзакцией».

- The opt-in update check no longer blocks the keyboard event loop: the daily
  network request runs on a worker thread, so a slow or offline network cannot
  freeze typing for the whole request timeout.
- Landing page: the power glyph in the hero and the placeholder window is centred
  again. The arc's sweep flag was inverted, which pushed the icon to the top of
  the button instead of forming a ring around its centre.
- Landing page demo leaves URL, e-mail, path and version tokens untouched,
  matching the daemon's structural-separator rule.
- Re-synced `black` formatting of `tests/test_data_sync.py` with the current
  release of the formatter.

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
- Password-field guard (AT-SPI): a fix is skipped while the focused element is a
  password entry, even if the stop-word list does not cover it.
- Text expansion (snippets). A `[snippets]` table in `snippets.toml` maps a
  trigger to text (with `{date}` / `{time}` placeholders); the daemon expands it
  before layout analysis. Toggle with `text_expander_enabled`.
- Selection fix. `CTRL+SHIFT+L` converts the layout of already-selected text
  (copy, convert, paste, restore) and can be rebound in the GUI.
- Per-app default layout. `app_layouts` maps an application name to a layout
  that is switched to when that application gains focus (`app_layout_switch`).
- Settings export/import. `linguafix export` / `linguafix import` (and the GUI
  **Backup** group) bundle the config, user dictionary and snippets into one
  JSON file. `linguafix restart` restarts the daemon preserving whether it runs
  as a user service; `linguafix config path` prints the config location.
- Opt-in update check. Once a day, when `update_check_enabled` is set, the
  daemon asks the GitHub releases API for the latest tag and logs (and
  notifies) when a newer version exists. Off by default — it is the only
  feature that uses the network. The GUI job now runs under xvfb and includes
  the GUI package in coverage (`.github/workflows/ci.yml`, `coverage-gui.rc`).
- Pre-filled exception list. `exceptions_apps` now ships with terminals, IDEs,
  editors and games (`gnome-terminal`, `code`, `vim`, `steam`, ...), where the
  text typed is a command or an identifier rather than a word. A manual fix
  (`SHIFT+SHIFT`) bypasses the list, so it still works inside a terminal.
- Quiet hours (`quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end`).
  Inside the daily window (may wrap midnight) automatic correction is paused;
  the manual fix keeps working. The GUI home tab explains the pause.
- A correction-history tab in the GUI, backed by a bounded ring of recent fixes
  (`history_size`). Entries hold metadata only — word length, layouts, time and
  an `undone` flag — and the newest can be undone from the tab.

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
