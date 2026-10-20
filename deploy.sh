#!/bin/bash
# Автооновлення. Запускається з cron кожні 2 хвилини: bash /home/opc/bot/deploy.sh
APP_DIR=/home/opc/bot
cd "$APP_DIR" || exit 1

git fetch -q origin main || exit 0   # немає зв'язку з GitHub — нічого не робимо

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0

# Спочатку перевіряємо синтаксис нової версії, щоб зламаний код не поклав бота
git show origin/main:bot.py > /tmp/bot_check.py
if ! "$APP_DIR/venv/bin/python" -m py_compile /tmp/bot_check.py; then
  echo "$(date) ❌ Нова версія ($REMOTE) має синтаксичну помилку — оновлення пропущено"
  exit 1
fi

git reset -q --hard origin/main
"$APP_DIR/venv/bin/pip" install -q -r requirements.txt
sudo systemctl restart bot
echo "$(date) ✅ Оновлено до $REMOTE"
