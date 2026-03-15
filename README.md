# PVZ Payroll Telegram Bot

Telegram-бот для учета смен, геолокации, мотивации и расчета ЗП сотрудников ПВЗ (WB/OZON).

## Что реализовано

- Роли: `employee`, `admin`.
- Подтверждение выхода на завтра (`да/нет/не знаю`) + ежедневный автозапрос.
- Открытие/закрытие смены с геолокацией.
- Гео-контроль по радиусу точки + ручное подтверждение отклонений админом.
- Расчет ЗП:
  - разные ставки на сотрудника/точку;
  - деление мотивации по часам между менеджерами одной смены;
  - бонус за выдачу: `+100 ₽` за каждый полный шаг в `100` товаров;
  - удержания по таблице оспаривания (только статус `не оспорено`);
  - корректировки/надбавки/удержания вручную;
  - дополнительные менеджерские выплаты (типы 1/2/3).
- Периоды выплат:
  - 10-го: `16..последний день` предыдущего месяца;
  - 25-го: `1..15` текущего месяца.
- Google Sheets sync (мотивация/оспаривания).
- Импорт WB-статистики из файла `Работа ПВЗ Wildberries (1).xlsx` (лист `Статистика по выдаче и приёмке`).
- Учет расходов по пунктам.
- Экспорты CSV/XLSX и отправка в Telegram.

Предустановленный каталог точек (Лесной):
- WB Гоголя 18: 09:00-21:00
- WB Ленина 61: 09:00-21:00
- WB Ленина 114: 09:00-21:00
- WB Мальского 5А: 10:00-21:00
- OZON Ленина 114: 09:00-21:00

## Стек

- Python 3.11+
- aiogram 3
- SQLAlchemy 2 (async)
- SQLite (по умолчанию, можно заменить на PostgreSQL)
- APScheduler
- gspread + Google Service Account
- openpyxl

## Установка локально

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Отредактируйте `.env`:
- `BOT_TOKEN`
- `ADMIN_IDS`
- `GOOGLE_*`
- при необходимости `CRITICAL_CODE`

Инициализация:

```bash
python scripts/init_db.py
python scripts/bootstrap_data.py
```

Запуск:

```bash
python -m app.main
```

## Запуск на Ubuntu/VPS (systemd)

Пример юнита `/etc/systemd/system/pvz-bot.service`:

```ini
[Unit]
Description=PVZ Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/pvz-bot
EnvironmentFile=/opt/pvz-bot/.env
ExecStart=/opt/pvz-bot/.venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Команды:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pvz-bot
sudo systemctl start pvz-bot
sudo systemctl status pvz-bot
```

## Админ-команды

- `/admin_help`
- `/admin_list_users`
- `/admin_add_user tg_id;role;ФИО;phone;manager_bonus_type`
- `/admin_delete_user tg_id` (деактивация)
- `/admin_restore_user tg_id`
- `/admin_list_points`
- `/admin_add_point name;address;brand;lat;lon;radius;work_start;work_end`
- `/admin_delete_point point_id` (деактивация)
- `/admin_restore_point point_id`
- `/admin_seed_lesnoy_points [lat lon radius]`
- `/admin_assign_rate tg_id;point_name;shift_rate;hourly_rate;is_primary`
- `/admin_add_adjustment tg_id;period_start;period_end;type;amount;comment`
- `/admin_sync [YYYY-MM-DD YYYY-MM-DD]`
- `/admin_payroll <10|25> [YYYY-MM-DD ref_date] [critical_code]`
- `/admin_report YYYY-MM-DD YYYY-MM-DD`
- `/admin_expenses YYYY-MM-DD YYYY-MM-DD`
- `/admin_confirmations [YYYY-MM-DD]`
- `/admin_geo_pending`

Примечание по `/admin_add_point`:
- если в `address` указать только `Ленина 61` (без запятых), адрес автоматически дополнится до `Свердловская область, Лесной, Ленина 61`;
- если `name` без префикса бренда, добавится `WB` или `OZON` автоматически.

## Особенности интеграции Google Sheets

Синк рассчитан на колонки с распространенными названиями (например: `дата`, `менеджер/фио/фамилия`, `пвз/адрес`, `приемка`, `выдано`, `тикеты`, `статус`, `сумма`).

Также поддержан ваш текущий блочный формат на листе `Статистика по выдаче и приёмке`:
- строка `ПВЗ ...`
- строка `Дата` (даты по колонкам)
- строка `Товаров отдали`
- строка `Статистика приёмки`

Сопоставление сотрудников:
- по фамилии (`last_name`) из профиля сотрудника.

Сопоставление точек:
- по `name/address` точки.

Если задан `WB_WORKBOOK_FILE`, бот берет основную WB-статистику (приемка + товары отдали) из XLSX-листа `WB_WORKBOOK_STATS_SHEET`. Формат листа поддерживается блочный:
- строка `ПВЗ ...`
- строка `Дата` (даты по колонкам)
- строка `Товаров отдали`
- строка `Статистика приёмки`

Если названия колонок в таблицах отличаются, нужно либо привести шапки, либо расширить aliases в `app/services/google_sheets.py`.

## Важные замечания

- Не храните токены/пароли в коде. Используйте `.env`.
- В `bootstrap_data.py` стоят временные координаты центра города: замените на реальные координаты каждого ПВЗ.
- Для OZON без бонусов задайте ставку `1900` через `/admin_assign_rate` для сотрудников OZON.

## Тесты

```bash
pytest -q
```
