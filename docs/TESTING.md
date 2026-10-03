# Testing

Testing happens on three levels, from cheapest to most realistic. A layer does
not replace the ones above it — a green pytest run does **not** mean the daemon
works on a real desktop.

| Level | What it runs | How to run | Proves |
|---|---|---|---|
| 1. Unit / integration | Real code, faked OS boundary | `make test` | Logic, parsing, config, conversion |
| 2. Package smoke test | The built `.deb`, installed into a clean `debian:12` container | `make smoke-test` | The package installs, all runtime imports resolve, the CLI starts |
| 3. Manual desktop test | A real GNOME session (Wayland and X11) | This document | Permissions, D-Bus, `uinput`, real applications |

## Level 2: package smoke test

`scripts/smoke_test.sh` builds nothing itself; it installs `dist/*.deb` into a
throwaway `debian:12` container and checks that `linguafix version`, `--help`,
`status` and `doctor` run, and that the daemon starts in `--dry-run`. It catches
the class of bug that pytest cannot: a missing runtime dependency or a broken
entry point in the installed package. It does **not** need a GUI, so it also
runs in CI (see `release.yml`).

```bash
make build-deb
make smoke-test
```

The container has no keyboard devices, so `doctor` is expected to report
failures there; the smoke test only asserts that the commands execute.

## Level 3: manual test plan

The automated suite runs headless and replaces the operating-system boundary
with fakes. It cannot verify permissions, D-Bus behaviour or how real
applications react to synthetic input. This plan covers what must be checked by
hand on a real desktop.

### Environments

Test on both, in a virtual machine:

| # | Distribution | Session | GNOME |
|---|---|---|---|
| 1 | Debian 12 (netinst, GNOME) | Wayland (default) | 43 |
| 2 | Ubuntu 22.04 LTS (GNOME) | Wayland (default) | 42 |

Then repeat the core scenarios switching to **X11** (choose "GNOME on Xorg" in
GDM).

## A. Installation

1. Run `bash install.sh` interactively. Note every prompt and any failure.
2. Confirm the apt packages: `dpkg -l | grep -E 'evdev|uinput|wtype|xdotool|appindicator'`.
3. Confirm the udev rule: `ls -l /etc/udev/rules.d/99-linguafix.rules`.
4. Log out completely and back in.
5. `groups | grep input` — the `input` group must be listed.
6. `linguafix status` — daemon running, backends reported.
7. `ls -l /dev/input/event*` — readable by your user.

## B. Daemon startup

1. `systemctl --user status linguafix.service` — active, no restart loop.
2. `journalctl --user -u linguafix.service -n 50 --no-pager` — no tracebacks.
3. `linguafix start --foreground --dry-run` — the daemon runs and logs
   "Dry run" instead of touching the text.

## C. Correction matrix

In each application, switch to the **wrong** layout, type `ghbdtn` (meaning
"привет"), and record whether LinguaFix corrected it:

| Application | Wayland | X11 | Notes |
|---|---|---|---|
| gnome-terminal | | | |
| Firefox (address bar + text area) | | | |
| Chrome / Chromium | | | |
| VS Code | | | |
| Gedit / Text Editor | | | |
| SuperTuxKart (chat) | | | |

Also test:

- A Russian word typed on the US layout and vice versa.
- Uppercase (`Ghbdtn`).
- Punctuation (`ghbdtn?`, `;b`).
- A password field: the correction must **not** fire for stop words, but note
  whether it fires for non-stop-word content in a password field (known
  limitation).

## D. Layout switching

1. With `g3kb-switch` installed: `g3kb-switch -p` before and after a correction.
2. Without `g3kb-switch` on Wayland: text is replaced but layout is unchanged
   (document the behaviour).
3. On X11: confirm the `setxkbmap` fallback works.

## E. Tray and notifications

1. Tray icon appears (requires the AppIndicator GNOME extension).
2. "Показать статус" shows a notification with the current layout.
3. "Исправить сейчас" triggers a correction.
4. `notify_on_fix = true` shows a notification after each fix.

## F. Privacy and logs

1. Type a word, trigger a correction, then inspect
   `~/.local/state/linguafix/linguafix.log`.
2. The log must contain only metadata (length, layouts) — never the typed text.
3. Confirm rotation config: 5 MB × 3 files.

## G. Conflicts

1. Start IBus or Fcitx and check for double conversions or missed fixes.
2. Document the outcome.

## Reporting

File one issue per problem found, using the bug report template
(`.github/ISSUE_TEMPLATE/bug_report.md`). Apply the `needs-testing` label while
triaging.

Attach a diagnostic bundle — one command collects everything a maintainer needs
(the `doctor` output, configuration, log tail, user journal, environment,
device permissions and package versions):

```bash
linguafix collect-logs
# -> ~/linguafix-logs-YYYYMMDD-HHMMSS.tar.gz
```

The daemon logs only metadata, so the bundle never contains the text you typed.
See `docs/TROUBLESHOOTING.md` for details.
