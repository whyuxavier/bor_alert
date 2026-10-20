# Вхід у Telethon через QR-код (без SMS/коду в чаті).
# Запускати в тій самій папці, де лежить bot.py.
# Потрібно: pip install qrcode[pil] python-dotenv
# Ключі беруться з .env (як і в bot.py).

import asyncio
import os

import qrcode
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
DATA_DIR = os.environ.get("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)


async def main():
    client = TelegramClient(os.path.join(DATA_DIR, "monitor_session"), API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        print("✅ Уже авторизовано, сесія готова.")
        await client.disconnect()
        return

    qr = await client.qr_login()

    while True:
        qrcode.make(qr.url).save("qr.png")
        print("Відкрийте файл qr.png у цій папці й відскануйте його в Telegram на телефоні:")
        print("Налаштування → Пристрої → Підключити пристрій")

        try:
            await qr.wait(timeout=30)
            break
        except asyncio.TimeoutError:
            await qr.recreate()  # QR живе недовго — оновлюємо
            print("QR оновлено, відскануйте новий qr.png")
        except SessionPasswordNeededError:
            password = input("Пароль двоетапної перевірки: ")
            await client.sign_in(password=password)
            break

    me = await client.get_me()
    print(f"✅ Вхід виконано як {me.first_name}. Файл monitor_session.session створено.")
    await client.disconnect()


asyncio.run(main())
