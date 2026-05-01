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
            
            view = discord.ui.View()
            await interaction.response.edit_message(embed=embed, view=view)
            
        except Exception as e:
            print(f"Show alliance history menu error: {e}")

async def setup(bot):
    await bot.add_cog(Changes(bot))