import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
import requests
from .alliance_member_operations import AllianceSelectView

VERSION_URL = "https://raw.githubusercontent.com/Reloisback/Whiteout-Survival-Discord-Bot/refs/heads/main/autoupdateinfo.txt"

class BotOperations(commands.Cog):
    def __init__(self, bot, conn):
        self.bot = bot
        self.conn = conn
        self.settings_db = sqlite3.connect('db/settings.sqlite', check_same_thread=False)
        self.settings_cursor = self.settings_db.cursor()
        self.alliance_db = sqlite3.connect('db/alliance.sqlite', check_same_thread=False)
        self.c_alliance = self.alliance_db.cursor()
        self.setup_database()

    def setup_database(self):
        try:
            self.settings_cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin (
                    id INTEGER PRIMARY KEY,
                    is_initial INTEGER DEFAULT 0
                )
            """)
            
            self.settings_cursor.execute("""
                CREATE TABLE IF NOT EXISTS adminserver (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin INTEGER NOT NULL,
                    alliances_id INTEGER NOT NULL,
                    FOREIGN KEY (admin) REFERENCES admin(id),
                    UNIQUE(admin, alliances_id)
                )
            """)
            
            self.settings_db.commit()
                
        except Exception as e:
            pass

    def __del__(self):
        try:
            self.settings_db.close()
            self.alliance_db.close()
        except:
            pass

    async def show_bot_operations_menu(self, interaction: discord.Interaction):
        try:
            embed = discord.Embed(
                title="🤖 Bot Operations",
                description=(
                    "Please choose an operation:\n\n"
                    "**Available Operations**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👥 **Admin Management**\n"
                    "└ Manage bot administrators\n\n"
                    "🔍 **Admin Permissions**\n"
                    "└ View and manage admin permissions\n\n"
                    "🔄 **Bot Updates**\n"
                    "└ Check and manage updates\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.blue()
            )
            
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Add Admin",
                emoji="➕",
                style=discord.ButtonStyle.success,
                custom_id="add_admin",
                row=1
            ))
            view.add_item(discord.ui.Button(
                label="Remove Admin",
                emoji="➖",
                style=discord.ButtonStyle.danger,
                custom_id="remove_admin",
                row=1
            ))
            view.add_item(discord.ui.Button(
                label="View Administrators",
                emoji="👥",
                style=discord.ButtonStyle.primary,
                custom_id="view_administrators",
                row=1
            ))
            view.add_item(discord.ui.Button(
                label="Assign Alliance to Admin",
                emoji="🔗",
                style=discord.ButtonStyle.success,
                custom_id="assign_alliance",
                row=2
            ))
            view.add_item(discord.ui.Button(
                label="Delete Admin Permissions",
                emoji="➖",
                style=discord.ButtonStyle.danger,
                custom_id="view_admin_permissions",
                row=2
            ))
            view.add_item(discord.ui.Button(
                label="Main Menu",
                emoji="🏠",
                style=discord.ButtonStyle.secondary,
                custom_id="main_menu",
                row=4
            ))

            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            if not any(error_code in str(e) for error_code in ["10062", "40060"]):
                print(f"Show bot operations menu error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while showing the menu.",
                    ephemeral=True
                )

    async def confirm_permission_removal(self, admin_id: int, alliance_id: int, confirm_interaction: discord.Interaction):
        try:
            self.settings_cursor.execute("""
                DELETE FROM adminserver 
                WHERE admin = ? AND alliances_id = ?
            """, (admin_id, alliance_id))
            self.settings_db.commit()
            return True
        except Exception as e:
            return False

    async def check_for_updates(self):
        try:
            response = requests.get(VERSION_URL)
            if response.status_code != 200:
                return None, None, [], []

            content = response.text.split('\n')
            documents = {}
            updates_needed = []
            update_notes = []

            doc_section = False
            update_section = False
            
            for line in content:
                line = line.strip()
                
                if line == "Documants;":
                    doc_section = True
                    continue
                elif line == "Updated Info;":
                    doc_section = False
                    update_section = True
                    continue
                elif doc_section and '=' in line:
                    file_name, version = [x.strip() for x in line.split('=')]
                    documents[file_name] = version
                elif update_section and line and line != "Updated Info;":
                    if line.startswith("- "):
                        update_notes.append(line)

            with sqlite3.connect('db/settings.sqlite') as conn:
                cursor = conn.cursor()
                
                for file_name, new_version in documents.items():
                    cursor.execute("SELECT version FROM versions WHERE file_name = ?", (file_name,))
                    current = cursor.fetchone()
                    current_version = current[0] if current else "No Version"
                    
                    if not current or current_version != new_version:
                        updates_needed.append({
                            'file': file_name,
                            'current': current_version,
                            'new': new_version
                        })

                cursor.execute("SELECT version FROM versions WHERE file_name = 'main.py'")
                result = cursor.fetchone()
                current_main_version = result[0] if result else "No Version"
                new_main_version = documents.get('main.py', "Unknown")

            return current_main_version, new_main_version, update_notes, updates_needed

        except Exception as e:
            print(f"Error checking for updates: {e}")
            return None, None, [], []

async def setup(bot):
    await bot.add_cog(BotOperations(bot, sqlite3.connect('db/settings.sqlite')))