# Troubleshooting

## Start here: `linguafix doctor`

Before anything else, run the self-diagnosis. It checks the `input` group,
read access to `/dev/input/event*`, `/dev/uinput`, the external tools
(`g3kb-switch`, `wtype`, `xdotool`, `setxkbmap`), the GNOME version, the
session type and the resolved switcher/injector backends, and prints a table
with a hint for every failed check.

```bash
linguafix doctor
```

The exit code is non-zero when a check fails, so it is safe to use in scripts.

## The daemon does not fix anything

1. Check that it is running:
   ```bash
   linguafix status
   ```
2. Look at the log:
   ```bash
   tail -n 100 ~/.local/state/linguafix/linguafix.log
   ```
3. Confirm the analysis timeout is short enough for your typing speed. If you
   pause longer than `analysis_timeout` between words the buffer flushes early,
   but if you type and keep typing quickly across a word boundary the correction
   may be skipped. Try raising it to `2.0` or `2.5`.
4. Make sure the words you type are at least `min_word_length` characters long.

## No permission on /dev/input

Symptom in the log:

```
Permission denied: '/dev/input/event3'
```

Cause: your user is not in the `input` group, or you have not logged out since
being added.

```bash
groups | grep input        # is 'input' listed?
sudo usermod -aG input "$USER"
# then log out completely and back in
```

The udev rule must also be installed:

```bash
ls -l /etc/udev/rules.d/99-linguafix.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## It switches the layout but does not replace the text

The injector backend is probably not able to synthesise input. Check which
backend is active:

```bash
linguafix status
```

- If it says `backend=none`, install `wtype` (Wayland) or `xdotool` (X11), or
  make sure `python3-uinput` is available and `/dev/uinput` is writable.
- If it says `backend=wtype` but nothing happens, the focused application may
  ignore synthetic Wayland input. This affects some games and Java/Swing apps.

Force a specific backend in `~/.config/linguafix/config.toml`:

```toml
backend = "xdotool"
```

## Nothing is corrected in the terminal

Terminals often use their own key handling. Try forcing the `uinput` backend,
which goes through the kernel like a real keyboard:

```toml
backend = "uinput"
```

## The tray icon is missing

The tray is optional and requires PyGObject with AppIndicator support:

```bash
sudo apt install python3-gi gir1.2-appindicator3-0.1
```

If GNOME does not show AppIndicator icons, install the "AppIndicator and
KStatusNotifierItem Support" GNOME extension. If PyGObject is missing LinguaFix
logs an INFO message and keeps running without a tray icon.

## Conflict with IBus / Fcitx

IBus and Fcitx also intercept and transform keyboard input. Running them next to
LinguaFix can lead to double conversion or missed corrections. If you do not use
them for an input method, disable them; otherwise prefer a single layout source.

```bash
# IBus
ibus exit
# Fcitx
fcitx5-remote -e
```

## The layout does not switch on Wayland

LinguaFix uses `g3kb-switch` on GNOME Wayland. Install it and verify:

```bash
g3kb-switch -p     # prints the current layout index
g3kb-switch -s 1   # switches to the second layout
```

If `g3kb-switch` is missing, LinguaFix can still replace text but cannot change
the active layout.

## Backspace does not delete in the terminal (or deletes too much)

Some terminals handle synthetic Backspace differently from real Backspace.
Symptoms: the old text stays, or the correction eats characters it should not.

- Force the kernel path, which behaves like a physical keyboard:
  ```toml
  backend = "uinput"
  ```
- If you use `xdotool`, `--clearmodifiers` is already passed; a stuck modifier
  from the surrounding session can still interfere. Press and release both
  Shift keys once, then retry.
- In `vim`/`nano`, the correction happens in normal mode. LinguaFix only
  rewrites what it believes is an input buffer; in a full-screen editor that
  assumption may not hold. Use `min_word_length` to reduce false triggers, or
  add the surrounding words to `stop_words`.

## Permission denied on /dev/uinput

```
Could not create uinput device
PermissionError: [Errno 13] Permission denied: '/dev/uinput'
```

The `uinput` backend needs write access to `/dev/uinput`. Check and fix:

```bash
ls -l /dev/uinput
sudo modprobe uinput                      # load the module if missing
ls -l /etc/udev/rules.d/99-linguafix.rules # udev rule installed?
sudo udevadm control --reload-rules && sudo udevadm trigger
```

The udev rule sets `GROUP="input", MODE="0660"`. Make sure you are in the
`input` group and that you have logged out completely since being added. When
`uinput` is unavailable, LinguaFix falls back to `wtype` or `xdotool`; set
`backend = "auto"` to allow that.

## uinput created the device but no text appears

The kernel accepted the virtual keyboard but the compositor did not route its
events to the focused window. This happens when the virtual device is created
after the window grabbed the keyboard, and in some games that read the device
directly. Switch the window focus away and back, or force `wtype`/`xdotool`:

```toml
backend = "wtype"
```

## IBus / Fcitx conflict in detail

IBus and Fcitx sit between the kernel and the application, so a keystroke can be
consumed twice: once by LinguaFix (reading `/dev/input`) and once by the input
method. Symptoms: characters appear twice, the layout flips twice, or nothing is
corrected.

Diagnose:

```bash
echo "$GTK_IM_MODULE $QT_IM_MODULE $XMODIFIERS"
pgrep -a ibus; pgrep -a fcitx
```

If you do not need the input method (for example, you only switch between `us`
and `ru` with GNOME's own layout switcher), disable it:

```bash
ibus exit                 # IBus
fcitx5-remote -e          # Fcitx5
```

For a permanent change, unset `GTK_IM_MODULE`/`QT_IM_MODULE` in your session
environment. Do not run LinguaFix and an input method that performs the same
correction at the same time.

## Corrections trigger while typing a password

On Wayland the daemon cannot see which window has focus, so it cannot tell a
password field from a text field. Mitigations:

- Keep the default `stop_words` (`password`, `login`, `token`, `secret`, ...).
- Add the words that appear around your passwords to `stop_words`.
- Raise `min_word_length` so short passwords are ignored.
- Disable LinguaFix while entering credentials: `linguafix stop` and
  `linguafix start` afterwards.

## Collecting diagnostics

The fastest way is one command that gathers everything:

```bash
linguafix collect-logs
```

It writes `~/linguafix-logs-YYYYMMDD-HHMMSS.tar.gz` containing the `doctor`
output, the configuration, the log tail, the user journal, environment details,
device permissions and package versions. Attach it to the GitHub issue. The
daemon logs only metadata, so the archive never contains the text you typed.

Manual equivalent:

```bash
linguafix status
systemctl --user status linguafix.service
journalctl --user -u linguafix.service -n 100 --no-pager
tail -n 100 ~/.local/state/linguafix/linguafix.log
```
