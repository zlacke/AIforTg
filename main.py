import os
import logging
from collections import defaultdict, deque

import httpx
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OR_KEY = os.environ["OPENROUTER_API_KEY"]
AIRLABS_KEY = os.environ["AIRLABS_API_KEY"]

client = AsyncOpenAI(
    api_key=OR_KEY,
    base_url="https://openrouter.ai/api/v1",
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-bot")

SYSTEM_PROMPT = (
    "Ты полезный помощник таксист в Telegram. "
    "Отвечай по-русски, кратко и по делу. "
    "Если про погоду, пробки или аэропорт — дай конкретный ответ."

KEYWORDS = ["погода", "пробки", "холодно", "жарко", "пулкаш", "пулково"]
AI_TRIGGERS = ["бот", "подскажи", "вопрос", "ии"]

HISTORY = defaultdict(lambda: deque(maxlen=20))

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Все команды работают!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 Бот готов!\n\n"
        "• Обращайся ко мне со словом 'Бот' — и я отвечу\n"
        "• /pulkovo — рейсы Пулково\n"
        "• /reset — очистить чат\n"
        "• /test — проверить бота"
    )
    await update.message.reply_text(msg)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    HISTORY[update.effective_chat.id].clear()
    await update.message.reply_text("🗑️ История очищена")

async def pulkovo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Загружаю рейсы...")
    url = "https://airlabs.co/api/v9/schedules"
    params = {
        "api_key": AIRLABS_KEY,
        "dep_iata": "LED",
        "limit": 15,
        "direction": "departures",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(url, params=params)
            data = resp.json()

        flights = data.get("response", [])
        if not flights:
            await update.message.reply_text("❌ Рейсов не найдено")
            return

        msg = ["✈️ Ближайшие вылеты Пулково:"]
        for flight in flights[:10]:
            flt = flight.get("flight_icao", "—")
            dest = flight.get("arr_iata", "—")
            dep = flight.get("dep_time_local", "—")
            status = flight.get("status", "—")
            msg.append(f"{flt} → {dest} | {dep} | {status}")

        await update.message.reply_text("\n".join(msg))

    except Exception as e:
        log.exception("AirLabs")
        await update.message.reply_text(f"❌ AirLabs: {str(e)[:100]}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    text = update.message.text.strip()
    low = text.lower()
    words = [w.strip(".,!?") for w in low.split()]

    if any(k in low or k in words for k in KEYWORDS):
        if any(k in ["пулкаш", "пулково"] for k in words) or "пулк" in low:
            await update.message.reply_text("✈️ Рейсы Пулково: /pulkovo")
            return
        if any(k in ["погода", "холодно", "жарко"] for k in words):
            await update.message.reply_text("🌤️ Хочешь точную погоду? Спроси!")
            return
        if "пробки" in words:
            await update.message.reply_text("🚗 Пробки? Спроси подробнее!")
            return

    has_trigger = any(t in low for t in AI_TRIGGERS)
    is_reply_to_bot = (
        update.message.reply_to_message
        and update.message.reply_to_message.from_user
        and update.message.reply_to_message.from_user.id == context.bot.id
    )

    if not (has_trigger or is_reply_to_bot):
        return

    HISTORY[cid].append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(HISTORY[cid])

    wait_msg = await update.message.reply_text("🤔 Думаю...")

    try:
        resp = await client.chat.completions.create(
            model="google/gemini-2.0-flash-lite-preview-02-05:free",
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
        )
        answer = resp.choices[0].message.content.strip()
        await wait_msg.edit_text(answer)
        HISTORY[cid].append({"role": "assistant", "content": answer})

    except Exception as e:
        log.exception("OpenRouter")
        await wait_msg.edit_text(f"❌ Ошибка AI: {str(e)[:100]}")

def main():
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("pulkovo", pulkovo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("🚀 Бот запускается...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
