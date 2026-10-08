# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.7] - 2026-10-08

### Fixed

- The undo hotkey documented in `README.md` and `docs/TROUBLESHOOTING.md` now
  matches the real default, `SHIFT+BACKSPACE` (both files said `CTRL+Z`). The
  default has been `SHIFT+BACKSPACE` since v0.2.2 precisely because `CTRL+Z`
  collides with the application's own undo; the daemon does not grab the
  keyboard, so it cannot swallow the chord. A user who followed the docs pressed
  `CTRL+Z`, the daemon's undo never fired, and the *application* undid the
  corrected word — deleting it without the daemon retyping the original, leaving
  the cursor in an empty spot, exactly as reported. A regression test pins the
  documented value to `DEFAULT_UNDO_HOTKEY`.

### Added

- The daemon logs the effective hotkeys at startup (`fix`, `undo`, `toggle`,
  `reload`) so the binding is discoverable without opening the GUI. The log
  holds the binding names only, never typed text. The undo path also logs
  `backspace count` and the layout transition at DEBUG level.

### Changed

- CI: every job now sets `timeout-minutes: 15`. A stuck GitHub runner once left
  the Python 3.12 job pending for ~49 minutes (the same suite finishes in ~1
  minute), which hung the whole check; the timeout bounds that. A regression
  test asserts every job keeps a timeout.

## [0.2.6] - 2026-10-08

### Fixed

- The `Received SIGUSR2` log spam is gone for real. The daemon now rewrites its
  metadata-only history snapshot itself whenever the history changes (a fix or
  an undo); the GUI only *reads* the file and no longer signals the daemon on a
  2 s poll timer. The v0.2.5 fix gated one tab's timer but the daemon's own
  per-fix write was never triggered without the signal, so the log stayed noisy.
- `typo_correction` (and any other GUI setting) is no longer reset to `false`
  after a reinstall or a mode change. The daemon's `_persist_config` used to
  dump its whole, possibly stale, in-memory config over the file; it now applies
  only the field it changed onto the current file contents.
- A double Shift now fixes 1-2 character tokens (`фт` -> `an`), which the
  ordinary detector skips below `min_word_length`. A conversion is applied only
  when it is unambiguous: the result must be a known word of the target language
  and the token must not already be a word of the current one; a taught word
  always wins. Ambiguous tokens (for example a lone letter) are left untouched.
- An invalid `config.toml` value now logs the exact key it dropped, so a silent
  revert to a default is traceable to the offending line.

### Added

- The `.deb` `postinst` runs `systemctl --user daemon-reload` after replacing
  the unit, so the next `systemctl --user restart linguafix.service` no longer
  warns that the unit changed on disk.
- `linguafix doctor` gains a "Графический интерфейс" check that names the exact
  packages to install (`python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`) when the
  GTK4/libadwaita stack is absent. The GUI stack is a `Recommends` of the
  `.deb` (a headless install does not need it), so a download followed by
  `--no-install-recommends` previously failed with a bare message; the
  requirement is now documented and diagnosed up front.

### Changed

- The Home tab's 1.5 s status poll is paused while the tab is hidden and
  refreshes on open, so a background window does not keep probing
  `systemctl`/`g3kb-switch`/D-Bus.

### Fixed

- `apt remove --purge` now leaves no empty `/usr/lib/linguafix` directories
  behind. The new `doctor` GUI check imports `linguafix.gui`; run as root, that
  writes root-owned `gui/__pycache__` under `/usr/lib`, which dpkg does not
  track. `postrm` now removes every nested `__pycache__` and prunes the
  directories it leaves empty.

## [0.2.5] - 2026-10-08

### Fixed

- The History tab no longer signals the daemon every 2 seconds (`Received
  SIGUSR2` log spam). The GUI polled the history snapshot regardless of which
  tab was visible; it now pauses while the page is hidden and refreshes on open.
- A layout correction can no longer rewrite text in the *same* layout. If the
  detector returned the current layout, the daemon deleted and retyped the word
  in place, which could deform it (the reported `Fixing buffer of length N (ru
  -> ru)`); such a fix is now refused and logged with `reason=`.
- One invalid value in `config.toml` no longer resets *every* setting to its
  default. `Config.from_dict` now drops only the offending keys, so a hand-edited
  typo cannot silently turn `typo_correction` (or anything else) back off.
- The big power button falls back to a Cairo-drawn glyph when the active icon
  theme cannot resolve `system-shutdown-symbolic`, so it is never a broken-image
  placeholder on a non-Adwaita theme.
- The default `backspace_settle_ms` is now 120 ms (was 80 ms), giving Chromium
  and Electron more time to apply the synthetic Backspaces before the
  replacement characters arrive.

### Added

- `linguafix logs [-n N] [-f] [--level LEVEL]` prints (or follows) the daemon
  log, with an optional level filter.
- The `Fixing buffer ...` log line now carries `reason=layout|typo|punctuation`,
  so a correction can be told apart from a typo fix without guessing.


## [0.2.4] - 2026-10-04

### Fixed

- The big power button now uses `system-shutdown-symbolic`. The old name
  `power-symbolic` does not exist in adwaita-icon-theme 48, so the button
  rendered as a broken-image placeholder. A new `tests/test_icons_exist.py`
  scans every `icon_name` in the GUI and asserts it exists in the installed
  icon theme.
- `linguafix fix` now applies the opt-in typo corrector when layout detection
  finds nothing, matching the daemon; `linguafix fix --text "превет"` gives
  `привет` when `typo_correction` is on.
- `linguafix status` now uses the same "running" definition as `stop` and the
  GUI (the flock PID lock, or an active systemd user unit), so a service daemon
  without a lock file is no longer reported as not running.
- `linguafix start` delegates to the shared control module instead of spawning
  and polling on its own, so `start` and the next `status` can no longer
  disagree.
- The manual-fix hotkey now resolves a taught short token (`ы` -> `s`) even when
  it is below `min_word_length`; only a conversion present in the user
  dictionary qualifies.

## [0.2.3] - 2026-10-07

### Added

- Two-edit typo correction for long words: a word of at least six characters may
  now be corrected within `typo_max_distance_long` edits (default 2), but only
  when the best candidate is clearly more frequent than the runner-up. Short
  words keep the strict one-edit rule. Config keys: `typo_max_distance_long`,
  `typo_long_word_threshold`, `typo_top1_ratio_strict`.
- Adaptive idle timeout (`analysis_timeout_adaptive`, on by default): the
  fallback that flushes a word typed without a separator now follows the user's
  typing speed — shorter for a fast typist, longer for a slow one — clamped to
  0.3–2.0 s. Only inter-key timing is recorded, never characters.
- A "Т9" tab in the GUI with a single master toggle for typo correction and the
  new punctuation cleanup, plus per-rule rows.
- Opt-in punctuation cleanup (`punctuation.py`): dashes, ellipsis, Cyrillic smart
  quotes and spacing, applied only when layout detection and typo correction both
  decline. A replacement the input backend cannot type is refused wholesale rather
  than half-applied. Off by default.
- Search-engine metadata for two indexed hosts: each host declares itself
  canonical (`https://linguafix.layero.app` for the Russian primary,
  `https://linguafix.vercel.app` for the English mirror) and cross-links the other
  with `hreflang` (`ru`, `en`, `x-default`), so the copies do not compete as
  duplicate content. A generated `robots.txt` and a sitemap are emitted per host,
  the default `description`/`og:locale`/JSON-LD follow the host language, and the
  README carries a keyword paragraph plus both site links.
- Google and Yandex site-verification files served on both hosts, an
  `apple-touch-icon`, and a footer "About" block in the host language.
- Packaging contract tests (`tests/test_packaging_contract.py`): the systemd
  user unit (no `Nice`/`CPUSchedulingPolicy`, `Restart=always`), the desktop
  entry, package-data coverage, bytecode stripping in `build_deb.sh`, the
  release workflow's tag filter, and a real `dpkg-deb` contents check.

### Changed

- `linguafix fix` now loads the user dictionary before detection, so a taught
  brand such as `vercel` is corrected by the CLI exactly as the daemon does.

### Fixed

- The GUI no longer freezes ("приложение не отвечает"): the home page ran its
  daemon probes (`systemctl`, `g3kb-switch`, `xprop`, the focused-app D-Bus query)
  synchronously on the GTK main thread on a timer and on every toggle click. They
  now run on a worker thread (`gui/async_utils.run_in_background`) and report back
  on the main thread; the toggle click and its reconcile poll are async too.
- The window tab labels are no longer truncated ("Глав…"): the fixed wide
  `ViewSwitcher` is replaced by a header `ViewSwitcherTitle` plus a bottom
  `ViewSwitcherBar` that appears only on narrow windows.
- `daemon_control._systemctl` backs off for 10 s after a timeout so a hung user
  D-Bus cannot re-pay the 5 s timeout on every GUI refresh.
- The desktop launcher declares `StartupWMClass` equal to the application id, so
  GNOME associates the running window with its installed entry.
- Both hosts publish their own sitemap and `robots.txt` instead of the preview
  suppressing them, so each is independently discoverable without duplicate content.

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

### Removed

- Stale release tag `v0.2.0-stage2` and the merged feature branches; `main` is
  the only branch left in `origin`.

## [0.2.2] - 2026-10-07

### Fixed

- `linguafix stop` (and `kill`) now actually stop a packaged daemon. The CLI
  only sent `SIGTERM` to the lock-file PID, so under the systemd user unit
  (`Restart=always`) systemd respawned the daemon about 5 s later and it looked
  unstoppable. Both commands now go through `daemon_control`, which stops the
  unit first; `kill` gained a force-stop path that does the same before sending
  `SIGKILL`.
- GUI settings now reach a running daemon. Every `GuiState.save` asks a live
  daemon to reload, so a switch flipped in the GUI (T9, a trigger, a guard) is
  applied immediately instead of only after a restart. This is why T9 appeared
  "on" but never corrected: the toggle was written to `config.toml` but the
  daemon kept its old in-memory copy.
- The window no longer resizes itself and breaks. The bottom switcher's
  `reveal` had two writers (the `ViewSwitcherTitle` binding and a manual
  `notify::default-width` handler with a different threshold); the duplicate
  handler is gone. The advanced page is added to the stack once at construction
  (hidden until revealed) instead of being appended at runtime to a homogeneous
  `ViewStack`, and the plain pages scroll, so the window shrinks cleanly.

### Changed

- The big on/off button looks like the GNOME quick-settings power button: a
  white circle with a soft outer ring and a thin `power-symbolic` glyph that
  turns accent-coloured when active. The `big-toggle`/`active-state`/`busy-state`
  classes previously had no stylesheet at all. Colours are libadwaita named
  colours, so light/dark themes follow automatically, and the transitions are
  dropped when the system asks for reduced motion.

## [0.2.1] - 2026-10-07

### Fixed

- GUI toggle: удалены невозможные для user-service директивы
  Nice/CPUScheduling из systemd unit (это была причина, почему
  сервис не запускался).
- GUI toggle: расширено окно reconcile до 10 секунд (совпадает
  с START_TIMEOUT).
- GUI toggle: показ реальной причины ошибки через toast
  (systemctl stderr / spawn failure / daemon exited immediately).
- Icon: добавлена зависимость `librsvg2-common` — без неё GNOME
  не рендерит SVG-иконку.
- Icon: добавлена зависимость `hicolor-icon-theme`.
- daemon: `_start_tray()` перенесён внутрь try/finally, чтобы
  исключение в трее не оставляло stale lock.

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

[0.2.3]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.2.3
[0.2.2]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.2.2
[0.2.1]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.2.1
[0.2.0]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.2.0
[0.1.0]: https://github.com/Pavel1778/LinguaFix/releases/tag/v0.1.0
