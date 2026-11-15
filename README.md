# Башкирия: Мёд и Нефть · LunexEconom V2

Новая версия экономического многопользовательского тренажёра для **Android** (горизонтальный экран, 2.5D по плану), на карте Башкортостана. Игрок управляет компанией, экономическая симуляция идёт на сервере. Этот репозиторий начинается с **нового корневого коммита**. Архив V1 в `archive/v1`; данные и аккаунты V1 не переносятся.

## Структура

- `server/` — PostgreSQL 16, Python 3.12+, независимые пакеты и реестр.
- `client/` — Godot 4.7.2, Android, экран входа и пустая штаб-квартира.
- `web/` — самостоятельный статический лендинг.
- `ops/` — план развертывания и V2-only CI-gated автообновление.
- `tools/` — инструменты проверок.
- `docs/spec/` — утвержденные спецификации, скопированы без редактирования из V1.
- `.github/workflows/` — сервер, клиент, сайт, Android APK.

## Запуск сервера локально

Только **отдельная PostgreSQL 16** для разработки или CI. Никогда не подключать production V1.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
export LUNEX_DATABASE_URL='postgresql://lunex_dev:YOUR_LOCAL_PASSWORD@localhost:5432/lunex_v2_dev'
python -m server.game_server
# GET http://127.0.0.1:18777/health
```

Миграции выполняются автоматически при старте и проверяются по SHA-256. Сборка Android: Godot 4.7.2 `--headless --path client --editor --quit`, затем экспорт Android debug через `client/export_presets.cfg` (нужны Android SDK и шаблоны). Секреты и ключ подписи не хранить в git.

## Проверки

```bash
export LUNEX_TEST_DATABASE_URL='postgresql://lunex_ci:YOUR_CI_PASSWORD@localhost:5432/lunex_v2_ci'
python -m unittest discover -s server/tests -v
python -m unittest discover -s ops -p 'test_*.py' -v
python tools/check_website.py
python -m http.server 8080 --directory web
# Godot 4.7.2 --headless --path client -s tests/smoke.gd
```

CI временно поднимает PostgreSQL 16. Без `LUNEX_TEST_DATABASE_URL` интеграционные тесты **пропускаются**, это не означает, что они пройдены. CI всегда задаёт DSN. Для миграций и ролей использовать изолированную тестовую базу.

## Состояние

**V2-00: каркас.** Доступны `/health`, `/auth/register`, `/auth/login`, `/auth/me`, `/catalog`, каркас тиков и журнал проводок. Сервер не развернут на VPS. Живой клиентский конфиг возвращает 503 до первой доверенной публикации подписи; полноценный подписант и клиентская проверка относятся к следующему этапу. Рабочая экономика и карта пока не реализованы.

См. [архитектуру](docs/ARCHITECTURE.md), [операции](docs/OPERATIONS.md) и [прогресс](docs/PROGRESS.md).
