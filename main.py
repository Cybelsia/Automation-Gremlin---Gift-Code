import os
import sys
import asyncio
import signal

import discord
from discord.ext import commands

# Bot token handling
TOKEN_FILE = "bot_token.txt"

def load_token() -> str:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token_value = f.read().strip()
            if token_value:
                return token_value
    # Ask user once and save
    token_value = input("Enter your bot token: ").strip()
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token_value)
    return token_value

# Intents and bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class GremlinBot(commands.Bot):
    async def on_error(self, event_name, *args, **kwargs):
        error = sys.exc_info()[1]
        if isinstance(error, discord.NotFound) and getattr(error, "code", None) == 10062:
            return
        await super().on_error(event_name, *args, **kwargs)

bot = GremlinBot(command_prefix="!", intents=intents)

# Cog loader
COGS = [
    "cogs.permission_handler",
    "cogs.registration",
    "cogs.gift_operations",
]

async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"[INFO] Loaded {cog}")
        except Exception as e:
            print(f"[WARN] Failed to load {cog}: {e}")

# Events
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print("[INFO] Slash commands synced")
    except Exception as e:
        print(f"[WARN] Could not sync commands: {e}")
    print(f"[INFO] Logged in as {bot.user}")
    print("[INFO] Automation Gremlin — Gift Code Bot is online")

# Run / shutdown
async def start_bot():
    await load_cogs()
    await bot.start(load_token())

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop_event = asyncio.Event()

    def handle_signal(*_):
        print("[INFO] Shutdown signal received")
        loop.call_soon_threadsafe(stop_event.set)

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                pass
    else:
        signal.signal(signal.SIGINT, lambda s, f: handle_signal())

    async def runner():
        bot_task = asyncio.create_task(start_bot())
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {bot_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if not bot.is_closed():
            await bot.close()

    try:
        loop.run_until_complete(runner())
    finally:
        loop.close()

if __name__ == "__main__":
    run_bot()