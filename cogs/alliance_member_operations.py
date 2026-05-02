import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import aiohttp
import hashlib
import time
import asyncio
from typing import List
from datetime import datetime
import os
import ssl

SECRET = 'tB87#kPtkxqOS2'

class PaginationView(discord.ui.View):
    def __init__(self, chunks: List[discord.Embed], author_id: int):
        super().__init__(timeout=180.0)
        self.chunks = chunks
        self.current_page = 0
        self.message = None
        self.author_id = author_id
        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return False
        return True

    def update_buttons(self):
        pass

class AllianceMemberOperations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn_alliance = sqlite3.connect('db/alliance.sqlite')
        self.c_alliance = self.conn_alliance.cursor()
        
        self.conn_users = sqlite3.connect('db/users.sqlite')
        self.c_users = self.conn_users.cursor()
        
        self.level_mapping = {
            31: "30-1", 32: "30-2", 33: "30-3", 34: "30-4",
            35: "FC 1", 36: "FC 1 - 1", 37: "FC 1 - 2", 38: "FC 1 - 3", 39: "FC 1 - 4",
        }

    async def handle_member_operations(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="👥 Alliance Member Operations",
            description=(
                "Please select an operation from below.\n\n"
                "**Available Operations**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📋 **Select Alliance**\n"
                "└ Choose from alliances available to you\n\n"
                "🏠 **Main Menu**\n"
                "└ Return to settings\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.blue()
        )
        
        view = MemberOperationsView(self)
        await interaction.response.edit_message(embed=embed, view=view)

    async def get_admin_alliances(self, user_id: int, guild_id: int):
        return [], [], False

class AllianceSelectView(discord.ui.View):
    def __init__(self, alliances_with_counts, cog=None, page=0):
        super().__init__(timeout=180)
        self.alliances = alliances_with_counts
        self.cog = cog
        self.page = page
        self.current_select = None
        self.callback = None


class MemberOperationsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Select Alliance", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def select_alliance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliances, _, _ = await self.cog.get_admin_alliances(interaction.user.id, interaction.guild_id)
        if not alliances:
            await interaction.response.send_message("❌ No alliances available for this operation.", ephemeral=True)
            return
        await interaction.response.send_message("Alliance selection is not configured for this operation yet.", ephemeral=True)

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AllianceMemberOperations(bot))