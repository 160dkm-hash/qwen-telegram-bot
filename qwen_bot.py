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

# ─── Load config ───
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "any_string")
MAX_HISTORY = int(os.getenv("MAX_HISTORY_LENGTH", 10))

# ─── Available Endpoints ───
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

# ─── Global Current Endpoint ───
current_endpoint_id = "2"  # Default: 27B model
def get_current_endpoint():
    return ENDPOINTS[current_endpoint_id]

if not BOT_TOKEN:
    print("❌ Missing TELEGRAM_BOT_TOKEN! Set it in Render Environment Variables")
    sys.exit(1)

# ─── Qwen Client ───
def create_client():
    ep = get_current_endpoint()
    return AsyncOpenAI(
        api_key=QWEN_API_KEY,
        base_url=ep["base_url"]
    )

client = create_client()

# ─── Conversation storage ───
conversations = {}
start_time = time.time()

# ─── Logging ───
def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    print(line.strip())

# ─── Handlers ───
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_user.id] = []
    ep = get_current_endpoint()
    await update.message.reply_text(
        f"🤖 Hello! I'm your Qwen AI bot.\n\n"
        f"📌 Current: {ep['name']}\n\n"
        f"📋 Commands:\n"
        f"/start — Show this menu\n"
        f"/endpoint — Switch model\n"
        f"/clear — Reset chat\n"
        f"/status — Check bot status\n"
        f"/zip — Download chat history"
    )
    log(f"User {update.effective_user.id} — /start")

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_user.id] = []
    await update.message.reply_text("✅ Chat history cleared!")
    log(f"User {update.effective_user.id} — /clear")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ep = get_current_endpoint()
    uptime = datetime.timedelta(seconds=int(time.time() - start_time))
    await update.message.reply_text(
        f"🟢 Bot is Running!\n\n"
        f"📌 Model: {ep['name']}\n"
        f"🔗 Endpoint: {ep['base_url']}\n"
        f"🕒 Uptime: {uptime}\n"
        f"💬 History limit: {MAX_HISTORY} messages"
    )

async def cmd_endpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_endpoint_id, client
    args = context.args
    current = get_current_endpoint()
    
    if not args:
        list_text = "📋 Available Models:\n\n"
        for idx, info in ENDPOINTS.items():
            marker = "✅" if idx == current_endpoint_id else "  "
            list_text += f"{marker} /endpoint {idx} → {info['name']}\n"
        list_text += "\nType /endpoint 1 or /endpoint 2 to switch!"
        await update.message.reply_text(list_text)
        return
    
    new_id = args[0]
    if new_id not in ENDPOINTS:
        await update.message.reply_text("❌ Invalid! Use /endpoint 1 or /endpoint 2")
        return
    
    if new_id == current_endpoint_id:
        await update.message.reply_text(f"✅ Already using {current['name']}!")
        return
    
    current_endpoint_id = new_id
    client = create_client()
    new_ep = get_current_endpoint()
    conversations[update.effective_user.id] = []
    
    await update.message.reply_text(
        f"🔄 Switched!\n\n"
        f"✅ Now: {new_ep['name']}\n"
        f"💬 Chat history cleared."
    )
    log(f"User {update.effective_user.id} → endpoint {new_id}")

async def cmd_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in conversations or not conversations[user_id]:
        await update.message.reply_text("📭 No chat history yet!")
        return

    zip_path = Path(f"chat_{user_id}.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        history = json.dumps(conversations[user_id], ensure_ascii=False, indent=2)
        zf.writestr("conversation.txt", history)

    with open(zip_path, "rb") as f:
        await update.message.reply_document(f, filename=f"chat_{user_id}.zip")

    zip_path.unlink(missing_ok=True)
    log(f"User {user_id} — downloaded history")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text or ""

    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({"role": "user", "content": user_text})
    conversations[user_id] = conversations[user_id][-MAX_HISTORY:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        ep = get_current_endpoint()
        messages = [
            {"role": "system", "content": "You are Qwen, a helpful, friendly AI assistant."}
        ] + conversations[user_id]

        response = await client.chat.completions.create(
            model=ep["model"],
            messages=messages,
            stream=True
        )

        sent_msg = None
        full_reply = ""
        buffer = ""

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
        log(f"User {user_id} — msg sent ({len(full_reply)} chars)")

    except Exception as e:
        err_msg = (
            f"❌ Error: {str(e)[:150]}\n\n"
            f"💡 Try switching models with /endpoint\n"
            f"Or check if the endpoint server is online"
        )
        await update.message.reply_text(err_msg)
        log(f"ERROR — {e}")

# ─── Run Bot ───
def main():
    try:
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", cmd_start))
        application.add_handler(CommandHandler("clear", cmd_clear))
        application.add_handler(CommandHandler("status", cmd_status))
        application.add_handler(CommandHandler("endpoint", cmd_endpoint))
        application.add_handler(CommandHandler("zip", cmd_zip))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        log(f"✅ Bot ONLINE | Default: {get_current_endpoint()['name']}")
        application.run_polling()
    except Exception as e:
        log(f"FATAL ERROR — {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
