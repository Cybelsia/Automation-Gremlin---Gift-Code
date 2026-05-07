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
from paths import *

class BearTrap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = database_path(BEAR_TRAP_DB, "beartime.sqlite")
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

    async def show_bear_trap_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🐻 Bear Trap",
            description=(
                "Bear Trap notification system is loaded.\n\n"
                "**Available Operations**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📋 **View Notifications**\n"
                "└ List notifications configured for this server\n\n"
                "🏠 **Main Menu**\n"
                "└ Return to settings\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.blue()
        )
        view = BearTrapMenuView(self)
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_notifications(self, interaction: discord.Interaction):
        self.cursor.execute("""
            SELECT id, channel_id, hour, minute, timezone, description, is_enabled
            FROM bear_notifications
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT 25
        """, (interaction.guild_id,))
        notifications = self.cursor.fetchall()
        if not notifications:
            await interaction.response.send_message("❌ No bear trap notifications found for this server.", ephemeral=True)
            return
        embed = discord.Embed(title="📋 Bear Trap Notifications", color=discord.Color.blue())
        for notification_id, channel_id, hour, minute, timezone, description, is_enabled in notifications:
            status = "Enabled" if is_enabled else "Disabled"
            embed.add_field(
                name=f"Notification #{notification_id}",
                value=f"Channel: <#{channel_id}>\nTime: `{hour:02d}:{minute:02d} {timezone}`\nStatus: `{status}`\nDescription: {description}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class BearTrapMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="View Notifications", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def view_notifications_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_notifications(interaction)

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(BearTrap(bot))