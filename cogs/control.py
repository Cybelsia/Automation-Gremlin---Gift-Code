import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import hashlib
import time
import sqlite3
import asyncio
from datetime import datetime
from colorama import Fore, Style
import os
from aiohttp_socks import ProxyConnector

SECRET = 'tB87#kPtkxqOS2'

level_mapping = {
    31: "30-1", 32: "30-2", 33: "30-3", 34: "30-4",
    35: "FC 1", 36: "FC 1 - 1", 37: "FC 1 - 2", 38: "FC 1 - 3", 39: "FC 1 - 4",
}

class Control(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn_alliance = sqlite3.connect('db/alliance.sqlite')
        self.conn_users = sqlite3.connect('db/users.sqlite')
        self.conn_changes = sqlite3.connect('db/changes.sqlite')
        self.cursor_alliance = self.conn_alliance.cursor()
        self.cursor_users = self.conn_users.cursor()
        self.cursor_changes = self.conn_changes.cursor()
        
        self.conn_settings = sqlite3.connect('db/settings.sqlite')
        self.cursor_settings = self.conn_settings.cursor()
        self.db_lock = asyncio.Lock()
        self.control_queue = asyncio.Queue()
        self.control_lock = asyncio.Lock()
        self.current_control = None

    async def fetch_user_data(self, fid, proxy=None):
        return None

    @commands.Cog.listener()
    async def on_ready(self):
        if not hasattr(self, 'monitor_started'):
            self.monitor_started = True

async def setup(bot):
    await bot.add_cog(Control(bot))