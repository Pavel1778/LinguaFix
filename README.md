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
It reads raw key events via `evdev`, tracks the word you are typing, and — the
moment you press Space or Enter — replaces mistyped text and switches the
layout, with no visible pause. Inspired by
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
- 🧩 CLI: `start`, `stop`, `kill`, `status`, `config`, `fix`, `doctor`, `collect-logs`
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
- Пакеты: `python3-evdev`, `wtype` (Wayland) или `xdotool` (X11)
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
linguafix dict add vercel              # научить слово, которое нельзя исправлять
linguafix config show                  # показать конфигурацию
linguafix collect-logs                 # собрать архив для баг-репорта
systemctl --user status linguafix.service
```

Флаг `--dry-run` удобен для отладки: демон полностью читает и анализирует
ввод, пишет в лог, что *собирался* исправить, но не переключает раскладку и
не трогает текст.

Ручное исправление последнего слова по умолчанию — **двойной Shift**
(дважды нажать Shift в течение 300 мс). Двойной Shift работает на любой
клавиатуре, в отличие от прежнего `PAUSE` (клавиши Pause на многих ноутбуках
нет). В GUI то же самое можно задать кнопкой «Изменить»: дважды нажмите
Shift, Ctrl или Alt.

## ⚙️ Конфигурация / Configuration

Файл: `~/.config/linguafix/config.toml` (создаётся с настройками по умолчанию).

```toml
analysis_timeout = 0.8     # запасной таймер простоя, секунды (слова без разделителя)
min_word_length = 3        # не анализировать короткие слова
max_buffer_size = 200      # верхняя граница буфера нажатий
layouts = ["us", "ru"]     # порядок раскладок
backend = "auto"           # auto | uinput | wtype | xdotool
switch_method = "auto"     # auto | g3kb-switch | setxkbmap
notify_on_fix = false      # уведомление при исправлении
tray_enabled = true        # иконка в трее
hotkey = "SHIFT+SHIFT"     # ручной триггер исправления (двойной Shift)
log_level = "INFO"         # DEBUG | INFO | WARNING | ERROR

# Хоткеи. Двойной тап модификатора задаётся как SHIFT+SHIFT / CTRL+CTRL / ALT+ALT.
hotkey_fix_last_word = "SHIFT+SHIFT"
hotkey_undo_last_fix = "CTRL+Z"
hotkey_reload_config = "CTRL+SHIFT+R"
hotkey_double_tap_ms = 300  # окно двойного тапа, мс (100–1000)

# Триггеры по границе слова: слово исправляется мгновенно, без паузы.
on_space = true            # пробел — основной триггер
on_enter = true            # Enter — конец строки
on_tab = false             # Tab (включать осторожно)
on_punctuation = false     # знаки препинания (включать осторожно)
punctuation_chars = ".!?,;:"

# Пауза после удаления перед вводом нового текста (Chromium/Electron).
backspace_settle_ms = 50
# Пауза после триггера по границе (пробел/Enter), пока приложение
# обрабатывает саму клавишу-границу, до начала удаления.
trigger_settle_ms = 50

# Слова, которые никогда не исправляются (пароли, логины, токены).
stop_words = [
  "password", "passwd", "login", "token", "secret", "apikey", "sudo",
]

# T9: исправление опечаток внутри слова (выключено по умолчанию).
typo_correction = false    # true — включить
typo_max_distance = 1      # 1 или 2 опечатки в слове
typo_min_word_length = 4   # не трогать короткие слова
```

Слова исправляются **сразу** при нажатии пробела или Enter — ждать паузы не
нужно. `analysis_timeout` — это лишь запасной таймер для слов, набранных без
разделителя (например, длинного URL). Слова, которые являются частью URL,
e-mail, пути или версии (`github.com`, `test@example.com`, `3.14`), не
исправляются.

### Бренд, имя или техножаргон не исправляется

Частотные словари не знают брендов (`vercel`, `муксуд`), имён и жаргона, поэтому
детектор молчит: он не уверен, что `муксуд` — это английское `vercel`. Научите
слово — и конвертация станет для детектора «известной хорошей»:

```bash
linguafix dict add vercel     # теперь муксуд → vercel срабатывает
linguafix dict list           # показать слова
linguafix dict remove vercel  # удалить слово
```

В GUI есть вкладка **«Словарь»**: добавление и удаление слов, поиск, импорт и
экспорт файла, кнопка «Применить к демону» (перечитывает словарь без
перезапуска). Файл — `~/.local/share/linguafix/dictionary.txt`, по одному слову
на строку. Научаемое слово никогда не переписывается, а его конвертация в
другую раскладку считается верной. Демон сам никогда не пишет набранный текст в
этот файл.

### Исправление опечаток (T9)

Отдельно от раскладки LinguaFix умеет исправлять **опечатку внутри слова**
(`langauge` → `language`, `teh` → `the`). Функция выключена по умолчанию:
неверное исправление хуже, чем его отсутствие. Включается в GUI (вкладка
«Дополнительно» → «Исправление опечаток (T9)») или в конфиге
`typo_correction = true`.

Правило одно, и оно намеренно строгое: слово заменяется, только если оно

* отсутствует в словаре языка,
* не короче `typo_min_word_length` символов,
* отличается от **ровно одного** слова словаря не более чем на
  `typo_max_distance` правок (расстояние Дамерау — перестановка соседних букв
  считается за одну правку).

Если ближайших вариантов два и более (или слово уже верное) — LinguaFix молчит.
Научаемые слова и токены с разделителем (URL, e-mail, путь, `id-с-дефисом`)
никогда не «исправляются». T9 работает только там, где раскладка признана
верной, поэтому не спорит с авто-переключением.

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
| `Permission denied: /dev/input/...` | Перезагрузите udev-правило: `sudo udevadm control --reload-rules && sudo udevadm trigger`; проверьте `getfacl /dev/input/event3` — подробнее [TROUBLESHOOTING: ACL после .deb](docs/TROUBLESHOOTING.md#после-установки-deb-doctor-жалуется-на-права-devinput-или-devuinput) |
| `doctor` из TTY или ssh | Это ожидаемо: тип сессии `unknown` — см. [TROUBLESHOOTING: doctor из TTY/ssh](docs/TROUBLESHOOTING.md#doctor-запущен-из-tty-или-ssh) |
| Переключает, но не заменяет текст | Смените `backend` на `uinput` |
| Исправляет то, что не нужно | Включены проверки `plausibility_check`, `structural_boundaries`, `identifier_guard`; добавьте строку в `custom_skip_regex` — подробнее [TROUBLESHOOTING: ложные срабатывания](docs/TROUBLESHOOTING.md#a-string-i-typed-is-corrected-wrongly-false-positive) |
| Нужно вернуть последнее исправление | Хоткей undo (`CTRL+Z`) или кнопка **«Отменить последнее исправление»** в GUI |
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
- Замена текста атомарна только на бэкенде `uinput`. На фолбэках `wtype` и
  `xdotool` удаление и ввод идут отдельными вызовами, поэтому при аварийном
  завершении посреди замены текст может остаться обрезанным. Используйте
  `uinput` (значение по умолчанию в Debian-пакете), где это возможно.
- Демон слушает все доступные клавиатуры; устройство с именем, содержащим
  `linguafix` или `uinput`, намеренно пропускается (защита от петли).

## 🤝 Contributing

См. [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). Коммиты атомарные:
`feat: …`, `fix: …`, `docs: …`.

## 📄 Лицензия / License

MIT — см. [LICENSE](LICENSE).

История изменений — в [CHANGELOG.md](CHANGELOG.md). Баги и предложения —
в [Issues](https://github.com/Pavel1778/LinguaFix/issues).

## 🙏 Благодарности / Acknowledgements

- [gswitch](https://github.com/skroll/gswitch) — исполнитель исправлений.
- [g3kb-switch](https://github.com/dvorka/g3kb-switch) — переключение раскладки
  в GNOME Wayland.
- [python-evdev](https://python-evdev.readthedocs.io/) — чтение клавиатуры
  (`evdev`) и ввод текста (`evdev.UInput`).
- Идея вдохновлена Caramba Switcher для Windows.
