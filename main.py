import os
import asyncio
import uuid
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from openai import OpenAI

# Налаштування логування
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================== Токени ==================
TELEGRAM_TOKEN = os.getenv("7881514807:AAH9DS4K3FPnqaQEWKIsgUJ5lsnjC41I1RU")
DEEPSEEK_API_KEY = os.getenv("sk-eb80ea6ba21b4789bd49dbd7eec2489c")
RAILWAY_PUBLIC_DOMAIN = os.getenv("worker-production-881b8.up.railway.app")

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

# ID адміністратора (замініть на ваш реальний user_id)
ADMIN_USER_ID = 259240310  # Замініть на ваш реальний user_id

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

# ================== Клавіатура ==================
menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Почати спілкування")],
        [KeyboardButton(text="Моя статистика")]
    ],
    resize_keyboard=True
)

# ================== Функції ==================
async def generate_response(user_id, user_message):
    logger.debug(f"Generating response for user_id={user_id}, message={user_message}")
    context = user_context.get(user_id, [])
    context.append({"role": "user", "content": user_message})
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": "You are Mila, a friendly bot."}] + context,
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
    # Адміністратор має необмежений доступ
    if user_id == ADMIN_USER_ID:
        logger.debug(f"User {user_id} is admin, bypassing limit")
        return True
    # Перевірка ліміту для інших користувачів
    count = user_limits.get(user_id, 0)
    logger.debug(f"User {user_id} has sent {count} messages")
    if count >= 15:
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

# ================== Реєстрація хендлерів ==================
dp.message.register(start_cmd, F.text.startswith("/start"))
dp.message.register(chat_handler)

# ================== Налаштування вебхука ==================
async def set_webhook(bot: Bot):
    webhook_url = f"https://{RAILWAY_PUBLIC_DOMAIN}/webhook/{TELEGRAM_TOKEN}"
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
            dispatcher=dp, bot=bot, secret_token=TELEGRAM_TOKEN
        )
        webhook_requests_handler.register(app, path=f"/webhook/{TELEGRAM_TOKEN}")
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