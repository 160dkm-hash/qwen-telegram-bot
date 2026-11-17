import os
import sys
import time
import json
import zipfile
import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from openai import AsyncOpenAI

# ─── Config ───
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "any_string")
MAX_HISTORY = int(os.getenv("MAX_HISTORY_LENGTH", 10))

# ─── Endpoints ───
ENDPOINTS = {
    "1": {
        "name": "Qwen3.8-Uncensored (Fast)",
        "base_url": "http://136.33.11.112:8000/v1",
        "model": "qwen38-uncensored"
    },
    "2": {
        "name": "Qwen3.8-27B-Uncensored (Smarter)",
        "base_url": "http://34.44.27.60:8000/v1",
        "model": "Qwen3.8-27B-Uncensored-Q4_K_M.gguf"
    }
}

current_endpoint_id = "2"
def get_current_endpoint():
    return ENDPOINTS[current_endpoint_id]

if not BOT_TOKEN:
    print("❌ Missing TELEGRAM_BOT_TOKEN!")
    sys.exit(1)

def create_client():
    ep = get_current_endpoint()
    return AsyncOpenAI(api_key=QWEN_API_KEY, base_url=ep["base_url"])

client = create_client()
conversations = {}
start_time = time.time()

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

# ─── Handlers ───
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_user.id] = []
    ep = get_current_endpoint()
    await update.message.reply_text(
        f"🤖 Qwen AI Bot Online!\n\n"
        f"📌 Current: {ep['name']}\n\n"
        f"Commands:\n"
        f"/start — Show menu\n"
        f"/endpoint — Switch model\n"
        f"/clear — Reset chat\n"
        f"/status — Check status\n"
        f"/zip — Download history"
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_user.id] = []
    await update.message.reply_text("✅ Chat cleared!")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ep = get_current_endpoint()
    uptime = datetime.timedelta(seconds=int(time.time() - start_time))
    await update.message.reply_text(
        f"🟢 Bot Running\n\n"
        f"📌 Model: {ep['name']}\n"
        f"🔗 Endpoint: {ep['base_url']}\n"
        f"🕒 Uptime: {uptime}"
    )

async def cmd_endpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_endpoint_id, client
    args = context.args
    if not args:
        text = "📋 Models:\n\n"
        for idx, info in ENDPOINTS.items():
            marker = "✅" if idx == current_endpoint_id else "  "
            text += f"{marker} /endpoint {idx} → {info['name']}\n"
        text += "\nType /endpoint 1 or /endpoint 2"
        await update.message.reply_text(text)
        return
    
    new_id = args[0]
    if new_id not in ENDPOINTS:
        await update.message.reply_text("❌ Use /endpoint 1 or /endpoint 2")
        return
    if new_id == current_endpoint_id:
        await update.message.reply_text("✅ Already using that model!")
        return
    
    current_endpoint_id = new_id
    client = create_client()
    conversations[update.effective_user.id] = []
    await update.message.reply_text(f"🔄 Switched to {get_current_endpoint()['name']}\n✅ Chat cleared")

async def cmd_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in conversations or not conversations[user_id]:
        await update.message.reply_text("📭 No history yet!")
        return
    zip_path = Path(f"chat_{user_id}.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("chat.txt", json.dumps(conversations[user_id], ensure_ascii=False, indent=2))
    with open(zip_path, "rb") as f:
        await update.message.reply_document(f, filename=f"chat.zip")
    zip_path.unlink(missing_ok=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    if user_id not in conversations:
        conversations[user_id] = []
    conversations[user_id].append({"role": "user", "content": text})
    conversations[user_id] = conversations[user_id][-MAX_HISTORY:]
    
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    
    try:
        ep = get_current_endpoint()
        messages = [{"role": "system", "content": "You are Qwen, a helpful AI assistant."}] + conversations[user_id]
        response = await client.chat.completions.create(
            model=ep["model"], messages=messages, stream=True
        )
        full_reply, buffer, sent_msg = "", "", None
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                buffer += chunk.choices[0].delta.content
                if len(buffer) > 30 or chunk.choices[0].finish_reason:
                    full_reply += buffer
                    if not sent_msg:
                        sent_msg = await update.message.reply_text(full_reply)
                    else:
                        await sent_msg.edit_text(full_reply)
                    buffer = ""
        conversations[user_id].append({"role": "assistant", "content": full_reply})
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:150]}\nTry /endpoint to switch models")

# ─── MAIN ───
def main():
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("clear", cmd_clear))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("endpoint", cmd_endpoint))
        app.add_handler(CommandHandler("zip", cmd_zip))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        log(f"✅ Bot ONLINE — {get_current_endpoint()['name']}")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        log(f"FATAL — {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
