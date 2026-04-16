import os
import sys
import asyncio
import signal
import sqlite3

import discord
from discord.ext import commands


def load_token() -> str:
    token = os.getenv("DISCORD_TOKEN")
    if token and token.strip():
        return token.strip()

    raise RuntimeError(
        "DISCORD_TOKEN is missing. Add it to your Railway variables."
    )


def ensure_folders():
    os.makedirs("cogs", exist_ok=True)
    os.makedirs("db", exist_ok=True)
    print("[INFO] Folders checked: cogs/, db/")


def setup_database():
    databases = {
        "alliance": "db/alliance.sqlite",
        "giftcode": "db/giftcode.sqlite",
        "changes": "db/changes.sqlite",
        "users": "db/users.sqlite",
        "settings": "db/settings.sqlite",
    }

    connections = {name: sqlite3.connect(path) for name, path in databases.items()}

    with connections["changes"] as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nickname_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fid INTEGER,
                old_nickname TEXT,
                new_nickname TEXT,
                change_date TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS furnace_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fid INTEGER,
                old_furnace_lv INTEGER,
                new_furnace_lv INTEGER,
                change_date TEXT
            )
        """)

    with connections["settings"] as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS botsettings (
                id INTEGER PRIMARY KEY,
                channelid INTEGER,
                giftcodestatus TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY,
                is_initial INTEGER
            )
        """)

    with connections["users"] as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                fid INTEGER PRIMARY KEY,
                nickname TEXT,
                furnace_lv INTEGER DEFAULT 0,
                kid INTEGER,
                stove_lv_content TEXT,
                alliance TEXT
            )
        """)

    with connections["giftcode"] as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_codes (
                giftcode TEXT PRIMARY KEY,
                date TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_giftcodes (
                fid INTEGER,
                giftcode TEXT,
                status TEXT,
                PRIMARY KEY (fid, giftcode),
                FOREIGN KEY (giftcode) REFERENCES gift_codes (giftcode)
            )
        """)

    with connections["alliance"] as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alliancesettings (
                alliance_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                interval INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alliance_list (
                alliance_id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)

    for conn in connections.values():
        conn.close()

    print("[INFO] Database tables checked")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class GremlinBot(commands.Bot):
    async def on_error(self, event_name, *args, **kwargs):
        error = sys.exc_info()[1]
        if isinstance(error, discord.NotFound) and getattr(error, "code", None) == 10062:
            return
        await super().on_error(event_name, *args, **kwargs)

    async def on_command_error(self, ctx, error):
        if isinstance(error, discord.NotFound) and getattr(error, "code", None) == 10062:
            return
        await super().on_command_error(ctx, error)


bot = GremlinBot(command_prefix="!", intents=intents)


COGS = [
    "cogs.control",
    "cogs.alliance",
    "cogs.alliance_member_operations",
    "cogs.bot_operations",
    "cogs.changes",
    "cogs.gift_operations",
    "cogs.id_channel",
    "cogs.logsystem",
    "cogs.w",
    "cogs.wel",
]


async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"[INFO] Loaded {cog}")
        except Exception as e:
            print(f"[WARN] Failed to load {cog}: {e}")


@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print("[INFO] Slash commands synced")
    except Exception as e:
        print(f"[WARN] Could not sync commands: {e}")

    print(f"[INFO] Logged in as {bot.user}")
    print("[INFO] Automation Gremlin is online")


async def start_bot():
    ensure_folders()
    setup_database()
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

        