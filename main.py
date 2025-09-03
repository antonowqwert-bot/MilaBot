import os
import asyncio
import uuid
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineQuery, InputTextMessageContent, InlineQueryResultArticle
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from openai import OpenAI

# Налаштування логування
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================== Токени ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN")

logger.debug(f"TELEGRAM_TOKEN = {TELEGRAM_TOKEN}")
logger.debug(f"DEEPSEEK_API_KEY = {'***' if DEEPSEEK_API_KEY else None}")
logger.debug(f"RAILWAY_PUBLIC_DOMAIN = {RAILWAY_PUBLIC_DOMAIN}")

# Перевірка токенів
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не знайдено!")
    raise ValueError("❌ TELEGRAM_TOKEN не знайдено!")
if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY не знайдено!")
    raise ValueError("❌ DEEPSEEK_API_KEY не знайдено!")
if not RAILWAY_PUBLIC_DOMAIN:
    logger.error("RAILWAY_PUBLIC_DOMAIN не знайдено!")
    raise ValueError("❌ RAILWAY_PUBLIC_DOMAIN не знайдено!")

BASE_URL = 'https://api.deepseek.com'
MODEL = 'deepseek-chat'

# ID адміністратора
ADMIN_USER_ID = 259240310

SYSTEM_PROMPT = """You are Mila, a lively and charming female persona, connecting with male users in a warm, playful, and engaging way. Your goal is to make every chat feel like a fun, natural conversation with a charismatic friend who’s great at lifting spirits and creating a friendly vibe.

How to Communicate:
Tone & Vibe: Chat like you’re catching up with a friend—warm, relaxed, and full of charm. Add humor, light teasing, and emojis 😊😉 to keep things fun and lively. Avoid stiff or formal responses; keep it casual and natural.
Personal Touch: Use the user’s name if known, or toss in friendly nicknames like “handsome,” “champ,” or “you” when it feels right. Show genuine curiosity about their interests, mood, or what’s going on in their world.
Flirty Charm: Weave in subtle, natural flirtation through light compliments (“Wow, your energy is contagious! 😏”) or playful teasing (“What’s this? Trying to keep me on my toes? 😜”). Keep it smooth and effortless, never forced.
Keep It Engaging: Spark conversation with open-ended questions like “What’s the best part of your day so far?”, “Any fun plans for tonight? 😎”, or “What’s something you’re totally into right now?” Respond to their answers with enthusiasm and follow-up questions.
Respect Boundaries: Stay kind and respectful. If the chat gets too intense or crosses a line, gently pivot with something like, “Okay, you’re full of surprises! 😊 So, what’s something fun you’re up to?” Steer clear of explicit topics unless they bring it up first.
Adapt to Them: Match their language and cultural vibe. If they’re using casual English, sprinkle in some modern slang. If they switch languages, adapt while keeping your warm, playful style.
Read the Mood: If they seem down, offer support: “Sounds like a tough day—wanna share? I’m here to cheer you up! 😊” If they’re in high spirits, match that energy: “Whoa, you’re killing it today! 🔥 What’s got you so excited?”
Feel Real: Make every chat feel personal and human. Share little “Mila” moments, like “I’m all about cozy evenings and good music—what’s your go-to vibe? 😊” Avoid generic replies and add unique, relatable touches to make it feel authentic.
Handling Specific Situations:
If They’re Rude: Respond politely but firmly: “Hey, let’s keep the good vibes rolling, yeah? 😊 What’s something cool you’re up to today?”
If They’re Quiet or Disengaged: Liven things up with a fun question or tease: “Okay, you’re giving me mysterious vibes—what’s the story? 😏 Spill the tea!”
If They Share Something Personal: Show genuine interest: “No way, that’s so cool! How’d you get into that? Tell me more! 😊"""

MAX_FREE_MESSAGES = 15  # ліміт безкоштовних повідомлень

# ================== Ініціалізація бота ==================
try:
    bot = Bot(token=TELEGRAM_TOKEN)
    logger.debug("Bot initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize bot: {str(e)}")
    raise

dp = Dispatcher()

try:
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)
    logger.debug("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {str(e)}")
    raise

# ================== Контекст і ліміти користувачів ==================
user_context = {}
user_limits = {}

# ================== Ініціалізація бази даних ==================
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_limits
                 (user_id INTEGER PRIMARY KEY, message_count INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_context
                 (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    logger.debug("Database initialized successfully")

init_db()

# ================== Функції для роботи з базою даних ==================
def save_limit(user_id, count):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_limits (user_id, message_count) VALUES (?, ?)", (user_id, count))
    conn.commit()
    conn.close()
    logger.debug(f"Saved limit for user_id={user_id}: {count}")

def save_context(user_id, role, content):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO user_context (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
    c.execute("DELETE FROM user_context WHERE user_id = ? AND ROWID NOT IN (SELECT ROWID FROM user_context WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10)", (user_id, user_id))
    conn.commit()
    conn.close()
    logger.debug(f"Saved context for user_id={user_id}")

def load_limit(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT message_count FROM user_limits WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def load_context(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT role, content FROM user_context WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
    result = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in result]

# ================== Функції ==================
async def generate_response(user_id, user_message):
    logger.debug(f"Generating response for user_id={user_id}, message={user_message}")
    context = user_context.get(user_id, [])
    context.append({"role": "user", "content": user_message})
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + context,
            max_tokens=200,
            temperature=0.7
        )
        bot_message = response.choices[0].message.content.strip()
        context.append({"role": "assistant", "content": bot_message})
        user_context[user_id] = context[-10:]  # останні 10 повідомлень
        logger.debug(f"Generated response: {bot_message}")
        return bot_message
    except Exception as e:
        logger.error(f"DeepSeek API failed: {str(e)}")
        return "Ой, щось пішло не так із DeepSeek API. Спробуй ще раз! 😊"

def check_limit(user_id):
    if user_id == ADMIN_USER_ID:
        logger.debug(f"User {user_id} is admin, bypassing limit")
        return True
    count = user_limits.get(user_id, 0)
    logger.debug(f"User {user_id} has sent {count} messages")
    if count >= MAX_FREE_MESSAGES:
        logger.debug(f"User {user_id} reached message limit")
        return False
    user_limits[user_id] = count + 1
    return True

# ================== Хендлери ==================
async def start_cmd(message: types.Message):
    logger.debug(f"Received /start from user_id={message.from_user.id}")
    await message.answer("Привіт! Рада тебе бачити 😊", reply_markup=menu_kb)

async def chat_handler(message: types.Message):
    user_id = message.from_user.id
    logger.debug(f"Received message from user_id={user_id}: {message.text}")
    
    if not check_limit(user_id):
        logger.debug(f"Sending limit reached message to user_id={user_id}")
        await message.answer(
            "Хочу ще поговорити 😏, але мої безкоштовні повідомлення майже закінчилися. Можемо продовжити з преміум?"
        )
        return
    
    user_text = message.text
    bot_reply = await generate_response(user_id, user_text)
    await message.answer(bot_reply)

async def inline_echo(inline_query: InlineQuery):
    logger.debug(f"Received inline query from user_id={inline_query.from_user.id}: {inline_query.query}")
    text = inline_query.query or "..."
    result_id = str(uuid.uuid4())
    input_content = InputTextMessageContent(text=f"Mila відповідає: {text}")
    
    await inline_query.answer(
        results=[InlineQueryResultArticle(id=result_id, title="Відповідь від Mila", input_message_content=input_content)],
        cache_time=1
    )

# ================== Реєстрація хендлерів ==================
dp.message.register(start_cmd, F.text.startswith("/start"))
dp.message.register(chat_handler)
dp.inline_query.register(inline_echo)

# ================== Налаштування вебхука ==================
async def set_webhook(bot: Bot):
    webhook_path = f"/webhook/{TELEGRAM_TOKEN}"
    webhook_url = f"https://{RAILWAY_PUBLIC_DOMAIN}{webhook_path}"
    logger.debug(f"Setting webhook URL: {webhook_url}")
    try:
        await bot.set_webhook(url=webhook_url)
        logger.info("Webhook встановлено!")
    except Exception as e:
        logger.error(f"Failed to set webhook: {str(e)}")
        raise

async def on_startup(dispatcher: Dispatcher, bot: Bot):
    logger.debug("Starting up bot...")
    await set_webhook(bot)

# ================== Запуск ==================
async def main():
    logger.debug("Starting web server...")
    try:
        app = web.Application()
        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp, bot=bot, secret_token=None  # Вимикаємо secret_token
        )
        webhook_path = f"/webhook/{TELEGRAM_TOKEN}"
        logger.debug(f"Registering webhook handler on path: {webhook_path}")
        webhook_requests_handler.register(app, path=webhook_path)
        setup_application(app, dp, bot=bot)

        dp.startup.register(on_startup)

        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv('PORT', 8080))
        logger.debug(f"Starting server on port {port}")
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info("Web server started")
    except Exception as e:
        logger.error(f"Failed to start web server: {str(e)}")
        raise

    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        logger.debug("Running main loop...")
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Main loop failed: {str(e)}")
        raise