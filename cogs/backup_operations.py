import discord
from discord.ext import commands, tasks
import sqlite3
import os
import zipfile
import datetime
import aiohttp
import json
from datetime import datetime, timedelta
import asyncio
import tempfile
import shutil
import pyzipper
import traceback
import ssl

class BackupOperations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "db/backup.sqlite"
        self.api_url = "https://wosland.com/apidc/backup_api/backup_api.php"
        self.api_key = "serioyun_backup_api_key_2024"
        self.log_path = "log/backuplog.txt"
        os.makedirs("log", exist_ok=True)
        self.setup_database()
        self.automatic_backup_loop.start()

    def setup_database(self):
        os.makedirs("db", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backup_passwords (
                discord_id TEXT PRIMARY KEY,
                backup_password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()

    def cog_unload(self):
        self.automatic_backup_loop.cancel()

    @tasks.loop(hours=3)
    async def automatic_backup_loop(self):
        try:
            conn = sqlite3.connect("db/settings.sqlite")
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM admin WHERE is_initial = 1")
            global_admins = cursor.fetchall()
            conn.close()
        except:
            pass

    @automatic_backup_loop.before_loop
    async def before_automatic_backup(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(BackupOperations(bot))