# Manual test plan

The automated suite (`pytest`, 270+ tests) runs headless and replaces the
operating-system boundary with fakes. It cannot verify permissions, D-Bus
behaviour or how real applications react to synthetic input. This plan covers
what must be checked by hand on a real desktop.

## Environments

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
(`.github/ISSUE_TEMPLATE/bug_report.md`). Attach the environment block and the
relevant log lines. Apply the `needs-testing` label while triaging.
