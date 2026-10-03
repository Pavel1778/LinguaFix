# LinguaFix

> **Твой язык. Автоматически.** — Your language. Automatically.
> Автоматическое переключение раскладки клавиатуры для Debian GNOME (X11 и Wayland).

[![CI](https://github.com/Pavel1778/LinguaFix/actions/workflows/ci.yml/badge.svg)](https://github.com/Pavel1778/LinguaFix/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Debian / Ubuntu](https://img.shields.io/badge/platform-Debian%20%7C%20Ubuntu-A80030.svg)](#-требования--requirements)

---

## 🇷🇺 О проекте

Вы печатаете `ghbdtn`, а на экране появляется `ghbdtn` вместо `привет`?
LinguaFix замечает это, исправляет текст и переключает раскладку —
автоматически, без вашего участия.

Демон читает нажатия клавиш напрямую через `evdev`, накапливает набранный
текст и после короткой паузы проверяет, соответствует ли он текущей
раскладке. Если слово «превращается» в осмысленное при смене раскладки —
LinguaFix переписывает его и переключает язык. Проект вдохновлён
**Caramba Switcher** для Windows (упоминание бренда только как источника идеи).

## 🇬🇧 About

LinguaFix is a background daemon for Debian GNOME (X11 and Wayland) that
detects text typed in the wrong keyboard layout and fixes it automatically.
It reads raw key events via `evdev`, buffers what you type, and — after a short
idle timeout — replaces mistyped text and switches the layout. Inspired by
Caramba Switcher for Windows.

## 🖼️ Демо / Demo

```
  Печатаете:   ghbdtn
  Получаете:   привет   ← LinguaFix исправил и переключил раскладку
```

![demo placeholder](docs/demo-placeholder.svg)

## ✨ Возможности / Features

- 🔄 Автоматическое определение неверной раскладки
- ⌨️ Исправление уже набранного текста (`ghbdtn` → `привет`)
- 🌐 Работает в X11 и Wayland (GNOME)
- 💻 Совместим с терминалами, браузерами и IDE
- 🚀 Автозапуск при входе в систему
- 🔔 Уведомления (`notify-send`) и иконка в трее (AppIndicator)
- 🛡️ Стоп-слова для защиты паролей и логинов
- ⚙️ Настраиваемые таймауты, языки и backend'ы
- 🧩 CLI: `start`, `stop`, `status`, `config`, `fix`, `doctor`, `collect-logs`
- 🩺 `linguafix doctor` — самодиагностика окружения с таблицей ✅/❌ и подсказками
- 📦 `linguafix collect-logs` — один tarball со всей диагностикой для баг-репорта
- 🔁 Горячая перезагрузка конфига по `SIGHUP`
- 🧪 Флаг `--dry-run` — анализ без изменения текста (отладка и тесты)
- 🔒 Приватность: в лог пишутся только метаданные, набранный текст не сохраняется

## 🎯 Сравнение с аналогами / Comparison

| Возможность | XNeur | gswitch | lay | LinguaFix |
|---|---|---|---|---|
| Автоматическое исправление | ⚠️ | ❌ | ⚠️ | ✅ |
| Wayland | ❌ | ✅ | ❌ | ✅ |
| Работа в терминалах | ⚠️ | ✅ | ⚠️ | ✅ |
| Переключение раскладки | ⚠️ | ❌ | ❌ | ✅ |
| Защита паролей (стоп-слова) | ❌ | ❌ | ❌ | ✅ |
| Иконка в трее | ✅ | ❌ | ❌ | ✅ |

## 📋 Требования / Requirements

- Debian 12+ или Ubuntu 22.04+
- GNOME 42–45 (протестированный диапазон; `g3kb-switch` зависит от версии
  GNOME Shell — вне этого диапазона переключение раскладки может не работать)
- X11 или Wayland
- Python 3.10+
- Пакеты: `python3-evdev`, `python3-uinput`, `wtype` (Wayland) или `xdotool` (X11)
- Для переключения раскладки в Wayland: `g3kb-switch`
- Для трея (опционально): `python3-gi`, `gir1.2-appindicator3-0.1`

## 🚀 Установка / Installation

Есть два пути. Обычному пользователю нужен первый.

### Для пользователей: пакет .deb (ничего настраивать не нужно)

```bash
sudo apt install ./linguafix_0.1.0_all.deb
```

Пакет **самодостаточен**: он ставит udev-правило с `TAG+="uaccess"`, включает
systemd user-сервис и загружает модуль `uinput` во время установки. Не нужно
`usermod`, не нужно добавлять себя в группу `input`, не нужно ничего включать
вручную — сервис стартует при следующем входе в сессию.

> ℹ️ Доступ к устройствам выдаётся активному пользователю сессии через ACL
> (`uaccess`), а не постоянным членством в группе. Это безопаснее и не требует
> перелогина после `usermod`.

Готовый `.deb` берётся со страницы
[Releases](https://github.com/Pavel1778/LinguaFix/releases) или собирается
локально: `make build-deb`.

### Для разработчиков: из исходников

```bash
git clone https://github.com/Pavel1778/LinguaFix.git
cd LinguaFix
bash install.sh          # добавьте --yes для неинтерактивного режима
```

`install.sh` ставит то же самое, но в venv внутри `~/.local/share/linguafix`.
Доступ к устройствам по-прежнему выдаётся через udev-правило с `uaccess`.

Подробности: [docs/INSTALL.md](docs/INSTALL.md).

## ⚡ Быстрый старт / Quick start

```bash
linguafix doctor                       # самодиагностика окружения (таблица ✅/❌)
linguafix status                       # проверить, что демон запущен
linguafix fix --text ghbdtn            # предпросмотр исправления
linguafix fix --text ghbdtn --apply    # применить исправление
linguafix fix --text ghbdtn --apply --dry-run   # показать, но не применять
linguafix start --foreground --dry-run # демон-наблюдатель: только логирует
linguafix config show                  # показать конфигурацию
linguafix collect-logs                 # собрать архив для баг-репорта
systemctl --user status linguafix.service
```

Флаг `--dry-run` удобен для отладки: демон полностью читает и анализирует
ввод, пишет в лог, что *собирался* исправить, но не переключает раскладку и
не трогает текст.

## ⚙️ Конфигурация / Configuration

Файл: `~/.config/linguafix/config.toml` (создаётся с настройками по умолчанию).

```toml
analysis_timeout = 1.5     # пауза перед анализом, секунды
min_word_length = 3        # не анализировать короткие слова
layouts = ["us", "ru"]     # порядок раскладок
backend = "auto"           # auto | uinput | wtype | xdotool
switch_method = "auto"     # auto | g3kb-switch | setxkbmap
notify_on_fix = false      # уведомление при исправлении
tray_enabled = true        # иконка в трее
hotkey = "PAUSE"           # ручной триггер исправления
log_level = "INFO"         # DEBUG | INFO | WARNING | ERROR

# Слова, которые никогда не исправляются (пароли, логины, токены).
stop_words = [
  "password", "passwd", "login", "token", "secret", "apikey", "sudo",
]
```

После правки конфига перезапустите сервис или отправьте `SIGHUP`:

```bash
systemctl --user restart linguafix.service
# или
kill -HUP "$(cat ~/.cache/linguafix/daemon.lock)"
```

## 🩺 Troubleshooting

| Проблема | Решение |
|---|---|
| Не исправляет | Запустите `linguafix doctor` — он проверит права, устройства и backend'ы |
| `Permission denied: /dev/input/...` | Перезагрузите udev-правило: `sudo udevadm control --reload-rules && sudo udevadm trigger`; проверьте `getfacl /dev/input/event3` |
| Переключает, но не заменяет текст | Смените `backend` на `uinput` |
| Не работает в терминале | Попробуйте `backend = "uinput"` |
| Нет иконки в трее | Установите `python3-gi gir1.2-appindicator3-0.1` |
| Сообщаете о баге | Приложите `linguafix collect-logs` — в архиве нет набранного текста |
| Конфликт с IBus/Fcitx | Отключите их, если не используете |
| Не переключает раскладку в Wayland | Установите `g3kb-switch` |

Полностью: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## ❓ FAQ

**Работает ли LinguaFix в полях пароля?**
Нет — Wayland не позволяет определить, что фокус в поле пароля. Используйте
стоп-слова (`stop_words`), чтобы защитить конкретные строки.

**Почему не сработало в игре?**
Некоторые игры и Java/Swing-приложения перехватывают ввод и игнорируют
синтетические нажатия. Это известное ограничение Wayland.

**Как добавить язык?**
Добавьте раскладку в `src/linguafix/data/layouts.json` и файл
`src/linguafix/data/ngrams_<lang>.json` со словами и биграммами. См.
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

**Почему короткие слова не исправляются?**
У слов из 1–2 символов слишком мало статистического сигнала. Порог задаётся
параметром `min_word_length`.

**Как временно остановить LinguaFix?**
`systemctl --user stop linguafix.service` или `linguafix stop`.

**Нужны ли root-права?**
Только при установке (udev-правило и systemd-сервис). Сам демон работает от
пользователя.

**Как удалить LinguaFix?**
Для `.deb`: `sudo apt remove --purge linguafix`. Из исходников:
`bash uninstall.sh` (добавьте `--purge`, чтобы удалить конфиг и логи).

## 🧑💻 Разработка / Development

```bash
bash scripts/dev_setup.sh     # venv + dev-зависимости
make check                    # ruff + black + mypy --strict + pytest --cov
make test                     # только тесты с покрытием (>80%)
make build-deb                # собрать .deb в dist/
```

Архитектура и принятые решения: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Ручной план тестирования на реальной системе: [docs/TESTING.md](docs/TESTING.md).

## ⚠️ Известные ограничения / Known limitations

- Демон не может определить поле пароля (ограничение Wayland) — митигация:
  стоп-слова.
- Точность на словах из 1–2 символов низкая — митигация: `min_word_length`.
- В некоторых играх и Java-приложениях замена текста может не работать.
- Доступ через `uaccess` применяется при входе в сессию: если пакет установлен
  в уже активной сессии, права появятся после следующего входа/перезагрузки.
- Переключение раскладки в GNOME Wayland требует `g3kb-switch`.

## 🤝 Contributing

См. [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). Коммиты атомарные:
`feat: …`, `fix: …`, `docs: …`.

## 📄 Лицензия / License

MIT — см. [LICENSE](LICENSE).

## 🙏 Благодарности / Acknowledgements

- [gswitch](https://github.com/skroll/gswitch) — исполнитель исправлений.
- [g3kb-switch](https://github.com/dvorka/g3kb-switch) — переключение раскладки
  в GNOME Wayland.
- [python-evdev](https://python-evdev.readthedocs.io/) и
  [python-uinput](https://github.com/tuomasjjrasanen/python-uinput).
- Идея вдохновлена Caramba Switcher для Windows.
