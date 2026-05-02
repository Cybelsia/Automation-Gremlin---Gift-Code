import discord
from discord import app_commands
from discord.ext import commands
import sqlite3  
import asyncio
from datetime import datetime

class Alliance(commands.Cog):
    def __init__(self, bot, conn):
        self.bot = bot
        self.conn = conn
        self.c = self.conn.cursor()
        
        self.conn_users = sqlite3.connect('db/users.sqlite')
        self.c_users = self.conn_users.cursor()
        
        self.conn_settings = sqlite3.connect('db/settings.sqlite')
        self.c_settings = self.conn_settings.cursor()
        
        self.conn_giftcode = sqlite3.connect('db/giftcode.sqlite')
        self.c_giftcode = self.conn_giftcode.cursor()

        self._create_table()
        self._check_and_add_column()

    def _create_table(self):
        self.c.execute("""
            CREATE TABLE IF NOT EXISTS alliance_list (
                alliance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                discord_server_id INTEGER
            )
        """)
        self.conn.commit()

    def _check_and_add_column(self):
        self.c.execute("PRAGMA table_info(alliance_list)")
        columns = [info[1] for info in self.c.fetchall()]
        if "discord_server_id" not in columns:
            self.c.execute("ALTER TABLE alliance_list ADD COLUMN discord_server_id INTEGER")
            self.conn.commit()

    @app_commands.command(name="settings", description="Open settings menu.")
    async def settings(self, interaction: discord.Interaction):
        try:
            self.c_settings.execute("SELECT COUNT(*) FROM admin")
            admin_count = self.c_settings.fetchone()[0]

            user_id = interaction.user.id

            if admin_count == 0:
                self.c_settings.execute("""
                    INSERT INTO admin (id, is_initial) 
                    VALUES (?, 1)
                """, (user_id,))
                self.conn_settings.commit()

            embed = discord.Embed(
                title="⚙️ Settings Menu",
                description="Please select a category.",
                color=discord.Color.blue()
            )
            
            view = SettingsMenuView(self)
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            print(f"Settings command error: {e}")

    async def show_main_menu(self, interaction: discord.Interaction):
        try:
            embed = discord.Embed(
                title="⚙️ Settings Menu",
                description="Please select a category.",
                color=discord.Color.blue()
            )
            
            view = SettingsMenuView(self)
            await interaction.response.edit_message(embed=embed, view=view)
                
        except Exception as e:
            pass

    async def show_alliance_operations_menu(self, interaction: discord.Interaction):
        try:
            embed = discord.Embed(
                title="🏰 Alliance Operations",
                description=(
                    "Please choose an alliance operation:\n\n"
                    "**Available Operations**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "📋 **View Alliances**\n"
                    "└ List registered alliances\n\n"
                    "🏠 **Main Menu**\n"
                    "└ Return to settings\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.blue()
            )
            view = AllianceOperationsView(self)
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while showing alliance operations.", ephemeral=True)

    async def show_alliances(self, interaction: discord.Interaction):
        try:
            self.c.execute("SELECT alliance_id, name, discord_server_id FROM alliance_list ORDER BY name")
            alliances = self.c.fetchall()
            if not alliances:
                await interaction.response.send_message("❌ No alliances found.", ephemeral=True)
                return

            embed = discord.Embed(title="📋 Registered Alliances", color=discord.Color.blue())
            for alliance_id, name, discord_server_id in alliances[:25]:
                embed.add_field(
                    name=f"{name} (ID: {alliance_id})",
                    value=f"Server ID: `{discord_server_id or 'Not set'}`",
                    inline=False
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ An error occurred while loading alliances.", ephemeral=True)


class SettingsMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    async def _missing_cog(self, interaction: discord.Interaction, name: str):
        await interaction.response.send_message(f"❌ {name} module not found.", ephemeral=True)

    @discord.ui.button(label="Alliance Operations", emoji="🏰", style=discord.ButtonStyle.primary, row=0)
    async def alliance_operations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_operations_menu(interaction)

    @discord.ui.button(label="Alliance Member Operations", emoji="👥", style=discord.ButtonStyle.primary, row=0)
    async def alliance_member_operations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog.bot.get_cog("AllianceMemberOperations")
        if cog:
            await cog.handle_member_operations(interaction)
        else:
            await self._missing_cog(interaction, "Alliance Member Operations")

    @discord.ui.button(label="Gift Code Operations", emoji="🎁", style=discord.ButtonStyle.primary, row=1)
    async def gift_code_operations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog.bot.get_cog("GiftOperations")
        if cog:
            await cog.show_gift_menu(interaction)
        else:
            await self._missing_cog(interaction, "Gift Code Operations")

    @discord.ui.button(label="Bot Operations", emoji="🤖", style=discord.ButtonStyle.primary, row=1)
    async def bot_operations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog.bot.get_cog("BotOperations")
        if cog:
            await cog.show_bot_operations_menu(interaction)
        else:
            await self._missing_cog(interaction, "Bot Operations")

    @discord.ui.button(label="Other Features", emoji="🔧", style=discord.ButtonStyle.secondary, row=2)
    async def other_features_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog.bot.get_cog("OtherFeatures")
        if cog:
            await cog.show_other_features_menu(interaction)
        else:
            await self._missing_cog(interaction, "Other Features")

    @discord.ui.button(label="Support", emoji="🎯", style=discord.ButtonStyle.secondary, row=2)
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog.bot.get_cog("SupportOperations")
        if cog:
            await cog.show_support_menu(interaction)
        else:
            await self._missing_cog(interaction, "Support")

    @discord.ui.button(label="Log System", emoji="📋", style=discord.ButtonStyle.secondary, row=3)
    async def log_system_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog.bot.get_cog("LogSystem")
        if cog:
            await cog.show_log_system_menu(interaction)
        else:
            await self._missing_cog(interaction, "Log System")


class AllianceOperationsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="View Alliances", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def view_alliances_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliances(interaction)

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_main_menu(interaction)

class PaginatedChannelView(discord.ui.View):
    def __init__(self, channels, original_callback):
        super().__init__(timeout=300)
        self.channels = channels
        self.original_callback = original_callback

async def setup(bot):
    conn = sqlite3.connect('db/alliance.sqlite')
    await bot.add_cog(Alliance(bot, conn))