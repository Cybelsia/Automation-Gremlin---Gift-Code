import discord
from discord.ext import commands
import sqlite3
from datetime import datetime
from .alliance_member_operations import AllianceSelectView

class Changes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn_settings = sqlite3.connect('db/settings.sqlite')
        self.c_settings = self.conn_settings.cursor()
        self.conn = sqlite3.connect('db/changes.sqlite')
        self.cursor = self.conn.cursor()
        self._create_tables()
        
        self.level_mapping = {
            31: "30-1", 32: "30-2", 33: "30-3", 34: "30-4",
            35: "FC 1", 36: "FC 1 - 1", 37: "FC 1 - 2", 38: "FC 1 - 3", 39: "FC 1 - 4",
        }

    def _create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS furnace_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fid INTEGER,
                old_value INTEGER,
                new_value INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    async def show_alliance_history_menu(self, interaction: discord.Interaction):
        try:
            embed = discord.Embed(
                title="📜 Alliance History Menu",
                description=(
                    "**Available Operations**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🔥 **Furnace Changes**\n"
                    "└ View furnace level changes\n\n"
                    "📝 **Nickname Changes**\n"
                    "└ View nickname history\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.blue()
            )
            
            view = AllianceHistoryView(self)
            await interaction.response.edit_message(embed=embed, view=view)
            
        except Exception as e:
            print(f"Show alliance history menu error: {e}")

class AllianceHistoryView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    async def _not_configured(self, interaction: discord.Interaction, operation: str):
        await interaction.response.send_message(f"❌ {operation} is not configured in this build.", ephemeral=True)

    @discord.ui.button(label="Furnace Changes", emoji="🔥", style=discord.ButtonStyle.primary, row=0)
    async def furnace_changes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._not_configured(interaction, "Furnace Changes")

    @discord.ui.button(label="Nickname Changes", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def nickname_changes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._not_configured(interaction, "Nickname Changes")

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Changes(bot))