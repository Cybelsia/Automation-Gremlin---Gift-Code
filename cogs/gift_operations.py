import discord
from discord.ext import commands
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import hashlib
import json
from datetime import datetime
import sqlite3
from discord.ext import tasks
import asyncio
import re
from .alliance_member_operations import AllianceSelectView
from .alliance import PaginatedChannelView
import os
import traceback
from .gift_operationsapi import GiftCodeAPI

class GiftOperations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if hasattr(bot, 'conn'):
            self.conn = bot.conn
            self.cursor = self.conn.cursor()
        else:
            self.conn = sqlite3.connect('db/giftcode.sqlite')
            self.cursor = self.conn.cursor()
            
        self.api = GiftCodeAPI(bot)
            
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS giftcodecontrol (
                alliance_id INTEGER PRIMARY KEY,
                status INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()
        
        self.settings_conn = sqlite3.connect('db/settings.sqlite')
        self.settings_cursor = self.settings_conn.cursor()
        
        self.alliance_conn = sqlite3.connect('db/alliance.sqlite')
        self.alliance_cursor = self.alliance_conn.cursor()
        
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS giftcode_channel (
                alliance_id INTEGER,
                channel_id INTEGER,
                PRIMARY KEY (alliance_id)
            )
        """)
        self.conn.commit()
        
        self.wos_player_info_url = "https://wos-giftcode-api.centurygame.com/api/player"
        self.wos_giftcode_url = "https://wos-giftcode-api.centurygame.com/api/gift_code"
        self.wos_giftcode_redemption_url = "https://wos-giftcode.centurygame.com"
        self.wos_encrypt_key = "tB87#kPtkxqOS2"
        
        self.retry_config = Retry(
            total=20,
            backoff_factor=1,
            status_forcelist=[429],
            allowed_methods=["POST"]
        )

        self.log_directory = 'log'
        if not os.path.exists(self.log_directory):
            os.makedirs(self.log_directory)

    async def show_gift_menu(self, interaction: discord.Interaction):
        gift_menu_embed = discord.Embed(
            title="🎁 Gift Code Operations",
            description=(
                "Please select an operation:\n\n"
                "**Available Operations**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🎫 **Create Gift Code**\n"
                "└ Generate new gift codes\n\n"
                "📋 **List Gift Codes**\n"
                "└ View all active codes\n\n"
                "⚙️ **Auto Gift Settings**\n"
                "└ Configure automatic gift code usage\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.gold()
        )
        
        view = GiftMenuView(self)
        await interaction.response.edit_message(embed=gift_menu_embed, view=view)


class GiftMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    async def _not_configured(self, interaction: discord.Interaction, operation: str):
        await interaction.response.send_message(f"❌ {operation} is not configured in this build.", ephemeral=True)

    @discord.ui.button(label="Create Gift Code", emoji="🎫", style=discord.ButtonStyle.primary, row=0)
    async def create_gift_code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._not_configured(interaction, "Create Gift Code")

    @discord.ui.button(label="List Gift Codes", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def list_gift_codes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.cursor.execute("SELECT giftcode, date FROM gift_codes ORDER BY date DESC LIMIT 25")
            codes = self.cog.cursor.fetchall()
            if not codes:
                await interaction.response.send_message("❌ No gift codes found.", ephemeral=True)
                return
            embed = discord.Embed(title="📋 Gift Codes", color=discord.Color.gold())
            for giftcode, date in codes:
                embed.add_field(name=giftcode, value=f"Date: `{date or 'Unknown'}`", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ An error occurred while listing gift codes.", ephemeral=True)

    @discord.ui.button(label="Auto Gift Settings", emoji="⚙️", style=discord.ButtonStyle.primary, row=1)
    async def auto_gift_settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._not_configured(interaction, "Auto Gift Settings")

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(GiftOperations(bot))