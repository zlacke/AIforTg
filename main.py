import os
import logging
from collections import defaultdict, deque

from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TG_TOKEN = os.environ["7962775610:AAFl9uWxHYKrAMfVI6ByAI8RCYNL8Y3PNGM"]
DS_KEY = os.environ["sk-7cd75c9ecf5c4be8b27625606ea47c25"]

client = AsyncOpenAI(
    api_key=DS_KEY,
    base_url="https://api.deepseek.com",
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("deepseek-tg")

SYSTEM_PROMPT = (
    "Ты полезный помощник-таксист в Telegram. "
    "Отвечай по-русски, кратко и по делу. "
    "Если вопрос про погоду, пробки или факты — отвечай нормально. "
    "Не упоминай, что ты ИИ, если это не нужно."
)

HISTORY = defaultdict(lambda: deque(maxlen=20))
MODE = defaultdict(lambda: "deepseek-v4-flash")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "DeepSeek бот запущен.\n"
        "Пиши текстом — я отвечу.\n"
        "/reset — очистить историю\n"
        "/mode — показать модель"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    HISTORY[update.effective_chat.id].clear()
    await update.message.reply_text("История очищена.")

async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(f"Модель: {MODE[cid]}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    user_text = update.message.text.strip()

    HISTORY[cid].append({"role": "user", "content": user_text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *HISTORY[cid]]

    placeholder = await update.message.reply_text("…")

    try:
        resp = await client.chat.completions.create(
            model=MODE[cid],
            messages=messages,
            temperature=0.7,
            max_tokens=1200,
        )
        answer = resp.choices[0].message.content.strip()
        if not answer:
            answer = "Не смог ответить."
        await placeholder.edit_text(answer[:4000])
        HISTORY[cid].append({"role": "assistant", "content": answer})
    except Exception as e:
        log.exception("DeepSeek error")
        await placeholder.edit_text(f"Ошибка: {e}")

def main():
    app = ApplicationBuilder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("mode", mode))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()