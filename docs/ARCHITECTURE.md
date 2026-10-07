# Architecture

This document explains how LinguaFix is put together, why the individual
components were chosen, and where the boundaries of the design are.

## Overview

LinguaFix is a background daemon with no main window. It observes raw keyboard
events, keeps the word currently being typed as a sequence of physical keys, and
— the moment the user presses a word boundary (Space or Enter) — decides whether
the word was typed in the wrong layout. When it is confident, it rewrites the
word and switches the active layout, all within that one keystroke.

```
                       ┌──────────────────────────────────────────┐
                       │              LinguaFixDaemon             │
                       │                                          │
  /dev/input/event*    │  ┌────────────────┐   ┌───────────────┐  │
  ────────────────►    │  │ word buffer    │   │  boundary     │  │
      evdev            │  │ "ghbdtn"       │──►│  Space/Enter  │  │
                       │  │ keys: G H B ...│   │  (immediate)  │  │
                       │  └────────────────┘   └──────┬────────┘  │
                       │        idle fallback ────────┘           │
                       │        (analysis_timeout 0.8 s)          │
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
   events are considered; modifiers and `EV_MSC` (scancode) events are ignored.
2. **Buffer.** Each printable key appends both its character (for detection) and
   its evdev code (for deletion) to the word buffer. Backspace removes the last
   character and its key. The buffer tracks the *word*, so it is flushed at every
   word boundary.
3. **Trigger.** Space and Enter flush the buffer immediately (Tab and
   punctuation are opt-in). The correction therefore happens inside the same
   keystroke that ends the word — there is no visible pause. An idle fallback
   (`analysis_timeout`, default 0.8 s) catches words typed without a separator,
   such as a long URL.
4. **Analyse.** The buffer is handed to the detector, which tokenises it, scores
   each word against the Russian and English n-gram/word corpora and picks the
   most likely language. Tokens that are not words — a URL, an e-mail address, a
   path, a version number or a hyphenated identifier — are recognised by an
   internal separator (`.` `@` `/` `\` `:` `_` `-`) and left alone.
5. **Decide.** If the detected language differs from the active layout, the
   converter produces the "other-layout" rendering of the buffer. If that
   rendering looks more like a real word, the daemon proceeds.
6. **Act.** The switcher changes the active layout and the injector deletes the
   word with Backspace and retypes it in the new layout.

## Scancode replay and the `рhello` bug

The replacement sends one Backspace per *physical key* the user pressed, not per
character in a string. The buffer keeps the evdev codes alongside the
characters, so the deletion can never drift from what is on screen: if a key was
processed late, its code is still in the list, and the count is still exact. A
free-form character buffer can desynchronise (a key the daemon did not process
in time) and leave the first character behind — the `рhello` symptom, where
`руддщ` was deleted but the leading `р` survived.

The uinput backend also flushes the deletion and the replacement as two separate
`syn` batches, with an optional pause (`backspace_settle_ms`, default 50 ms)
between them. Chromium and Electron applications process Backspace
asynchronously, so typing into the same batch can race the deletion. The pause
lets the compositor apply the deletion before the new text arrives. The
backspace batch is still flushed with a single `syn`, so a crash before that
point leaves the text untouched instead of half-deleted.

When the flush is triggered by a word-boundary key (Space/Enter/Tab), the daemon
waits an additional `trigger_settle_ms` (default 50 ms) *before* the deletion.
The boundary key that ended the word is still being processed by the compositor
at that instant; deleting immediately races it and leaves the first character
behind (`руддщ ` -> `рhello`). The idle fallback and an explicit hotkey skip this
pause, because no boundary key is in flight.

A word-boundary trigger is the practical limit of "real time": a word cannot be
corrected before it is finished, because until then the detector does not know
what the word is. Pressing Space is that moment, and the correction costs no
extra keystroke.

## Why evdev + uinput

- `evdev` reads events straight from the kernel, so LinguaFix sees the physical
  keys the user pressed regardless of the current layout or the toolkit the
  focused application uses. This is what makes detection possible at all: the
  application only ever sees the *translated* characters.
- A virtual keyboard (created with `evdev.UInput`, which speaks the kernel
  `uinput` interface) lets the daemon synthesise Backspace and the corrected
  characters. Because the input goes through the same kernel path as a real
  keyboard it works in almost every application, including those that ignore
  synthetic X11/Wayland events.
- The combination works identically on X11 and Wayland, which is why it was
  chosen over toolkit-specific hooks.

The device is created with `evdev.UInput`, not with the `python-uinput`
package. `python-uinput` changed its public API between Debian releases
(`Device`/`emit` versus `UInput`/`write`) and its `KEY_*` constants are
`(event_type, code)` tuples, so `int(uinput.KEY_A)` raises `TypeError` on
Debian 13. Key codes come from `evdev.ecodes` (plain ints), which removes the
dependency and the version skew in one move.

## Device access: uaccess instead of the input group

Reading `/dev/input/event*` and writing `/dev/uinput` both need elevated
device permissions. There are two common ways to grant them, and LinguaFix
deliberately uses the first.

- **`TAG+="uaccess"` in a udev rule (chosen).** `systemd-logind` grants a POSIX
  ACL to the user who is physically logged in at the seat. The ACL is applied
  when that user logs in, is granted only to them, and is removed when the
  session ends. It requires no `usermod` and no relogin after installing, which
  is what makes the `.deb` zero-config.
- **Membership of the `input` group (rejected).** This is permanent: every
  member can read every keyboard, at every seat, whether or not they are the
  active user. It also only takes effect after a full logout/login.

The security difference matters: `uaccess` follows the session, so a background
process belonging to a logged-out user does not keep keyboard access. The
packaged rule is:

```
ACTION!="remove", KERNEL=="event*", TAG+="uaccess"
ACTION!="remove", KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"
```

`OPTIONS+="static_node=uinput"` makes udev create `/dev/uinput` at boot once the
module is loaded, so the node exists before the daemon starts.

Two details are easy to get wrong and both are load-bearing:

- The file is named `71-linguafix.rules`, not `99-*`. On systemd 257+ (Debian 13)
  the rule that turns `uaccess` into an ACL is `73-seat-late.rules`. udev applies
  a tag in filename order, so a `99-*` rule runs after `73-seat-late.rules` and
  the ACL is never applied. Installing the rule before 73 makes it effective.
- Every rule carries `ACTION!="remove"`. `73-seat-late.rules` only processes
  rules that guard against the `remove` event, so a rule without it is skipped.

`linguafix doctor` accepts either mechanism so the developer path (which may
still use the `input` group) is not reported as broken, but the packaged path
never touches group membership.

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

## Logging and privacy

LinguaFix reads everything you type, so it must never persist that text. The
log records only metadata: the buffer length, the source and target layout, and
the action taken. The typed string itself is never written to the log file,
which is rotated at 5 MB with three backups
(`~/.local/state/linguafix/linguafix.log`). The `--dry-run` flag analyses and
logs the same metadata without switching the layout or touching the text, which
makes it safe to run while investigating behaviour.

The same rule applies to every other surface:

- **Notifications.** The desktop notification is a fixed label, never the
  corrected text, so nothing typed reaches the notification history.
- **Subprocesses.** No argv ever contains the typed text. This matters because
  argv is world-readable through `/proc` and is echoed into the journal.
- **Tracebacks.** If a fix raises, the traceback is formatted and the buffer is
  replaced with `<redacted>` before it is logged, so an exception message that
  happens to embed the text cannot leak it.

`tests/test_privacy_audit.py` enforces all of this: it runs a session with a
distinctive secret string and then searches the log, cache, state directory,
config file, user journal and every subprocess argv for any trace of it.

## Failure handling

The daemon is designed to survive the failures that a long-running, keystroke-
reading process will meet in practice:

- **Atomic deletion.** The `uinput` backend writes every backspace and flushes
  them with a single `syn`, then types the replacement as a second flush after
  `backspace_settle_ms`. A crash or `SIGKILL` before the first `syn` leaves the
  text untouched rather than half-deleted, and the settle pause keeps the
  replacement from racing an asynchronous compositor. A boundary-triggered flush
  also waits `trigger_settle_ms` before the deletion, so the Space/Enter that
  ended the word is processed first. The `wtype`/`xdotool` backends cannot be
  atomic; that residual window is documented in the troubleshooting guide.
- **Exact deletion count.** The daemon counts physical keys, not characters, so
  the number of Backspaces always matches what is on screen even under very fast
  typing.
- **Races.** The buffer is snapshotted and cleared under a lock, but the lock is
  released before the slow switch/inject, so keys pressed during a fix are
  buffered for the next pass instead of being dropped.
- **Bounded memory.** The buffer is capped at `max_buffer_size` (default 200).
  A held key or a paste-like burst is analysed and cleared early rather than
  growing without bound.
- **Shutdown.** `SIGTERM`/`SIGINT` set a flag. A fix is skipped if shutdown was
  requested before it started, and always finishes once started. `linguafix
  stop` (and `kill`) stop the systemd user unit first when it is the manager,
  because the unit carries `Restart=always` and would otherwise respawn a
  process killed out from under systemd; `stop` then escalates to `SIGKILL` if
  the daemon does not exit within 3 seconds, and `kill` sends `SIGKILL` at once.
- **Device loss.** When a keyboard disappears the device is dropped and
  discovery is retried in place; `Restart=always` in the unit is the backstop.
- **Every event and every buffer is guarded.** An exception in the detector,
  converter, switcher or injector is logged (redacted) and the loop continues.

## Languages, context and exceptions

Recognition is language-first, not script-first. Every layout is mapped to a
language (`us` → `en`, `ru` → `ru`, `uk` → `uk`, `fr` → `fr`, `de` → `de`) and a
word is scored against the corpora whose *layout could have produced it*.

- **Bundled languages.** `en`, `ru`, `uk`, `de` and `fr` all ship corpora under
  `src/linguafix/data/`. Only `en` and `ru` are loaded by default: the Latin
  layouts (`us`, `de`, `fr`) share physical positions, so loading every corpus
  at once makes them compete and blurs borderline words. Enable the rest with
  `languages = ["en", "ru", "uk", "fr"]` in the config. This is why
  `LanguageDetector()` without arguments keeps behaving exactly as before.
- **Context analysis** (`context_analysis`, `context_weight`). The previous word
  is treated as weak evidence: when it has an unambiguous language, a candidate
  in that language gains `context_weight`. It is additive only, so it can tip a
  borderline word but can never talk the detector out of a clear correction.
  Disable it with `context_analysis = false` or a weight of `0.0`.
- **Per-app exceptions** (`exceptions_apps`). A focused application on this list
  is never touched, in any mode. The list ships pre-filled with terminals, IDEs,
  editors and games (`DEFAULT_EXCEPTION_APPS` in `config.py`) because there the
  other layout is not more plausible — the text is a command or an identifier.
  `exceptions_force_in_manual` lists the applications that stay automatic while
  `mode = "manual"`. The focused application is resolved best-effort; the daemon
  degrades to auto behaviour when it cannot tell, and never reads window contents.
  A manual fix (`SHIFT+SHIFT`) bypasses the exception list, so it still works
  inside a terminal.
- **Quiet hours** (`quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end`).
  Inside the daily window the daemon skips *automatic* correction but keeps the
  manual fix. The window may wrap midnight (`22:00`–`08:00`). The check is
  cached per wall-clock minute and consulted in `_should_fix_buffer`.
- **Correction history** (`history_size`). A bounded ring of recent fixes backs
  the GUI "История" tab. An entry stores only the word *length*, the source and
  target layouts, a monotonic timestamp and an `undone` flag — never the typed
  text. The GUI reads it through `daemon_control.request_history` (SIGUSR2) and
  `read_history` (the atomically-written `history.json`).
- **Skip rules** (`ignore_all_caps`, `ignore_with_digits`, `ignore_emails_urls`,
  `custom_skip_regex`). These short-circuit a buffer before detection. Digital
  tokens, `ALL CAPS` and e-mail/URL/path-like tokens (an internal separator such
  as `. @ / \ : _ -`) are left untouched.
- **False-positive guards** (`plausibility_check`, `structural_boundaries`,
  `identifier_guard`, all on by default). Three layers keep the detector from
  rewriting text that already reads as real words:
  - *Plausibility*: the typed text is scored in the layout it was typed in; if it
    already looks like a real word there, no correction is made. This suppresses
    the `сb cj,jq?ye;yjn/g/` class of false positives.
  - *Structural boundaries*: URLs, e-mail addresses, paths and version numbers
    are recognised and skipped before scoring.
  - *Identifier guard*: `snake_case`, `camelCase`, `x86_64` and similar code
    tokens are treated as identifiers, not prose.
  The guards run **after** the user-dictionary check, so a taught word
  (`муксуд` → `vercel`) is still fixed even when the source looks plausible.
- **User dictionary** (`dictionary_size`, `dictionary_custom_path`). A
  newline-separated list of words the user taught the daemon. It is a deliberate,
  explicit file (`~/.local/share/linguafix/dictionary.txt` by default) — the
  daemon never writes typed text to it on its own. The list is consulted in two
  directions. A taught word is an absolute override: when the buffer *equals* a
  taught word, `target_layout` returns `None` for it in every layout. The
  converted form is also checked: if the wrong-layout rendering of the buffer is
  a taught word (``муксуд`` → ``vercel``), that rendering is accepted as valid and
  the correction fires, even though the brand is absent from the frequency
  corpora. Without this, an unknown brand makes the detector stay silent.
  `dictionary_size` caps the bundled vocabulary (larger = more recall, more RAM).
- **Typo correction (T9)** (`typo_correction`, `typo_max_distance`,
  `typo_min_word_length`). A second, independent correction path, off by
  default. It runs only when `target_layout` returned `None` — that is, when the
  layout is already right — so it can never fight the layout switcher. It uses
  the same vocabulary the detector scores against (`LanguageDetector.vocabulary`)
  and accepts a replacement only when the word is absent from the vocabulary and
  within `typo_max_distance` edits of **exactly one** word (optimal string
  alignment / Damerau-Levenshtein, so a transposition counts as one edit). Two
  equally close candidates mean no change. Taught words and tokens with an
  internal separator are never corrected. `TypoCorrector` instances are built
  lazily per language and dropped on `reload_config`, because the vocabulary can
  change with `dictionary_size` and `languages`.

## Modes and hotkeys

`mode` selects how much the daemon acts on its own: `auto` corrects every word,
`manual` only on the fix hotkey, and `hybrid` corrects automatically but keeps a
short undo history.

Hotkeys are matched in `daemon._parse_hotkey`. A chord such as `CTRL+Z` requires
the modifier to be held; a **double tap** such as `SHIFT+SHIFT`, `CTRL+CTRL` or
`ALT+ALT` fires when the same modifier is pressed twice within
`hotkey_double_tap_ms` (default 300 ms) with nothing else in between. The default
fix hotkey is `SHIFT+SHIFT` because a laptop has no Pause key. Double taps are
tracked separately from chords (`_double_tap_hotkeys`): the first tap arms the
family, a matching second tap within the window fires the action and clears the
state, and any other key cancels the arm. A single Shift press never triggers a
fix, so normal capitalisation is unaffected. Hotkeys are re-parsed on
`reload_config`, so editing `config.toml` and sending `SIGHUP` rebinds them live.

## Extension points

- `LanguageDetector` — add a language by dropping `ngrams_<lang>.json` and a
  word list into `src/linguafix/data/` and extending the layout map. Then add the
  language to `SUPPORTED_LANGUAGES` in `config.py`.
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
| `converter.py` | Character maps between layouts (`us`, `ru`, `uk`, `de`, `fr`) |
| `detector.py` | Language detection, context, user dictionary, `target_layout` |
| `dictionary.py` | Reading/writing the user dictionary file |
| `typo.py` | T9: bounded Damerau-Levenshtein + `TypoCorrector` (opt-in) |
| `text_expander.py` | Snippet expansion (trigger -> text) |
| `selection_fix.py` | Convert the layout of already-selected text |
| `app_focus.py` | Best-effort focused-application detection for exceptions |
| `app_layouts.py` | `AppLayoutManager`: switch layout when a mapped app gains focus |
| `switcher.py` | `g3kb-switch` / `setxkbmap` layout control |
| `injector.py` | Text replacement via `uinput` / `wtype` / `xdotool` |
| `daemon.py` | `LinguaFixDaemon`: event loop, buffering, orchestration |
| `daemon_control.py` | Start/stop/reload/undo a daemon however it was launched |
| `backup.py` | Export/import a JSON bundle of config + dictionary + snippets |
| `update_check.py` | Opt-in GitHub release check (daily, off by default) |
| `doctor.py` | `linguafix doctor`: environment and permission diagnosis |
| `collect_logs.py` | `linguafix collect-logs`: bundle logs for a bug report |
| `tray.py` | Optional AppIndicator icon |
| `cli.py` | `argparse` command-line interface |
| `gui/` | Optional GTK4 + libadwaita preferences window |
