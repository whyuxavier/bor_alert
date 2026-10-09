#бот працює на сервері Oracle тому містить шлях до файлів які лежать там

import asyncio
import aiohttp
import json
import os

from telethon import TelegramClient, events
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# API
api_id = 67
api_hash = "ваш_api"
alerts_token = "ваш_api"

channels = [
    "testboralert",
    "operinform",
    "war_monitor",
    "ua_radar_raket",
    "eRadarrua",
    "kyiv_nebo",
    "chyste_nebo"
]

target_channel = "bor_alert"
client = TelegramClient("monitor_session", api_id, api_hash)

COOLDOWN = timedelta(seconds=35)
KYIV_TZ = ZoneInfo("Europe/Kyiv")
last_message_time = None
last_alert_status = None
alert_start_time = None
boryspil_target_sent = False

BORYSPIL_RAION_UID = "78"
ALERT_HISTORY_FILE = "/home/opc/alert_history.json"
channel_link = '<a href="https://t.me/bor_alert">Бориспіль | Монітор</a>'


def kyiv_now():
    return datetime.now(KYIV_TZ).replace(tzinfo=None)


def load_alert_history():
    if not os.path.exists(ALERT_HISTORY_FILE):
        return []

    try:
        with open(ALERT_HISTORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print(f"⚠️ Не вдалося завантажити історію тривог: {e}")
        return []


def save_alert_history(history):
    try:
        with open(ALERT_HISTORY_FILE, "w", encoding="utf-8") as file:
            json.dump(history, file, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Не вдалося зберегти історію тривог: {e}")


alert_history = load_alert_history()


def parse_alert_time(value):
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KYIV_TZ).replace(tzinfo=None)


def save_finished_alert(start_time, finish_time):
    if start_time is None or finish_time is None:
        return

    alert_history.append({
        "started_at": start_time.isoformat(),
        "finished_at": finish_time.isoformat()
    })

    save_alert_history(alert_history)

    print(
        f"💾 Тривогу збережено: "
        f"{start_time.strftime('%d.%m.%Y %H:%M')} — "
        f"{finish_time.strftime('%d.%m.%Y %H:%M')}"
    )


def get_day_statistics(day):
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    count = 0
    total_duration = timedelta(0)

    for item in alert_history:
        try:
            start_time = datetime.fromisoformat(item["started_at"])
            finish_time = datetime.fromisoformat(item["finished_at"])
        except Exception:
            continue

        if finish_time <= day_start or start_time >= day_end:
            continue

        count += 1
        period_start = max(start_time, day_start)
        period_finish = min(finish_time, day_end)
        total_duration += period_finish - period_start

    return count, total_duration


# Повідомлення з каналів
@client.on(events.NewMessage(chats=channels))
async def new_message(event):
    text = event.raw_text.lower()
    message_text = event.raw_text.replace("🛵", "🟠")

    print(f"📨 Нове повідомлення | {kyiv_now().strftime('%H:%M:%S')}")

    global last_message_time
    global boryspil_target_sent

    boryspil_words = [
        "бориспіль",
        "щасливе",
        "гора",
        "дударків",
        "велика олександрівка",
        "баришівка",
        "рогозів",
        "гоголів",
        "вороньків"
    ]

    ignore_words = [
        "бориспільський район",
        "бориспільського району",
        "бориспільському районі",
        "бориспільводоканал",
        "планові роботи",
    ]

    if any(word in text for word in ignore_words):
        return

    is_boryspil = any(word in text for word in boryspil_words)

    is_recon = (
        "область дорозвідка" in text
        and last_alert_status in ["yellow", "red", "active"]
        and boryspil_target_sent
    )

    if "область дорозвідка" in text and not is_recon:
        return

    if not (is_boryspil or is_recon):
        return

    now = kyiv_now()

    if not is_recon and last_message_time and now - last_message_time < COOLDOWN:
        print("⏳ Повідомлення пропущено — ще не минуло 35 секунд")
        return

    if not is_recon:
        last_message_time = now

    if is_boryspil:
        print("📍 ЗНАЙДЕНО ЦІЛЬ НА БОРИСПІЛЬ!")

    if is_recon:
        print("🟡 ЗНАЙДЕНО ДОРОЗВІДКУ!")

    print(event.raw_text)
    print("-" * 40)

    source = event.chat.username

    if source:
        source = f"@{source}"
    else:
        source = "Джерело: Telegram-канал"

    await client.send_message(
        target_channel,
        message_text + f"\n\n{source}",
        silent=is_recon
    )

    if is_boryspil:
        boryspil_target_sent = True

    print("📤 ПОВІДОМЛЕННЯ НАДІСЛАНО")
    print("-" * 40)


# Alerts.in.ua
async def get_boryspil_alert(session):
    url = "https://api.alerts.in.ua/v1/alerts/active.json"
    headers = {
        "Authorization": f"Bearer {alerts_token}"
    }

    async with session.get(url, headers=headers) as response:
        if response.status != 200:
            try:
                error_data = await response.json()
                error_message = error_data.get("message", "Невідома помилка")
            except Exception:
                error_message = "Невідома помилка"

            raise Exception(f"API HTTP {response.status}: {error_message}")

        data = await response.json()

    alerts = data.get("alerts", [])

    boryspil_alerts = [
        alert
        for alert in alerts
        if str(alert.get("location_uid")) == BORYSPIL_RAION_UID
        and alert.get("alert_type") == "air_raid"
    ]

    if not boryspil_alerts:
        return None

    return boryspil_alerts[0]


# Ранкова статистика
async def daily_statistics():
    while True:
        try:
            now = kyiv_now()
            report_time = now.replace(hour=8, minute=0, second=0, microsecond=0)

            if now >= report_time:
                report_time += timedelta(days=1)

            seconds_until_report = (report_time - now).total_seconds()
            await asyncio.sleep(seconds_until_report)

            previous_day = (kyiv_now() - timedelta(days=1)).date()
            alert_count, alert_duration = get_day_statistics(previous_day)
            total_seconds = int(alert_duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            if alert_start_time is not None:
                if last_alert_status == "yellow":
                    current_status = "🟡 Триває жовта тривога"
                elif last_alert_status == "red":
                    current_status = "🔴 Триває червона тривога"
                else:
                    current_status = "⚠️ Тривога триває"
            else:
                current_status = "🟢 Спокійно"

            message = (
                "<b>☀️ Доброго ранку!</b>\n\n"
                "<b>📊 За минулу добу:</b>\n"
                f"🚨 Тривог: <b>{alert_count}</b>\n"
                f"⏱ Загальна тривалість: "
                f"<b>{hours} год {minutes} хв</b>\n\n"
                f"Наразі: <b>{current_status}</b>\n\n"
                f"📡 {channel_link}"
            )

            await client.send_message(
                target_channel,
                message,
                parse_mode="html",
                silent=True,
                link_preview=False
            )

            print(
                f"📊 Ранкова статистика надіслана: "
                f"{alert_count} тривог, "
                f"{hours} год {minutes} хв"
            )

        except Exception as e:
            print(f"⚠️ Помилка статистики дня: {e}")


# Моніторинг тривог
async def monitor_alerts():
    global last_alert_status
    global alert_start_time
    global boryspil_target_sent
    global last_message_time

    timeout = aiohttp.ClientTimeout(total=5)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                alert = await get_boryspil_alert(session)

                if alert is None:
                    current_status = "no_alert"
                else:
                    alert_level = alert.get("alert_level")

                    if alert_level == "yellow":
                        current_status = "yellow"
                    elif alert_level == "red":
                        current_status = "red"
                    else:
                        current_status = "active"

                if last_alert_status is None:
                    last_alert_status = current_status

                    print(
                        f"🚨 alerts.in.ua | "
                        f"Початковий статус: {current_status}"
                    )

                    if alert is not None:
                        started_at = alert.get("started_at")
                        alert_start_time = parse_alert_time(started_at)

                        if alert_start_time:
                            print(f"🕐 Початок поточної тривоги: {alert_start_time}")

                    print("-" * 40)

                elif current_status != last_alert_status:
                    last_message_time = None

                    print(f"🚨 alerts.in.ua | {last_alert_status} → {current_status}")

                    if (
                        last_alert_status == "no_alert"
                        and current_status in ["yellow", "red", "active"]
                    ):
                        print("🚨 ПОЧАТОК ПОВІТРЯНОЇ ТРИВОГИ!")

                        if alert:
                            started_at = alert.get("started_at")
                            alert_start_time = parse_alert_time(started_at)

                            if alert_start_time:
                                print(f"🕐 Початок тривоги: {alert_start_time}")

                    if current_status == "yellow":
                        print("🟡 ЖОВТИЙ РІВЕНЬ ПОВІТРЯНОЇ ТРИВОГИ!")

                        await client.send_message(
                            target_channel,
                            "<b>🟡 Повітряна тривога!</b>\n"
                            "<i>Жовтий рівень!</i>",
                            parse_mode="html"
                        )

                    elif current_status == "red":
                        print("🔴 ЧЕРВОНИЙ РІВЕНЬ ПОВІТРЯНОЇ ТРИВОГИ!")

                        await client.send_message(
                            target_channel,
                            "<b>🔴 Повітряна тривога!</b>\n"
                            "<i>Червоний рівень!</i>",
                            parse_mode="html"
                        )

                    elif current_status == "active":
                        print("⚠️ Активна тривога, але рівень не визначений")

                    elif current_status == "no_alert":
                        print("🟢 ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!")

                        duration_text = ""

                        if alert_start_time:
                            finished_at = kyiv_now()
                            duration = finished_at - alert_start_time
                            total_seconds = int(duration.total_seconds())
                            hours = total_seconds // 3600
                            minutes = (total_seconds % 3600) // 60

                            if hours:
                                duration_text = (
                                    f"\n⏱ Тривалість: "
                                    f"{hours} год {minutes} хв"
                                )
                            else:
                                duration_text = f"\n⏱ Тривалість: {minutes} хв"

                            print(f"⏱ Тривалість тривоги: {hours} год {minutes} хв")
                            save_finished_alert(alert_start_time, finished_at)

                        else:
                            print("⚠️ Час початку тривоги не збережений")

                        await client.send_message(
                            target_channel,
                            "<b>🟢 Відбій повітряної тривоги!</b>" + duration_text,
                            parse_mode="html"
                        )

                        alert_start_time = None
                        boryspil_target_sent = False

                    last_alert_status = current_status

            except Exception as e:
                print(f"⚠️ Помилка alerts.in.ua: {e}")

            await asyncio.sleep(6)


# Запуск
client.start()

print("=" * 40)
print("🟢 БОТ ЗАПУЩЕНИЙ")
print(f"Час запуску: {kyiv_now().strftime('%d.%m.%Y %H:%M:%S')}")
print("📡 Моніторимо канали:")
print(channels)
print(f"📨 Повідомлення надсилаються у: {target_channel}")
print("🚨 alerts.in.ua: Бориспільський район (UID 78)")
print(f"💾 Історія тривог: {ALERT_HISTORY_FILE}")
print("=" * 40)

client.loop.create_task(daily_statistics())
client.loop.create_task(monitor_alerts())
client.run_until_disconnected()
