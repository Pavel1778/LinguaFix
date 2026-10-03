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

## doctor complains about /dev/input or /dev/uinput permissions

Symptom in the log:

```
Permission denied: '/dev/input/event3'
```

The packaged install grants access with a udev rule that uses
`TAG+="uaccess"` (an ACL for the active session user), so the fix is almost
always to make udev re-apply the rule, not to change group membership.

1. Check that the rule is installed and uses `uaccess`:

   ```bash
   cat /usr/lib/udev/rules.d/99-linguafix.rules      # or /etc/udev/rules.d/
   # expected: KERNEL=="event*", TAG+="uaccess"
   #           KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"
   ```

2. Re-apply it and re-check the ACL:

   ```bash
   sudo udevadm control --reload-rules && sudo udevadm trigger
   getfacl /dev/input/event3     # expect a user:<you>:rw- line
   getfacl /dev/uinput
   ```

   If the ACL is missing, log out and back in: `uaccess` is granted when the
   user logs in at the seat.

3. Make sure `/dev/uinput` exists:

   ```bash
   sudo modprobe uinput && ls -l /dev/uinput
   ```

4. If the rule is not there at all, reinstall the package:
   `sudo apt install --reinstall linguafix`.

On the developer path (`install.sh`) the rule lives in
`/etc/udev/rules.d/99-linguafix.rules` and the same steps apply. `linguafix
doctor` accepts either mechanism — a `uaccess` rule or membership of the
`input` group — and only fails when neither is present.

### После установки .deb doctor жалуется на права /dev/input или /dev/uinput

Причина: правило с `TAG+="uaccess"` выдаёт ACL **в момент создания seat-сессии**
(`systemd-logind`). Если пользователь поставил `.deb`, уже находясь в графической
сессии, ACL для него ещё не создан — он появится при следующем входе. Это
штатное поведение `systemd-logind`, а не баг пакета.

Диагностика:

```bash
getfacl /dev/input/event3    # ожидается строка  user:$USER:rw-
getfacl /dev/uinput          # ожидается строка  user:$USER:rw-
ls -l /usr/lib/udev/rules.d/99-linguafix.rules
grep uaccess /usr/lib/udev/rules.d/99-linguafix.rules
```

Если строки `user:$USER:rw-` нет — это и есть причина, применяем решение ниже.

Решение (от простого к сложному):

1. Выйти из GNOME и войти заново, затем проверить `linguafix doctor`.
2. Если не помогло — перезагрузить правило udev и снова перелогиниться:

   ```bash
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

3. Если ACL всё равно нет — убедиться, что пользователь в **активной** seat-сессии,
   а не подключён по ssh:

   ```bash
   loginctl show-user "$USER" | grep State    # ожидается State=active
   ```

   При `State=online` (ssh, cron, TTY без входа в GNOME) ACL не выдаётся по
   дизайну: доступ получает только пользователь, физически сидящий за машиной.

### doctor запущен из TTY или ssh

Поведение: `linguafix doctor` не падает, но строка «Тип сессии» становится
предупреждением:

```
⚠️  Тип сессии                    unknown (XDG_SESSION_TYPE не задан)
                                 ↳ запустите doctor из графической сессии GNOME;
                                   из TTY/ssh переключение раскладки и замена текста недоступны
```

Проверки раскладки и ввода при этом показывают `backend=none session=unknown`,
потому что без сессии нет ни `g3kb-switch`/`setxkbmap` в нужном окружении, ни
доступа к устройствам. Это ожидаемо.

Что делать: запускать `linguafix doctor` из терминала внутри GNOME (не по ssh и
не из TTY), либо заранее задать тип сессии:

```bash
XDG_SESSION_TYPE=wayland linguafix doctor    # или x11
```

Для сбора диагностики с удалённой машины используйте `linguafix collect-logs` —
он фиксирует окружение и не требует графической сессии.

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

## Several keyboards: text typed on the "other" one is not corrected

The daemon listens to every keyboard it can find, not just the first one. If a
keyboard is present but its events never reach the daemon, check:

- The device is not filtered out. Devices whose name contains `linguafix` or
  `uinput` are skipped on purpose to avoid a feedback loop; a keyboard with such
  a name is ignored.
- You have read access to that device's `/dev/input/event*` node (see the
  permission section above). A keyboard that appears after login may need the
  session to be refreshed (`loginctl terminate-session $XDG_SESSION_ID`) for the
  `uaccess` ACL to apply.
- Run `linguafix doctor` and check the "Устройства /dev/input/event*" row.

## The daemon stopped after unplugging a USB keyboard

Expected and handled. When the last keyboard disappears the daemon logs
`Device read error (device removed?)`, drops that device and re-runs discovery
every 2 seconds until a keyboard is back. If recovery ever fails the systemd
unit has `Restart=always`, so the service is restarted with a fresh device list
(the path is rediscovered, never cached). To confirm:

```bash
systemctl --user status linguafix.service
journalctl --user -u linguafix.service -n 50 --no-pager
```

## `linguafix stop` does not stop the daemon

`stop` sends `SIGTERM` and waits up to 2 seconds. If the process is wedged (for
example blocked in a subprocess), `stop` escalates to `SIGKILL` automatically
and prints a warning. To skip the graceful attempt entirely:

```bash
linguafix kill
```

## Corrections trigger while typing a password

On Wayland the daemon cannot see which window has focus, so it cannot tell a
password field from a text field. Mitigations:

- Keep the default `stop_words` (`password`, `login`, `token`, `secret`, ...).
- Add the words that appear around your passwords to `stop_words`.
- Raise `min_word_length` so short passwords are ignored.
- Disable LinguaFix while entering credentials: `linguafix stop` and
  `linguafix start` afterwards.

## Privacy: what LinguaFix does and does not store

LinguaFix never writes the text you type to disk. The log records only metadata
(buffer length, layout names). The tests in `tests/test_privacy_audit.py`
enforce this: they run a session with a distinctive secret string and then
search the log, cache, state directory, config file, systemd journal and every
subprocess argv for any trace of it.

Two consequences worth knowing:

- The desktop notification is a fixed label ("Раскладка исправлена"), not the
  corrected text, so it never appears in the notification history.
- If a fix fails, the exception traceback is redacted of the buffer before it is
  logged.

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
