import os
import asyncio
import uuid
import logging
import json
import boto3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineQuery, InputTextMessageContent, InlineQueryResultArticle
from openai import OpenAI

# Налаштування логування
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================== Токени ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

logger.debug(f"TELEGRAM_TOKEN = {TELEGRAM_TOKEN}")
logger.debug(f"DEEPSEEK_API_KEY = {'***' if DEEPSEEK_API_KEY else None}")

# Перевірка токенів
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не знайдено!")
    raise ValueError("❌ TELEGRAM_TOKEN не знайдено!")
if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY не знайдено!")
    raise ValueError("❌ DEEPSEEK_API_KEY не знайдено!")

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

# ================== Ініціалізація DynamoDB ==================
dynamodb = boto3.resource('dynamodb')
limits_table = dynamodb.Table('UserLimits')
context_table = dynamodb.Table('UserContext')

def init_db():
    try:
        dynamodb.create_table(
            TableName='UserLimits',
            KeySchema=[{'AttributeName': 'user_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'user_id', 'AttributeType': 'N'}],
            BillingMode='PAY_PER_REQUEST'
        )
        dynamodb.create_table(
            TableName='UserContext',
            KeySchema=[{'AttributeName': 'user_id', 'KeyType': 'HASH'}, {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[
                {'AttributeName': 'user_id', 'AttributeType': 'N'},
                {'AttributeName': 'timestamp', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        logger.debug("DynamoDB tables initialized successfully")
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        logger.debug("DynamoDB tables already exist")

init_db()

# ================== Функції для роботи з DynamoDB ==================
def save_limit(user_id, count):
    limits_table.put_item(Item={'user_id': user_id, 'message_count': count})
    logger.debug(f"Saved limit for user_id={user_id}: {count}")

def save_context(user_id, role, content):
    timestamp = datetime.utcnow().isoformat()
    context_table.put_item(Item={
        'user_id': user_id,
        'role': role,
        'content': content,
        'timestamp': timestamp
    })
    # Видаляємо старі записи, залишаючи останні 10
    response = context_table.query(
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id},
        ProjectionExpression='timestamp',
        ScanIndexForward=False,
        Limit=10
    )
    items = response.get('Items', [])
    if len(items) == 10:
        old_items = context_table.query(
            KeyConditionExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id},
            ScanIndexForward=False,
            Limit=100
        ).get('Items', [])
        for item in old_items[10:]:
            context_table.delete_item(Key={'user_id': user_id, 'timestamp': item['timestamp']})
    logger.debug(f"Saved context for user_id={user_id}")

def load_limit(user_id):
    try:
        response = limits_table.get_item(Key={'user_id': user_id})
        return response.get('Item', {}).get('message_count', 0)
    except Exception as e:
        logger.error(f"Failed to load limit: {str(e)}")
        return 0

def load_context(user_id):
    try:
        response = context_table.query(
            KeyConditionExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id},
            ScanIndexForward=False,
            Limit=10
        )
        return [{'role': item['role'], 'content': item['content']} for item in response.get('Items', [])]
    except Exception as e:
        logger.error(f"Failed to load context: {str(e)}")
        return []

# ================== Функції ==================
async def generate_response(user_id, user_message):
    logger.debug(f"Generating response for user_id={user_id}, message={user_message}")
    context = load_context(user_id)
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
        save_context(user_id, "user", user_message)
        save_context(user_id, "assistant", bot_message)
        logger.debug(f"Generated response: {bot_message}")
        return bot_message
    except Exception as e:
        logger.error(f"DeepSeek API failed: {str(e)}")
        return "Ой, щось пішло не так із DeepSeek API. Спробуй ще раз! 😊"

def check_limit(user_id):
    if user_id == ADMIN_USER_ID:
        logger.debug(f"User {user_id} is admin, bypassing limit")
        return True
    count = load_limit(user_id)
    logger.debug(f"User {user_id} has sent {count} messages")
    if count >= MAX_FREE_MESSAGES:
        logger.debug(f"User {user_id} reached message limit")
        return False
    count += 1
    save_limit(user_id, count)
    return True

# ================== Хендлери ==================
async def start_cmd(message: types.Message):
    logger.debug(f"Received /start from user_id={message.from_user.id}")
    await message.answer("Привіт! Рада тебе бачити 😊")

async def stats_cmd(message: types.Message):
    user_id = message.from_user.id
    count = load_limit(user_id)
    await message.answer(f"Ти надіслав {count} із {MAX_FREE_MESSAGES} безкоштовних повідомлень. 😊")

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
dp.message.register(stats_cmd, F.text.startswith("/stats"))
dp.message.register(chat_handler)
dp.inline_query.register(inline_echo)

# ================== Обробник Lambda ==================
async def lambda_handler(event, context):
    try:
        update = json.loads(event['body'])
        await dp.feed_raw_update(bot, update)
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}