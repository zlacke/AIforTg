import os
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta

import httpx
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TG_TOKEN = os.environ["7962775610:AAFl9uWxHYKrAMfVI6ByAI8RCYNL8Y3PNGM"]
DS_KEY = os.environ["sk-7cd75c9ecf5c4be8b27625606ea47c25"]
AIRLABS_KEY = os.environ["7802447b-4d2f-4401-8392-ff6913502595"]

client = AsyncOpenAI(
    api_key=DS_KEY,
    base_url="https://api.deepseek.com",
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-bot")

SYSTEM_PROMPT = (
    "Ты полезный помощник в Telegram. "
    "Отвечай по-русски, кратко и по делу."
)

KEYWORDS = ["погода", "пробки", "холодно", "жарко", "пулкаш", "пулково"]

HISTORY = defaultdict(lambda: deque(maxlen=20))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот запущен.\n"
        "Пиши текстом — я отвечу.\n"
        "/reset — очистить историю\n"
        "/pulkovo — ближайшие рейсы"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    HISTORY[update.effective_chat.id].clear()
    await update.message.reply_text("История очищена.")

async def pulkovo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://airlabs.co/api/v9/schedules"
    params = {
        "api_key": AIRLABS_KEY,
        "dep_iata": "LED",
        "limit": 10,
    }

    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(url, params=params)
            data = r.json()

        items = data.get("response", [])[:10]
        if not items:
            await update.message.reply_text("Ближайших рейсов не нашёл.")
            return

        lines = ["✈️ Ближайшие рейсы Пулково:"]
        for item in items:
            flight = item.get("flight", {}).get("iata", "—")
            dep = item.get("dep_time", {}).get("utc", item.get("dep_time", {}).get("local", "—"))
            arr = item.get("arr_time", {}).get("utc", item.get("arr_time", {}).get("local", "—"))
            dest = item.get("arr_iata", "—")
            status = item.get("status", "—")
            lines.append(f"{flight} → {dest} | вылет: {dep} | прилёт: {arr} | {status}")

        await update.message.reply_text("\n".join(lines[:15]))

    except Exception as e:
        log.exception("AirLabs error")
        await update.message.reply_text(f"Ошибка AirLabs: {e}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    text = update.message.text.strip()
    low = text.lower()

    words = low.split()
if any(k in low for k in KEYWORDS) or any(k in words for k in KEYWORDS):
        if "пулк" in low:
            await update.message.reply_text("Хочешь посмотреть ближайшие рейсы Пулково? Напиши /pulkovo")
            return
        if "погода" in low or "холодно" in low or "жарко" in low:
            await update.message.reply_text("Хочешь узнать погоду подробнее? Просто задай мне вопрос.")
            return
        if "пробки" in low:
            await update.message.reply_text("Хочешь узнать подробности про пробки? Просто задай мне вопрос.")
            return

    HISTORY[cid].append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *HISTORY[cid]]

    placeholder = await update.message.reply_text("…")

    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=1200,
        )
        answer = resp.choices[0].message.content.strip() or "Не смог ответить."
        await placeholder.edit_text(answer[:4000])
        HISTORY[cid].append({"role": "assistant", "content": answer})
    except Exception as e:
        log.exception("DeepSeek error")
        await placeholder.edit_text(f"Ошибка: {e}")

def main():
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("pulkovo", pulkovo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
