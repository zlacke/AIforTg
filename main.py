import os
import logging
from collections import defaultdict, deque
import time

import httpx
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OR_KEY = os.environ["OPENROUTER_API_KEY"]
AIRLABS_KEY = os.environ["AIRLABS_API_KEY"]

# 📋 Список моделей в порядке приоритета
# OpenRouter free-тариф динамически маршрутизирует, поэтому фолбэк сильно повышает шанс быстрого ответа
MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "qwen/qwen-2.5-7b-instruct:free"  # ⚡ Самый быстрый фолбэк
]

client = AsyncOpenAI(
    api_key=OR_KEY,
    base_url="https://openrouter.ai/api/v1",
    timeout=httpx.Timeout(timeout=40.0, connect=10.0)  # 40 сек на попытку
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("ai-bot")

SYSTEM_PROMPT = "Ты полезный помощник таксист в Telegram. Отвечай по-русски, кратко и по делу."

KEYWORDS = ["погода", "пробки", "холодно", "жарко", "пулкаш", "пулково"]
HISTORY = defaultdict(lambda: deque(maxlen=20))

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Все команды работают!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот готов!\n\n"
        "• /pulkovo — рейсы Пулково\n"
        "• /reset — очистить чат\n"
        "• /test — проверить бота\n"
        "• Напиши: бот ... — чтобы спросить AI"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    HISTORY[update.effective_chat.id].clear()
    await update.message.reply_text("🗑️ История очищена")

async def pulkovo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Загружаю рейсы...")
    url = "https://airlabs.co/api/v9/schedules"
    params = {
        "api_key": AIRLABS_KEY,
        "dep_iata": "LED",
        "limit": 10,
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
        log.exception("AirLabs error")
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

    if not low.startswith("бот "):
        return

    prompt = text[4:].strip()
    if not prompt:
        await update.message.reply_text("Напиши после слова 'бот' свой вопрос.")
        return

    HISTORY[cid].append({"role": "user", "content": prompt})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(HISTORY[cid])

    wait_msg = await update.message.reply_text("⚡ Думаю...")
    start_time = time.time()
    success = False

    for model_name in MODELS:
        # Если ждём больше 50 сек суммарно — прекращаем перебор
        if time.time() - start_time > 50:
            break
            
        try:
            resp = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7,
                max_tokens=300,  # Короткие ответы = быстрее
            )
            answer = resp.choices[0].message.content.strip()
            
            # Помечаем, если ответила не основная модель
            if model_name != MODELS[0]:
                short_name = model_name.split("/")[-1].split(":")[0]
                answer = f"⚡ ({short_name})\n{answer}"
                
            await wait_msg.edit_text(answer)
            HISTORY[cid].append({"role": "assistant", "content": answer})
            success = True
            break
            
        except Exception as e:
            err = str(e).lower()
            # OpenRouter free часто кидает 429, 503, timeout или "overloaded"
            if any(x in err for x in ["429", "rate limit", "timeout", "overloaded", "busy", "503"]):
                log.warning(f"{model_name} занята/лимит, пробую следующую...")
                continue
            else:
                log.error(f"Model error {model_name}: {e}")
                await wait_msg.edit_text("⚠️ Ошибка генерации. Попробуй позже.")
                break

    if not success:
        await wait_msg.edit_text("⏳ Все модели сейчас загружены. Подожди ~1 мин и попробуй снова.")

def main():
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("pulkovo", pulkovo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print(f"🚀 Бот запущен. Цепочка моделей: {len(MODELS)}")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
