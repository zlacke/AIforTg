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
    max_retries=0,
    timeout=10.0,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-bot")

SYSTEM_PROMPT = "Ты полезный помощник таксист в Telegram. Отвечай по-русски, кратко и по делу."

KEYWORDS = ["погода", "пробки", "холодно", "жарко", "пулкаш", "пулково"]
HISTORY = defaultdict(lambda: deque(maxlen=20))

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Работает! Fallback включён.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Таксист-бот готов!\n\n"
        "• /pulkovo — рейсы\n"
        "• /reset — очистить\n"
        "• /test — тест\n"
        "• бот [вопрос] — AI"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    HISTORY[update.effective_chat.id].clear()
    await update.message.reply_text("🗑️ История очищена")

async def pulkovo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Рейсы...")
    url = "https://airlabs.co/api/v9/schedules"
    params = {
        "api_key": AIRLABS_KEY,
        "dep_iata": "LED",
        "limit": 10,
        "direction": "departures",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(url, params=params)
            data = resp.json()

        flights = data.get("response", [])
        if not flights:
            await update.message.reply_text("❌ Рейсов нет")
            return

        msg = ["✈️ Вылеты:"]
        for flight in flights[:8]:
            flt = flight.get("flight_icao", "—")
            dest = flight.get("arr_iata", "—")
            dep = flight.get("dep_time_local", "—")
            status = flight.get("status", "—")
            msg.append(f"`{flt} → {dest}` | {dep} | {status}")

        await update.message.reply_text("\n".join(msg), parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ {str(e)[:100]}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    text = update.message.text.strip()
    low = text.lower()

    if any(k in low for k in KEYWORDS):
        if "пулк" in low:
            await update.message.reply_text("✈️ /pulkovo")
            return
        await update.message.reply_text("Спроси AI: `бот [вопрос]`", parse_mode="Markdown")
        return

    if not low.startswith("бот "):
        return

    prompt = text[4:].strip()
    if not prompt:
        await update.message.reply_text("`бот [вопрос]`", parse_mode="Markdown")
        return

    HISTORY[cid].append({"role": "user", "content": prompt})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(HISTORY[cid])

    wait_msg = await update.message.reply_text("🤔")

    models = [
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "openai/gpt-oss-120b:free",
        "google/gemma-4-26b-a4b-it:free",
    ]

    success = False
    for model in models:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=800
            )
            answer = resp.choices[0].message.content.strip()
            await wait_msg.edit_text(answer)
            HISTORY[cid].append({"role": "assistant", "content": answer})
            success = True
            break
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                continue
            await wait_msg.edit_text("⚠️ Я пока не в ресурсе.")
            break

    if not success:
        await wait_msg.edit_text("⚠️ Я на заказе.")

def main():
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("pulkovo", pulkovo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("🚀 Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
