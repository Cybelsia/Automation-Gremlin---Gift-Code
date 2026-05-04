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
                "👥 **View Alliance Members**\n"
                "└ View members in an alliance\n\n"
                "✏️ **Edit Member**\n"
                "└ Edit an existing alliance member\n\n"
                "🗑️ **Delete Member**\n"
                "└ Delete an alliance member\n\n"
                "🔍 **Member Scan**\n"
                "└ Scan alliance members\n\n"
                "🆔 **FID Number Lookup**\n"
                "└ Look up member details by FID\n\n"
                "⬅️ **Back**\n"
                "└ Return to WOS menu\n"
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
        is_owner = (user_id == 1237812594140512347)

        if is_owner or not is_admin:
            # Owner sees all alliances; mods see all alliances in the server
            self.c_alliance.execute("""
                SELECT alliance_id, name
                FROM alliance_list
                WHERE discord_server_id = ?
                ORDER BY name
            """, (guild_id,))
            alliances = self.c_alliance.fetchall()
        else:
            # Admins only see alliances assigned to them in admin_alliances
            with sqlite3.connect('db/settings.sqlite') as sdb:
                scursor = sdb.cursor()
                scursor.execute("""
                    SELECT aa.alliance_id
                    FROM admin_alliances aa
                    WHERE aa.guild_id = ? AND aa.user_id = ?
                """, (guild_id, user_id))
                assigned = [r[0] for r in scursor.fetchall()]

            if not assigned:
                # No alliances assigned yet — fall back to all (so they aren't locked out)
                self.c_alliance.execute("""
                    SELECT alliance_id, name
                    FROM alliance_list
                    WHERE discord_server_id = ?
                    ORDER BY name
                """, (guild_id,))
                alliances = self.c_alliance.fetchall()
            else:
                placeholders = ",".join("?" * len(assigned))
                self.c_alliance.execute(f"""
                    SELECT alliance_id, name
                    FROM alliance_list
                    WHERE discord_server_id = ? AND alliance_id IN ({placeholders})
                    ORDER BY name
                """, [guild_id] + assigned)
                alliances = self.c_alliance.fetchall()

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
            elif operation == "edit":
                await self.show_member_select(select_interaction, alliance_id, "edit")
            elif operation == "delete":
                await self.show_member_select(select_interaction, alliance_id, "delete")
            else:
                await self.show_alliance_members(select_interaction, alliance_id)

        view.callback = alliance_callback
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

<<<<<<< HEAD
    async def show_member_select(self, interaction: discord.Interaction, alliance_id: int, operation: str):
        self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
        alliance = self.c_alliance.fetchone()
        alliance_name = alliance[0] if alliance else f"Alliance {alliance_id}"

        self.c_users.execute("""
            SELECT fid, nickname FROM users
=======
    async def show_edit_member_select(self, interaction: discord.Interaction):
        await self.show_member_select(interaction, "edit")

    async def show_delete_member_select(self, interaction: discord.Interaction):
        await self.show_member_select(interaction, "delete")

    async def show_member_scan(self, interaction: discord.Interaction):
        await self.show_member_select(interaction, "scan_alliance")

    async def show_fid_number_lookup(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "mod"):
            await interaction.response.send_message("❌ You don't have permission to look up member FIDs.", ephemeral=True)
            return
        await interaction.response.send_modal(FIDLookupModal(self))

    async def show_member_select(self, interaction: discord.Interaction, operation: str):
        alliances, _, _ = await self.get_admin_alliances(interaction.user.id, interaction.guild_id)
        if not alliances:
            await interaction.response.send_message("❌ No alliances available for this operation.", ephemeral=True)
            return

        if operation == "scan_alliance":
            embed = discord.Embed(
                title="🔍 Select Alliance to Scan",
                description="Select an alliance to manually scan and refresh all stored member data.",
                color=discord.Color.blue()
            )
            view = AllianceSelectView(alliances, self)

            async def scan_callback(select_interaction: discord.Interaction):
                alliance_id = int(view.current_select.values[0])
                await self.scan_alliance_members(select_interaction, alliance_id)

            view.callback = scan_callback
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        self.c_users.execute("""
            SELECT u.fid, u.nickname, u.alliance, a.name
            FROM users u
            LEFT JOIN alliance_list a ON CAST(u.alliance AS TEXT) = CAST(a.alliance_id AS TEXT)
            WHERE a.discord_server_id = ?
            ORDER BY a.name COLLATE NOCASE, u.nickname COLLATE NOCASE
        """, (interaction.guild_id,))
        members = self.c_users.fetchall()
        if not members:
            await interaction.response.send_message("❌ No alliance members available for this operation.", ephemeral=True)
            return

        title = "✏️ Select Member to Edit" if operation == "edit" else "🗑️ Select Member to Delete"
        embed = discord.Embed(
            title=title,
            description="Select a member from the dropdown below.",
            color=discord.Color.blue() if operation == "edit" else discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, view=MemberSelectView(self, members, operation), ephemeral=True)

    async def get_member(self, fid: int):
        self.c_users.execute("""
            SELECT u.fid, u.nickname, u.furnace_lv, u.kid, u.stove_lv_content, u.alliance, u.discord_id, a.name
            FROM users u
            LEFT JOIN alliance_list a ON CAST(u.alliance AS TEXT) = CAST(a.alliance_id AS TEXT)
            WHERE u.fid = ?
        """, (fid,))
        return self.c_users.fetchone()

    async def update_member(self, interaction: discord.Interaction, original_fid: int, fid: int, nickname: str, furnace_lv: int, kid: int, stove_lv_content: str, discord_id: int):
        try:
            self.c_users.execute("""
                UPDATE users
                SET fid = ?, nickname = ?, furnace_lv = ?, kid = ?, stove_lv_content = ?, discord_id = ?
                WHERE fid = ?
            """, (fid, nickname, furnace_lv, kid, stove_lv_content, discord_id, original_fid))
            self.conn_users.commit()
        except sqlite3.IntegrityError:
            await interaction.response.send_message("❌ Another member already uses that FID.", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Member Updated",
            description=f"`{nickname}` has been updated.",
            color=discord.Color.green()
        )
        embed.add_field(name="FID", value=f"`{fid}`", inline=True)
        embed.add_field(name="Furnace Level", value=f"`{stove_lv_content or furnace_lv}`", inline=True)
        embed.add_field(name="Kingdom ID", value=f"`{kid or 'Unknown'}`", inline=True)
        embed.add_field(name="Discord ID", value=f"`{discord_id}`" if discord_id else "`None`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def confirm_delete_member(self, interaction: discord.Interaction, fid: int):
        member = await self.get_member(fid)
        if not member:
            await interaction.response.send_message("❌ Member not found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚠️ Confirm Member Deletion",
            description=f"Are you sure you want to delete `{member[1] or fid}` from `{member[7] or 'Unknown Alliance'}`?",
            color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=ConfirmDeleteMemberView(self, fid))

    async def delete_member(self, interaction: discord.Interaction, fid: int):
        member = await self.get_member(fid)
        if not member:
            await interaction.response.edit_message(content="❌ Member not found.", embed=None, view=None)
            return

        self.c_users.execute("DELETE FROM users WHERE fid = ?", (fid,))
        self.conn_users.commit()
        embed = discord.Embed(
            title="✅ Member Deleted",
            description=f"Deleted `{member[1] or fid}` from `{member[7] or 'Unknown Alliance'}`.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def scan_alliance_members(self, interaction: discord.Interaction, alliance_id: int):
        if not check_permission(interaction.user.id, interaction.guild_id, "mod"):
            await interaction.response.send_message("❌ You don't have permission to scan alliance members.", ephemeral=True)
            return

        self.c_users.execute("""
            SELECT fid, nickname, furnace_lv, kid, stove_lv_content, discord_id
            FROM users
>>>>>>> 0f27573 (Restructure menu flow and move member tools under WOS)
            WHERE alliance = ?
            ORDER BY nickname COLLATE NOCASE
        """, (alliance_id,))
        members = self.c_users.fetchall()
<<<<<<< HEAD

        if not members:
            await interaction.response.send_message(f"❌ No members found in `{alliance_name}`.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=f"{nickname or fid}"[:100], value=str(fid), description=f"FID: {fid}")
            for fid, nickname in members[:25]
        ]
        select = discord.ui.Select(placeholder="Select a member", min_values=1, max_values=1, options=options)
        view = discord.ui.View(timeout=180)

        async def member_callback(select_interaction: discord.Interaction):
            fid = int(select.values[0])
            nickname = next((n for f, n in members if f == fid), str(fid))
            if operation == "edit":
                await select_interaction.response.send_modal(EditMemberModal(self, fid, nickname))
            elif operation == "delete":
                await self.confirm_delete_member(select_interaction, fid, nickname, alliance_name)

        select.callback = member_callback
        view.add_item(select)

        title = "✏️ Select Member to Edit" if operation == "edit" else "🗑️ Select Member to Delete"
        embed = discord.Embed(title=title, description=f"Alliance: `{alliance_name}`", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=view)

    async def confirm_delete_member(self, interaction: discord.Interaction, fid: int, nickname: str, alliance_name: str):
        embed = discord.Embed(
            title="⚠️ Confirm Member Deletion",
            description=f"Are you sure you want to remove `{nickname}` (FID: `{fid}`) from `{alliance_name}`?",
            color=discord.Color.orange()
        )
        view = ConfirmDeleteMemberView(self, fid, nickname)
        await interaction.response.edit_message(embed=embed, view=view)
=======
        if not members:
            await interaction.response.send_message("❌ No members found for this alliance.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        updated = 0
        failed = 0
        changes = []

        for fid, old_nickname, old_furnace_lv, old_kid, old_stove_lv_content, discord_id in members:
            try:
                player_data = await self.fetch_player_info(int(fid))
                nickname = player_data.get('nickname')
                furnace_lv = player_data.get('stove_lv', 0)
                kid = player_data.get('kid', None)
                stove_lv_content = player_data.get('stove_lv_content') or self.level_mapping.get(furnace_lv, str(furnace_lv))
                self.c_users.execute("""
                    UPDATE users
                    SET nickname = ?, furnace_lv = ?, kid = ?, stove_lv_content = ?
                    WHERE fid = ?
                """, (nickname, furnace_lv, kid, stove_lv_content, fid))
                updated += 1
                if (nickname, furnace_lv, kid, stove_lv_content) != (old_nickname, old_furnace_lv, old_kid, old_stove_lv_content):
                    changes.append(f"`{old_nickname or fid}` → `{nickname}` | `{old_furnace_lv}` → `{stove_lv_content}`")
            except Exception as e:
                failed += 1
                print(f"[ERROR] Member scan failed fid={fid}: {e}")

        self.conn_users.commit()
        embed = discord.Embed(
            title="🔍 Member Scan Complete",
            color=discord.Color.green() if failed == 0 else discord.Color.orange()
        )
        embed.add_field(name="Members Checked", value=f"`{len(members)}`", inline=True)
        embed.add_field(name="Updated", value=f"`{updated}`", inline=True)
        embed.add_field(name="Failed", value=f"`{failed}`", inline=True)
        if changes:
            embed.add_field(name="Changes", value="\n".join(changes[:10]), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def lookup_fid(self, interaction: discord.Interaction, fid: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            player_data = await self.fetch_player_info(fid)
        except Exception as e:
            print(f"[ERROR] FID lookup failed fid={fid}: {e}")
            await interaction.followup.send("❌ Failed to fetch player information for that FID.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🆔 FID Number Lookup",
            description=f"Player information for FID `{fid}`.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Nickname", value=f"`{player_data.get('nickname') or 'Unknown'}`", inline=True)
        embed.add_field(name="Furnace Level", value=f"`{player_data.get('stove_lv_content') or player_data.get('stove_lv', 'Unknown')}`", inline=True)
        embed.add_field(name="Kingdom ID", value=f"`{player_data.get('kid') or 'Unknown'}`", inline=True)
        avatar_image = player_data.get('avatar_image')
        stove_lv_content = player_data.get('stove_lv_content')
        if avatar_image:
            embed.set_image(url=avatar_image)
        if isinstance(stove_lv_content, str) and stove_lv_content.startswith("http"):
            embed.set_thumbnail(url=stove_lv_content)
        await interaction.followup.send(embed=embed, ephemeral=True)
>>>>>>> 0f27573 (Restructure menu flow and move member tools under WOS)

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

    async def _not_configured(self, interaction: discord.Interaction, operation: str):
        await interaction.response.send_message(f"❌ {operation} is not configured in this build.", ephemeral=True)

    @discord.ui.button(label="Add Alliance Member", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add_alliance_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "add")

    @discord.ui.button(label="View Alliance Members", emoji="👥", style=discord.ButtonStyle.primary, row=0)
    async def view_alliance_members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "view")

<<<<<<< HEAD
    @discord.ui.button(label="Edit Member", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
    async def edit_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "edit")

    @discord.ui.button(label="Delete Member", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliance_select(interaction, "delete")

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
=======
    @discord.ui.button(label="Edit Member", emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def edit_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(self.cog, "show_edit_member_select"):
            await self.cog.show_edit_member_select(interaction)
        else:
            await self._not_configured(interaction, "Edit Member")

    @discord.ui.button(label="Delete Member", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(self.cog, "show_delete_member_select"):
            await self.cog.show_delete_member_select(interaction)
        else:
            await self._not_configured(interaction, "Delete Member")

    @discord.ui.button(label="Member Scan", emoji="🔍", style=discord.ButtonStyle.primary, row=2)
    async def member_scan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(self.cog, "show_member_scan"):
            await self.cog.show_member_scan(interaction)
        elif hasattr(self.cog, "member_scan"):
            await self.cog.member_scan(interaction)
        else:
            await self._not_configured(interaction, "Member Scan")

    @discord.ui.button(label="FID Number Lookup", emoji="🆔", style=discord.ButtonStyle.primary, row=2)
    async def fid_number_lookup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(self.cog, "show_fid_number_lookup"):
            await self.cog.show_fid_number_lookup(interaction)
        elif hasattr(self.cog, "fid_number_lookup"):
            await self.cog.fid_number_lookup(interaction)
        else:
            await self._not_configured(interaction, "FID Number Lookup")

    @discord.ui.button(label="Back", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
>>>>>>> 0f27573 (Restructure menu flow and move member tools under WOS)
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_wos_menu(interaction)
        else:
            await interaction.response.send_message("❌ WOS menu not found.", ephemeral=True)


class MemberSelectView(discord.ui.View):
    def __init__(self, cog, members, operation: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.members = members
        self.operation = operation
        self.add_member_select()

    def add_member_select(self):
        options = [
            discord.SelectOption(
                label=(nickname or str(fid))[:100],
                value=str(fid),
                description=f"{alliance_name or 'Unknown Alliance'} | FID {fid}"[:100]
            )
            for fid, nickname, alliance_id, alliance_name in self.members[:25]
        ]
        select = discord.ui.Select(
            placeholder="Select a member",
            min_values=1,
            max_values=1,
            options=options
        )

        async def select_callback(interaction: discord.Interaction):
            fid = int(select.values[0])
            if self.operation == "edit":
                member = await self.cog.get_member(fid)
                if not member:
                    await interaction.response.send_message("❌ Member not found.", ephemeral=True)
                    return
                await interaction.response.send_modal(EditMemberModal(self.cog, member))
            elif self.operation == "delete":
                await self.cog.confirm_delete_member(interaction, fid)
            else:
                await interaction.response.send_message("❌ No action configured for this selection.", ephemeral=True)

        select.callback = select_callback
        self.add_item(select)


class EditMemberModal(discord.ui.Modal):
    def __init__(self, cog, member):
        super().__init__(title="Edit Member")
        self.cog = cog
        self.original_fid = int(member[0])
        self.fid = discord.ui.TextInput(label="FID", default=str(member[0]), max_length=20)
        self.nickname = discord.ui.TextInput(label="Nickname", default=str(member[1] or ""), max_length=100)
        self.furnace_lv = discord.ui.TextInput(label="Furnace Level", default=str(member[2] or 0), max_length=10)
        self.kid = discord.ui.TextInput(label="Kingdom ID", default=str(member[3] or ""), max_length=20, required=False)
        self.discord_id = discord.ui.TextInput(label="Discord ID", default=str(member[6] or ""), max_length=20, required=False)
        self.add_item(self.fid)
        self.add_item(self.nickname)
        self.add_item(self.furnace_lv)
        self.add_item(self.kid)
        self.add_item(self.discord_id)

    async def on_submit(self, interaction: discord.Interaction):
        fid_value = str(self.fid.value).strip()
        nickname_value = str(self.nickname.value).strip()
        furnace_value = str(self.furnace_lv.value).strip()
        kid_value = str(self.kid.value).strip()
        discord_id_value = str(self.discord_id.value).strip()

        if not fid_value.isdigit():
            await interaction.response.send_message("❌ FID must be numeric.", ephemeral=True)
            return
        if not nickname_value:
            await interaction.response.send_message("❌ Nickname is required.", ephemeral=True)
            return
        if not furnace_value.isdigit():
            await interaction.response.send_message("❌ Furnace level must be numeric.", ephemeral=True)
            return
        if kid_value and not kid_value.isdigit():
            await interaction.response.send_message("❌ Kingdom ID must be numeric if provided.", ephemeral=True)
            return
        if discord_id_value and not discord_id_value.isdigit():
            await interaction.response.send_message("❌ Discord ID must be numeric if provided.", ephemeral=True)
            return

        furnace_lv = int(furnace_value)
        stove_lv_content = self.cog.level_mapping.get(furnace_lv, str(furnace_lv))
        await self.cog.update_member(
            interaction,
            self.original_fid,
            int(fid_value),
            nickname_value,
            furnace_lv,
            int(kid_value) if kid_value else None,
            stove_lv_content,
            int(discord_id_value) if discord_id_value else None
        )


class ConfirmDeleteMemberView(discord.ui.View):
    def __init__(self, cog, fid: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.fid = fid

    @discord.ui.button(label="Confirm Delete", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.delete_member(interaction, self.fid)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Deletion cancelled.", embed=None, view=None)


class FIDLookupModal(discord.ui.Modal, title="FID Number Lookup"):
    fid = discord.ui.TextInput(label="FID", placeholder="Enter player FID", max_length=20)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        fid_value = str(self.fid.value).strip()
        if not fid_value.isdigit():
            await interaction.response.send_message("❌ FID must be numeric.", ephemeral=True)
            return
        await self.cog.lookup_fid(interaction, int(fid_value))


class EditMemberModal(discord.ui.Modal, title="Edit Alliance Member"):
    discord_id = discord.ui.TextInput(label="Discord ID", placeholder="Enter Discord user ID (or leave blank to clear)", max_length=20, required=False)

    def __init__(self, cog, fid: int, nickname: str):
        super().__init__()
        self.cog = cog
        self.fid = fid
        self.nickname = nickname

    async def on_submit(self, interaction: discord.Interaction):
        discord_id_value = str(self.discord_id.value).strip()
        if discord_id_value and not discord_id_value.isdigit():
            await interaction.response.send_message("❌ Discord ID must be numeric.", ephemeral=True)
            return
        new_discord_id = int(discord_id_value) if discord_id_value else None
        try:
            self.cog.c_users.execute(
                "UPDATE users SET discord_id = ? WHERE fid = ?",
                (new_discord_id, self.fid)
            )
            self.cog.conn_users.commit()
            embed = discord.Embed(
                title="✅ Member Updated",
                color=discord.Color.green()
            )
            embed.add_field(name="Player", value=f"`{self.nickname}`", inline=True)
            embed.add_field(name="FID", value=f"`{self.fid}`", inline=True)
            embed.add_field(name="Discord ID", value=f"`{new_discord_id}`" if new_discord_id else "`Cleared`", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"[ERROR] EditMemberModal fid={self.fid}: {e}")
            await interaction.response.send_message("❌ An error occurred while updating the member.", ephemeral=True)


class ConfirmDeleteMemberView(discord.ui.View):
    def __init__(self, cog, fid: int, nickname: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.fid = fid
        self.nickname = nickname

    @discord.ui.button(label="Confirm Delete", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.c_users.execute("DELETE FROM users WHERE fid = ?", (self.fid,))
            self.cog.conn_users.commit()
            embed = discord.Embed(
                title="✅ Member Removed",
                description=f"`{self.nickname}` (FID: `{self.fid}`) has been removed.",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            print(f"[ERROR] DeleteMember fid={self.fid}: {e}")
            await interaction.response.edit_message(content="❌ An error occurred while deleting the member.", embed=None, view=None)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Deletion cancelled.", embed=None, view=None)


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