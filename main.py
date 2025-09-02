import os
import asyncio
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineQuery, InputTextMessageContent, InlineQueryResultArticle
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from openai import OpenAI

# ================== Перевірка токенів ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не знайдено. Перевір Environment Variables на Railway!")

if not DEEPSEEK_API_KEY:
    raise ValueError("❌ DEEPSEEK_API_KEY не знайдено. Перевір Environment Variables на Railway!")

BASE_URL = 'https://api.deepseek.com'
MODEL = 'deepseek-chat'

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
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

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
    context = user_context.get(user_id, [])
    context.append({"role": "user", "content": user_message})
    
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + context,
        max_tokens=200,
        temperature=0.7
    )
    
    bot_message = response.choices[0].message.content.strip()
    context.append({"role": "assistant", "content": bot_message})
    user_context[user_id] = context[-10:]  # останні 10 повідомлень
    
    return bot_message

def check_limit(user_id):
    count = user_limits.get(user_id, 0)
    if count >= MAX_FREE_MESSAGES:
        return False
    user_limits[user_id] = count + 1
    return True

# ================== Хендлери ==================
async def start_cmd(message: types.Message):
    await message.answer("Привіт! Рада тебе бачити 😊", reply_markup=menu_kb)

async def chat_handler(message: types.Message):
    user_id = message.from_user.id
    
    if not check_limit(user_id):
        await message.answer(
            "Хочу ще поговорити 😏, але мої безкоштовні повідомлення майже закінчилися. Можемо продовжити з преміум?"
        )
        return
    
    user_text = message.text
    bot_reply = await generate_response(user_id, user_text)
    await message.answer(bot_reply)

async def inline_echo(inline_query: InlineQuery):
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
    webhook_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/webhook/{TELEGRAM_TOKEN}"
    await bot.set_webhook(url=webhook_url)
    print("Webhook встановлено!")

async def on_startup(dispatcher: Dispatcher, bot: Bot):
    await set_webhook(bot)

# ================== Запуск ==================
async def main():
    # Налаштування вебсервера
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=TELEGRAM_TOKEN
    )
    webhook_requests_handler.register(app, path=f"/webhook/{TELEGRAM_TOKEN}")
    setup_application(app, dp, bot=bot)

    # Реєстрація хендлера для запуску
    dp.startup.register(on_startup)

    # Запуск вебсервера
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()

    # Чекаємо завершення
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())