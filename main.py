# Бориспіль | Монітор
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()

# ---------- Налаштування ----------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
ALERTS_TOKEN = os.environ["ALERTS_TOKEN"]
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "bor_alert") 

# Папка з сесією та історією тривог (поза репозиторієм)
DATA_DIR = os.environ.get("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

CHANNELS = ["operinform", "war_monitor", "eRadarrua", "kyiv_nebo", "kyiv_airdef"]

BORYSPIL_RAION_UID = "78"
ALERT_HISTORY_FILE = os.path.join(DATA_DIR, "alert_history.json")
POLL_SECONDS = 6
DEDUP_WINDOW = timedelta(seconds=150)

CHANNEL_LINK = '<a href="https://t.me/bor_alert">Бориспіль | Монітор</a>'
KYIV_TZ = ZoneInfo("Europe/Kyiv")

BORYSPIL_WORDS = [
    "бориспіль", "борисполя", "щасливе", "гора", "гору", "дударків",
    "велика олександрівка", "олександрівка", "баришівка", "баришівку",
    "рогозів", "вороньків",
]

IGNORE_WORDS = [
    "бориспільський район", "бориспільського району", "бориспільському районі",
    "бориспільводоканал", "планові роботи", "багринова", "чорна", "батиєва",
]

# Поки вимкнено (разом з обмеженням "більше 20 слів без терміну").
# URGENT_TERMS = ["шахед", "баліст", "ракет", "крилат", "дорозвідка", "пуск", "зліт"]

DIRECTIONS = {
    "північ", "півночі", "північний", "північного",
    "південний", "південь", "півдня", "південного",
    "схід", "сходу", "східний", "східного",
    "захід", "заходу", "західний", "західного",
}

ALERT_TEXT = {
    "yellow": "<b>🟡 Повітряна тривога!</b>\n<i>Жовтий рівень!</i>",
    "red": "<b>🔴 Повітряна тривога!</b>\n<i>Червоний рівень!</i>",
    "active": "<b>🚨 Повітряна тривога!</b>",
}
STATUS_TEXT = {
    "yellow": "🟡 Триває жовта тривога",
    "red": "🔴 Триває червона тривога",
    "active": "⚠️ Тривога триває",
}
MONTHS = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]

# ---------- Стан ----------
client = TelegramClient(os.path.join(DATA_DIR, "monitor_session"), API_ID, API_HASH)

last_alert_status = None       # None / "no_alert" / "yellow" / "red" / "active"
alert_start_time = None
boryspil_target_sent = False   # чи було повідомлення про загрозу Борисполю
recent_messages = []           # для дедуплікації


def kyiv_now():
    return datetime.now(KYIV_TZ).replace(tzinfo=None)


# ---------- Обробка тексту ----------
def contains_phrase(text, phrase):
    pattern = r"(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def has_any(text, words):
    return any(contains_phrase(text, w) for w in words)


def normalize(text):
    text = re.sub(r"@\w+", " ", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return set(text.split())


def clean_message(text):
    text = text.replace("🛵", "")
    text = re.sub(r"@\w+", "", text)  # прибираємо підписи каналів
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# рядок-пункт списку: на початку (після емодзі/символів) число або "біля/на/до/..."
LIST_LINE = re.compile(
    r"^\W*(?:\d+\s+|(?:біля|в бік|у бік|на|до|курсом?|летить|рухається|напрям\w*)\b)",
    flags=re.IGNORECASE,
)


def keep_boryspil_lines(message):
    """Якщо повідомлення — список напрямків, лишає тільки рядки про Бориспіль."""
    lines = [line for line in message.splitlines() if line.strip()]

    if sum(bool(LIST_LINE.match(line)) for line in lines) < 2:
        return message  # не список — лишаємо як є

    targets = [i for i, line in enumerate(lines) if has_any(line, BORYSPIL_WORDS)]
    if not targets:
        return ""

    first = targets[0]
    kept = [
        line for i, line in enumerate(lines)
        if i in targets or (i < first and "київщина" in line.lower())
    ]
    return "\n".join(kept)


def is_duplicate(tokens, now):
    if len(tokens) < 3:
        return False

    recent_messages[:] = [m for m in recent_messages if now - m["time"] <= DEDUP_WINDOW]
    directions = tokens & DIRECTIONS

    for item in recent_messages:
        old = item["tokens"]
        old_directions = old & DIRECTIONS

        if directions and old_directions and directions != old_directions:
            continue  # різні напрямки — не дубль

        shared = tokens & old
        if len(shared) >= 3 and len(shared) / len(tokens | old) >= 0.72:
            return True

    return False


# ---------- Історія тривог ----------
def load_alert_history():
    if not os.path.exists(ALERT_HISTORY_FILE):
        return []
    try:
        with open(ALERT_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Не вдалося завантажити історію тривог: {e}")
        return []


alert_history = load_alert_history()


def save_finished_alert(start, finish):
    alert_history.append({"started_at": start.isoformat(), "finished_at": finish.isoformat()})
    try:
        with open(ALERT_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(alert_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Не вдалося зберегти історію тривог: {e}")


def get_day_statistics(day):
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    count = 0
    total = timedelta(0)

    for item in alert_history:
        try:
            start = datetime.fromisoformat(item["started_at"])
            finish = datetime.fromisoformat(item["finished_at"])
        except Exception:
            continue

        if finish <= day_start or start >= day_end:
            continue

        count += 1
        total += min(finish, day_end) - max(start, day_start)

    return count, total


def parse_alert_time(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(KYIV_TZ).replace(tzinfo=None)


# ---------- Повідомлення з каналів ----------
@client.on(events.NewMessage(chats=CHANNELS))
async def new_message(event):
    global boryspil_target_sent

    raw = event.raw_text or ""
    lowered = raw.lower()

    # Дорозвідка — тільки під час тривоги, після повідомлення про Бориспіль
    is_recon = "область дорозвідка" in lowered
    if is_recon:
        if not (boryspil_target_sent and last_alert_status in STATUS_TEXT):
            return
    elif not has_any(lowered, BORYSPIL_WORDS):
        return

    message = clean_message(raw)
    if not is_recon:
        message = keep_boryspil_lines(message)

    # Ігнор перевіряємо вже після фільтра, щоб один "чужий" рядок не глушив увесь список
    if not message or has_any(message.lower(), IGNORE_WORDS):
        return

    now = kyiv_now()
    tokens = normalize(message)

    if is_duplicate(tokens, now):
        print("⏭️ Дублікат пропущено")
        return

    entry = {"time": now, "tokens": tokens}
    recent_messages.append(entry)

    try:
        await client.send_message(TARGET_CHANNEL, message, silent=is_recon)
    except Exception as e:
        recent_messages.remove(entry)
        print(f"⚠️ Не вдалося надіслати повідомлення: {e}")
        return

    if not is_recon:
        boryspil_target_sent = True

    print(f"📤 Надіслано ({'дорозвідка' if is_recon else 'Бориспіль'}) | {now:%H:%M:%S}")
    print(message)
    print("-" * 40)


# ---------- alerts.in.ua ----------
async def get_boryspil_alert(session):
    url = "https://api.alerts.in.ua/v1/alerts/active.json"
    headers = {"Authorization": f"Bearer {ALERTS_TOKEN}"}

    async with session.get(url, headers=headers) as response:
        if response.status != 200:
            raise Exception(f"API HTTP {response.status}")
        data = await response.json()

    for alert in data.get("alerts", []):
        if str(alert.get("location_uid")) == BORYSPIL_RAION_UID and alert.get("alert_type") == "air_raid":
            return alert

    return None


async def monitor_alerts():
    global last_alert_status, alert_start_time, boryspil_target_sent

    timeout = aiohttp.ClientTimeout(total=5)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                alert = await get_boryspil_alert(session)

                if alert is None:
                    status = "no_alert"
                elif alert.get("alert_level") in ("yellow", "red"):
                    status = alert["alert_level"]
                else:
                    status = "active"

                if last_alert_status is None:
                    # перший запуск — просто запам'ятовуємо стан
                    last_alert_status = status
                    if alert:
                        alert_start_time = parse_alert_time(alert.get("started_at")) or kyiv_now()
                    print(f"🚨 Початковий статус: {status}")

                elif status != last_alert_status:
                    print(f"🚨 {last_alert_status} → {status}")

                    if status == "no_alert":
                        finished_at = kyiv_now()
                        duration_text = ""

                        if alert_start_time:
                            minutes_total = int((finished_at - alert_start_time).total_seconds() // 60)
                            hours, minutes = divmod(minutes_total, 60)
                            if hours:
                                duration_text = f"\n⏱ Тривалість: {hours} год {minutes} хв"
                            else:
                                duration_text = f"\n⏱ Тривалість: {minutes} хв"

                        await client.send_message(
                            TARGET_CHANNEL,
                            "<b>🟢 Відбій повітряної тривоги!</b>" + duration_text,
                            parse_mode="html",
                        )

                        # зберігаємо тільки ПІСЛЯ успішного надсилання (щоб не було дублів)
                        if alert_start_time:
                            save_finished_alert(alert_start_time, finished_at)

                        alert_start_time = None
                        boryspil_target_sent = False

                    else:
                        if last_alert_status == "no_alert":
                            alert_start_time = parse_alert_time(alert.get("started_at")) or kyiv_now()

                        await client.send_message(TARGET_CHANNEL, ALERT_TEXT[status], parse_mode="html")

                    last_alert_status = status

            except Exception as e:
                print(f"⚠️ Помилка моніторингу тривог: {e}")

            await asyncio.sleep(POLL_SECONDS)


# ---------- Ранкова статистика ----------
async def daily_statistics():
    while True:
        now = kyiv_now()
        report_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= report_time:
            report_time += timedelta(days=1)

        # +1 секунда, щоб після пробудження вже точно було після 08:00 (без подвійної відправки)
        await asyncio.sleep((report_time - now).total_seconds() + 1)

        try:
            day = (kyiv_now() - timedelta(days=1)).date()
            count, duration = get_day_statistics(day)
            total_minutes = int(duration.total_seconds() // 60)
            hours, minutes = divmod(total_minutes, 60)

            current = STATUS_TEXT.get(last_alert_status, "🟢 Спокійно")

            message = (
                "<b>☀️ Доброго ранку!</b>\n\n"
                f"<b>📊 Статистика за {day.day} {MONTHS[day.month - 1]}:</b>\n"
                f"🚨 Тривог: <b>{count}</b>\n"
                f"⏱ Загальна тривалість у Бориспільському районі: <b>{hours} год {minutes} хв</b>\n\n"
                f"Наразі: <b>{current}</b>\n\n"
                f"📡 {CHANNEL_LINK}"
            )

            await client.send_message(
                TARGET_CHANNEL, message, parse_mode="html", silent=True, link_preview=False
            )
            print(f"📊 Статистика надіслана: {count} тривог, {hours} год {minutes} хв")

        except Exception as e:
            print(f"⚠️ Помилка статистики дня: {e}")


# ---------- Запуск ----------
client.start()  # акаунт користувача (сесія monitor_session) — бот-токен не бачить чужі канали

print("=" * 40)
print("🟢 БОТ ЗАПУЩЕНИЙ")
print(f"Час запуску: {kyiv_now():%d.%m.%Y %H:%M:%S}")
print(f"📡 Канали: {CHANNELS}")
print(f"📨 Надсилаємо у: {TARGET_CHANNEL}")
print("=" * 40)

client.loop.create_task(daily_statistics())
client.loop.create_task(monitor_alerts())
client.run_until_disconnected()

