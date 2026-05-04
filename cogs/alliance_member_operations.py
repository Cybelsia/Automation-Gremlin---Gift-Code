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
import traceback
from cogs.permissions import check_permission

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
        self._ensure_users_table()
        
        self.level_mapping = {
            31: "30-1", 32: "30-2", 33: "30-3", 34: "30-4",
            35: "FC 1", 36: "FC 1 - 1", 37: "FC 1 - 2", 38: "FC 1 - 3", 39: "FC 1 - 4",
        }

    def _ensure_users_table(self):
        self.c_users.execute("""
            CREATE TABLE IF NOT EXISTS users (
                fid INTEGER PRIMARY KEY,
                nickname TEXT,
                furnace_lv INTEGER DEFAULT 0,
                kid INTEGER,
                stove_lv_content TEXT,
                alliance TEXT,
                discord_id INTEGER
            )
        """)
        self.c_users.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in self.c_users.fetchall()]
        if "discord_id" not in columns:
            self.c_users.execute("ALTER TABLE users ADD COLUMN discord_id INTEGER")
        self.conn_users.commit()

    async def fetch_player_info(self, fid: int):
        time_val = int(datetime.now().timestamp())
        form = f"fid={fid}&time={time_val}"
        sign = hashlib.md5((form + SECRET).encode('utf-8')).hexdigest()
        form_data = f"fid={fid}&sign={sign}&time={time_val}"
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://wos-giftcode.centurygame.com",
            "referer": "https://wos-giftcode.centurygame.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post('https://wos-giftcode-api.centurygame.com/api/player', headers=headers, data=form_data) as response:
                response_text = await response.text()
                if response.status != 200:
                    print(f"[ERROR] Player API failed fid={fid} status={response.status} response_body={response_text}")
                    raise RuntimeError(f"Player API returned HTTP {response.status}: {response_text}")

                data = await response.json()
                player_data = data.get('data')
                if not player_data:
                    print(f"[ERROR] Player API returned no data fid={fid} response_body={response_text}")
                    raise RuntimeError(f"Player API returned no player data: {data}")

                return player_data

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
        if guild_id is None:
            return [], [], False

        if not check_permission(user_id, guild_id, "mod"):
            return [], [], False

        is_admin = check_permission(user_id, guild_id, "admin")

        self.c_alliance.execute("""
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
        """, (guild_id,))
        alliances = self.c_alliance.fetchall()
        print(f"[DEBUG] get_admin_alliances guild_id={guild_id} raw_results={alliances}")

        alliances_with_counts = []
        for alliance_id, name in alliances:
            self.c_users.execute("SELECT COUNT(*) FROM users WHERE alliance = ?", (alliance_id,))
            member_count = self.c_users.fetchone()[0]
            alliances_with_counts.append((alliance_id, name, member_count))

        return alliances_with_counts, alliances, is_admin

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
            SELECT fid, nickname, furnace_lv, kid, discord_id
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
        for fid, nickname, furnace_lv, kid, discord_id in members[:25]:
            discord_name = "No Discord"
            if discord_id:
                try:
                    discord_user = await self.bot.fetch_user(int(discord_id))
                    discord_name = str(discord_user) if discord_user else str(discord_id)
                except Exception:
                    discord_name = str(discord_id)

            embed.add_field(
                name=nickname or str(fid),
                value=f"FID: `{fid}` | Discord: `{discord_name}` | Furnace: `{furnace_lv}` | Kingdom: `{kid or 'Unknown'}`",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def add_alliance_member(self, interaction: discord.Interaction, alliance_id: int, fid: int, discord_id: int = None):
        player_data = await self.fetch_player_info(fid)
        nickname = player_data.get('nickname')
        furnace_lv = player_data.get('stove_lv', 0)
        kid = player_data.get('kid', None)
        stove_lv_content = player_data.get('stove_lv_content') or self.level_mapping.get(furnace_lv, str(furnace_lv))

        self.c_users.execute("""
            INSERT OR REPLACE INTO users (fid, discord_id, nickname, furnace_lv, kid, stove_lv_content, alliance)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (fid, discord_id, nickname, furnace_lv, kid, stove_lv_content, alliance_id))
        self.conn_users.commit()

        self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
        alliance = self.c_alliance.fetchone()
        alliance_name = alliance[0] if alliance else f"Alliance {alliance_id}"
        discord_name = "No Discord account linked"
        if discord_id:
            try:
                discord_user = await self.bot.fetch_user(int(discord_id))
                discord_name = str(discord_user) if discord_user else "No Discord account linked"
            except Exception:
                discord_name = "No Discord account linked"

        embed = discord.Embed(
            title="✅ Alliance Member Added",
            description=f"`{nickname}` has been added to `{alliance_name}`.",
            color=discord.Color.green()
        )
        embed.add_field(name="FID", value=f"`{fid}`", inline=True)
        embed.add_field(name="Discord ID", value=f"`{discord_id}`" if discord_id else "`None`", inline=True)
        embed.add_field(name="Discord", value=f"`{discord_name}`", inline=True)
        embed.add_field(name="Nickname", value=f"`{nickname}`", inline=True)
        embed.add_field(name="Furnace Level", value=f"`{stove_lv_content}`", inline=True)
        embed.add_field(name="Kingdom ID", value=f"`{kid or 'Unknown'}`", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

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
    discord_id = discord.ui.TextInput(label="Discord ID", placeholder="Optional: Enter Discord user ID", max_length=20, required=False)

    def __init__(self, cog, alliance_id: int):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id

    async def on_submit(self, interaction: discord.Interaction):
        fid_value = str(self.fid.value).strip()
        discord_id_value = str(self.discord_id.value).strip()

        if not fid_value.isdigit():
            await interaction.response.send_message("❌ FID must be numeric.", ephemeral=True)
            return

        if discord_id_value and not discord_id_value.isdigit():
            await interaction.response.send_message("❌ Discord ID must be numeric if provided.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            await self.cog.add_alliance_member(
                interaction,
                self.alliance_id,
                int(fid_value),
                int(discord_id_value) if discord_id_value else None
            )
        except Exception as e:
            print(f"[ERROR] Failed to add alliance member fid={fid_value} discord_id={discord_id_value}: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            await interaction.followup.send("❌ Failed to fetch or save player information.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AllianceMemberOperations(bot))