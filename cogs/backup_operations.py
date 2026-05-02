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
import traceback
import ssl
from cogs.permissions import check_permission

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
        pass

    @automatic_backup_loop.before_loop
    async def before_automatic_backup(self):
        await self.bot.wait_until_ready()

    async def show_backup_menu(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ You don't have permission to use backup operations.", ephemeral=True)
            return

        embed = discord.Embed(
            title="💾 Backup System",
            description=(
                "Backup system is loaded.\n\n"
                "**Available Operations**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🏠 **Main Menu**\n"
                "└ Return to settings\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.blue()
        )
        view = BackupMenuView(self)
        await interaction.response.edit_message(embed=embed, view=view)


class BackupMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(BackupOperations(bot))