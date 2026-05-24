from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from app.lib.constants import CHANNEL_ID, BOT_TOKEN, TG_PROXY
from app.lib.db import get_connection

MAX_MESSAGE_LENGTH = 4048

async def send_telegram_message(message: str):
    session = AiohttpSession(proxy=TG_PROXY)
    bot = Bot(token=BOT_TOKEN, session=session)
    connection = get_connection()
    cursor = connection.cursor()

    for chunk in split_telegram_markdown(message):
        try:
            message = await bot.send_message(
                chat_id=CHANNEL_ID,
                parse_mode="Markdown",
                text=chunk
            )
            cursor.execute("INSERT INTO sent_messages (message_id, message_text) VALUES (?, ?)", (message.message_id, chunk))
        except Exception as e:
            print(f"Failed to send message chunk: {e}")
    
    connection.commit()
    connection.close()
    await bot.session.close()


async def cleanup_telegram_messages():
    session = AiohttpSession(proxy=TG_PROXY)
    bot = Bot(token=BOT_TOKEN, session=session)
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT message_id FROM sent_messages WHERE deleted_at IS NULL")
    messages = cursor.fetchall()
    for message in messages:
        try:
            await bot.delete_message(chat_id=CHANNEL_ID, message_id=message["message_id"])
        except Exception as e:
            print(f"Failed to delete message {message['message_id']}: {e}")
        finally:
            cursor.execute("UPDATE sent_messages SET deleted_at = CURRENT_TIMESTAMP WHERE message_id = ?", (message["message_id"],))
    connection.commit()
    connection.close()
    await bot.session.close()


def get_last_sent_message_age_in_seconds():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT MAX(created_at) AS last_sent FROM sent_messages")
    result = cursor.fetchone()
    connection.close()
    if result and result["last_sent"]:
        from datetime import datetime
        last_sent = datetime.strptime(result["last_sent"], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - last_sent).total_seconds()
    return None


def split_telegram_markdown(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    if not text:
        return []

    blocks = _split_markdown_to_blocks(text)
    chunks: list[str] = []
    current = ""

    def push_current():
        nonlocal current

        chunk = current.strip()
        if chunk:
            chunks.append(chunk)

        current = ""

    for block in blocks:
        block = block.strip("\n")

        if not block:
            continue

        # Если блок сам больше лимита, режем его отдельно
        if len(block) > limit:
            push_current()
            chunks.extend(_split_large_markdown_block(block, limit))
            continue

        candidate = block if not current else current + "\n\n" + block

        if len(candidate) <= limit:
            current = candidate
        else:
            push_current()
            current = block

    push_current()

    return chunks


def _split_markdown_to_blocks(text: str) -> list[str]:
    """
    Делит Markdown на логические блоки:
    - обычные абзацы
    - fenced code blocks ```...```
    """
    blocks: list[str] = []
    current: list[str] = []
    in_code_block = False

    lines = text.splitlines()

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            current.append(line)
            in_code_block = not in_code_block

            if not in_code_block:
                blocks.append("\n".join(current))
                current = []

            continue

        if in_code_block:
            current.append(line)
            continue

        if stripped == "":
            if current:
                blocks.append("\n".join(current))
                current = []
            continue

        current.append(line)

    if current:
        blocks.append("\n".join(current))

    return blocks


def _split_large_markdown_block(block: str, limit: int) -> list[str]:
    """
    Режет слишком большой блок.
    Сначала по строкам, потом по словам.
    Важно: если внутри одной огромной строки есть незакрытая Markdown-разметка,
    её всё равно можно разорвать. Для 100% корректности нужен Markdown parser.
    """
    chunks: list[str] = []
    current = ""

    def push_current():
        nonlocal current

        chunk = current.strip()
        if chunk:
            chunks.append(chunk)

        current = ""

    for line in block.splitlines():
        if len(line) > limit:
            push_current()
            chunks.extend(_split_long_line_by_words(line, limit))
            continue

        candidate = line if not current else current + "\n" + line

        if len(candidate) <= limit:
            current = candidate
        else:
            push_current()
            current = line

    push_current()

    return chunks


def _split_long_line_by_words(line: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""

    for word in line.split(" "):
        if not word:
            continue

        if len(word) > limit:
            if current.strip():
                chunks.append(current.strip())
                current = ""

            for i in range(0, len(word), limit):
                chunk = word[i:i + limit].strip()
                if chunk:
                    chunks.append(chunk)

            continue

        candidate = word if not current else current + " " + word

        if len(candidate) <= limit:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            current = word

    if current.strip():
        chunks.append(current.strip())

    return chunks