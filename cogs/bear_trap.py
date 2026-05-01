import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta
import pytz
import os
import asyncio
import json
import urllib.parse
import traceback

class BearTrap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = 'db/beartime.sqlite'
        os.makedirs('db', exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS bear_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                timezone TEXT NOT NULL,
                description TEXT NOT NULL,
                notification_type INTEGER NOT NULL,
                mention_type TEXT NOT NULL,
                repeat_enabled INTEGER NOT NULL DEFAULT 0,
                repeat_minutes INTEGER DEFAULT 0,
                is_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER NOT NULL,
                last_notification TIMESTAMP,
                next_notification TIMESTAMP
            )
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id INTEGER NOT NULL,
                notification_time INTEGER NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (notification_id) REFERENCES bear_notifications(id) ON DELETE CASCADE
            )
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS bear_notification_embeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id INTEGER NOT NULL,
                title TEXT,
                description TEXT,
                color INTEGER,
                image_url TEXT,
                thumbnail_url TEXT,
                footer TEXT,
                author TEXT,
                mention_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (notification_id) REFERENCES bear_notifications(id) ON DELETE CASCADE
            )
        """)
        
        self.conn.commit()

    async def cog_load(self):
        pass

    async def cog_unload(self):
        pass

async def setup(bot):
    await bot.add_cog(BearTrap(bot))