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

## Collecting diagnostics

```bash
linguafix status
systemctl --user status linguafix.service
journalctl --user -u linguafix.service -n 100 --no-pager
tail -n 100 ~/.local/state/linguafix/linguafix.log
```
