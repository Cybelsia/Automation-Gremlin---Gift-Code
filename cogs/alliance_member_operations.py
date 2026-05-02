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
                "➕ **Add Alliance Member**\n"
                "└ Add a member to an alliance\n\n"
                "� **View Alliance Members**\n"
                "└ View members in an alliance\n\n"
                "�📋 **Select Alliance**\n"
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
        self.c_alliance.execute("PRAGMA table_info(alliance_list)")
        columns = [column[1] for column in self.c_alliance.fetchall()]
        has_discord_server_id = "discord_server_id" in columns

        settings_conn = sqlite3.connect('db/settings.sqlite')
        settings_cursor = settings_conn.cursor()

        try:
            settings_cursor.execute("SELECT is_initial FROM admin WHERE id = ?", (user_id,))
            admin_result = settings_cursor.fetchone()
            is_global_admin = bool(admin_result and admin_result[0] == 1)

            if is_global_admin:
                if has_discord_server_id:
                    self.c_alliance.execute("""
                        SELECT alliance_id, name
                        FROM alliance_list
                        WHERE discord_server_id IS NULL OR discord_server_id = ?
                        ORDER BY name
                    """, (guild_id,))
                else:
                    self.c_alliance.execute("SELECT alliance_id, name FROM alliance_list ORDER BY name")
                alliances = self.c_alliance.fetchall()
            else:
                settings_cursor.execute("""
                    SELECT alliances_id
                    FROM adminserver
                    WHERE admin = ?
                """, (user_id,))
                alliance_ids = [row[0] for row in settings_cursor.fetchall()]
                if not alliance_ids:
                    return [], [], False

                placeholders = ",".join("?" for _ in alliance_ids)
                if has_discord_server_id:
                    self.c_alliance.execute(f"""
                        SELECT alliance_id, name
                        FROM alliance_list
                        WHERE alliance_id IN ({placeholders})
                        AND (discord_server_id IS NULL OR discord_server_id = ?)
                        ORDER BY name
                    """, (*alliance_ids, guild_id))
                else:
                    self.c_alliance.execute(f"""
                        SELECT alliance_id, name
                        FROM alliance_list
                        WHERE alliance_id IN ({placeholders})
                        ORDER BY name
                    """, alliance_ids)
                alliances = self.c_alliance.fetchall()

            alliances_with_counts = []
            for alliance_id, name in alliances:
                self.c_users.execute("SELECT COUNT(*) FROM users WHERE alliance = ?", (alliance_id,))
                member_count = self.c_users.fetchone()[0]
                alliances_with_counts.append((alliance_id, name, member_count))

            return alliances_with_counts, alliances, is_global_admin
        finally:
            settings_conn.close()

    async def show_alliance_select(self, interaction: discord.Interaction, operation: str = "view"):
        alliances, _, _ = await self.get_admin_alliances(interaction.user.id, interaction.guild_id)
        if not alliances:
            await interaction.response.send_message("❌ No alliances available for this operation.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Select Alliance",
            description="Select an alliance from the dropdown below.",
            color=discord.Color.blue()
        )
        view = AllianceSelectView(alliances, self)

        async def alliance_callback(select_interaction: discord.Interaction):
            alliance_id = int(view.current_select.values[0])
            if operation == "add":
                await select_interaction.response.send_modal(AddAllianceMemberModal(self, alliance_id))
            else:
                await self.show_alliance_members(select_interaction, alliance_id)

        view.callback = alliance_callback
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def show_alliance_members(self, interaction: discord.Interaction, alliance_id: int):
        self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
        alliance = self.c_alliance.fetchone()
        alliance_name = alliance[0] if alliance else f"Alliance {alliance_id}"

        self.c_users.execute("""
            SELECT fid, nickname, furnace_lv, kid
            FROM users
            WHERE alliance = ?
            ORDER BY nickname COLLATE NOCASE
        """, (alliance_id,))
        members = self.c_users.fetchall()

        if not members:
            await interaction.response.send_message(f"❌ No members found for `{alliance_name}`.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"� {alliance_name} Members",
            description=f"Total members: `{len(members)}`",
            color=discord.Color.blue()
        )
        for fid, nickname, furnace_lv, kid in members[:25]:
            embed.add_field(
                name=nickname or str(fid),
                value=f"FID: `{fid}` | Furnace: `{furnace_lv}` | Kingdom: `{kid or 'Unknown'}`",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def add_alliance_member(self, interaction: discord.Interaction, alliance_id: int, fid: int, nickname: str, furnace_lv: int, kid: int | None):
        stove_lv_content = self.level_mapping.get(furnace_lv, str(furnace_lv))
        self.c_users.execute("""
            INSERT OR REPLACE INTO users (fid, nickname, furnace_lv, kid, stove_lv_content, alliance)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fid, nickname, furnace_lv, kid, stove_lv_content, alliance_id))
        self.conn_users.commit()

        self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
        alliance = self.c_alliance.fetchone()
        alliance_name = alliance[0] if alliance else f"Alliance {alliance_id}"

        embed = discord.Embed(
            title="✅ Alliance Member Added",
            description=f"`{nickname}` has been added to `{alliance_name}`.",
            color=discord.Color.green()
        )
        embed.add_field(name="FID", value=f"`{fid}`", inline=True)
        embed.add_field(name="Furnace Level", value=f"`{stove_lv_content}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AllianceSelectView(discord.ui.View):
    def __init__(self, alliances_with_counts, cog=None, page=0):
        super().__init__(timeout=180)
        self.alliances = alliances_with_counts
        self.cog = cog
        self.page = page
        self.current_select = None
        self.callback = None
        self.add_alliance_select()

    def add_alliance_select(self):
        start = self.page * 25
        end = start + 25
        options = [
            discord.SelectOption(
                label=name[:100],
                value=str(alliance_id),
                description=f"{member_count} member(s)"
            )
            for alliance_id, name, member_count in self.alliances[start:end]
        ]
        select = discord.ui.Select(
            placeholder="Select an alliance",
            min_values=1,
            max_values=1,
            options=options
        )

        async def select_callback(interaction: discord.Interaction):
            self.current_select = select
            if self.callback:
                await self.callback(interaction)
            else:
                await interaction.response.send_message("❌ No action configured for this selection.", ephemeral=True)

        select.callback = select_callback
        self.current_select = select
        self.add_item(select)


class MemberOperationsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Add Alliance Member", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add_alliance_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "add")

    @discord.ui.button(label="View Alliance Members", emoji="👥", style=discord.ButtonStyle.primary, row=0)
    async def view_alliance_members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "view")

    @discord.ui.button(label="Select Alliance", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def select_alliance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "view")

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)


class AddAllianceMemberModal(discord.ui.Modal, title="Add Alliance Member"):
    fid = discord.ui.TextInput(label="FID", placeholder="Enter player FID", max_length=20)
    nickname = discord.ui.TextInput(label="Nickname", placeholder="Enter player nickname", max_length=100)
    furnace_lv = discord.ui.TextInput(label="Furnace Level", placeholder="Enter furnace level", max_length=5)
    kid = discord.ui.TextInput(label="Kingdom ID", placeholder="Optional", required=False, max_length=10)

    def __init__(self, cog, alliance_id: int):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id

    async def on_submit(self, interaction: discord.Interaction):
        fid_value = str(self.fid.value).strip()
        furnace_value = str(self.furnace_lv.value).strip()
        kid_value = str(self.kid.value).strip()
        nickname = str(self.nickname.value).strip()

        if not fid_value.isdigit() or not furnace_value.isdigit() or (kid_value and not kid_value.isdigit()):
            await interaction.response.send_message("❌ FID, furnace level, and kingdom ID must be numeric.", ephemeral=True)
            return

        await self.cog.add_alliance_member(
            interaction,
            self.alliance_id,
            int(fid_value),
            nickname,
            int(furnace_value),
            int(kid_value) if kid_value else None
        )

async def setup(bot):
    await bot.add_cog(AllianceMemberOperations(bot))