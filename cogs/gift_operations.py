import discord
from discord.ext import commands
import aiohttp
import ssl
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
from cogs.permissions import check_permission

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

    async def show_create_gift_code_modal(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "mod"):
            await interaction.response.send_message("❌ You don't have permission to use this feature.", ephemeral=True)
            return

        await interaction.response.send_modal(CreateGiftCodeModal(self))

    async def get_alliance_by_input(self, alliance_value: str, guild_id: int):
        if alliance_value.isdigit():
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name
                FROM alliance_list
                WHERE alliance_id = ? AND discord_server_id = ?
                """,
                (int(alliance_value), guild_id)
            )
        else:
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name
                FROM alliance_list
                WHERE LOWER(name) = LOWER(?) AND discord_server_id = ?
                """,
                (alliance_value, guild_id)
            )
        return self.alliance_cursor.fetchone()

    def get_gift_code_failure_reason(self, data):
        msg = data.get("msg") if isinstance(data, dict) else None
        if not msg:
            return "Unknown error"

        reason_mapping = {
            "same gift code": "Already redeemed",
            "expired": "Code expired",
            "params error": "Request error (params)",
            "gift code not found": "Invalid code"
        }
        return reason_mapping.get(msg, msg)

    async def show_gift_code_alliance_select(self, interaction: discord.Interaction, gift_code: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
            return

        self.alliance_cursor.execute(
            """
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
            """,
            (interaction.guild_id,)
        )
        alliances = self.alliance_cursor.fetchall()

        if not alliances:
            await interaction.response.send_message("❌ No alliances found for this server.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎁 Select Alliance",
            description=f"Select the alliance to redeem `{gift_code}` for.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(
            embed=embed,
            view=GiftCodeAllianceSelectView(self, gift_code, alliances),
            ephemeral=True
        )

    async def redeem_gift_code_for_fid(self, fid: int, gift_code: str):
        time_val = int(datetime.now().timestamp())
        form = f"cdk={gift_code}&fid={fid}&time={time_val}"
        sign = hashlib.md5((form + self.wos_encrypt_key).encode('utf-8')).hexdigest()
        form_data = f"cdk={gift_code}&fid={fid}&sign={sign}&time={time_val}"
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded",
            "origin": self.wos_giftcode_redemption_url,
            "referer": f"{self.wos_giftcode_redemption_url}/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(self.wos_giftcode_url, headers=headers, data=form_data) as response:
                response_text = await response.text()
                if response.status != 200:
                    return False, f"HTTP {response.status}: {response_text}"

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError:
                    return False, "Unknown error"

                if data.get("code") == 0 or data.get("success") is True:
                    return True, response_text

                return False, self.get_gift_code_failure_reason(data)

    async def create_gift_code_for_alliance(self, interaction: discord.Interaction, gift_code: str, alliance_id: int, alliance_name: str):
        if interaction.guild_id is None:
            await interaction.followup.send("❌ This can only be used in a server.", ephemeral=True)
            return

        with sqlite3.connect('db/users.sqlite') as users_conn:
            users_cursor = users_conn.cursor()
            users_cursor.execute("SELECT fid FROM users WHERE alliance = ?", (alliance_id,))
            members = users_cursor.fetchall()

        if not members:
            await interaction.followup.send(f"❌ No members found for `{alliance_name}`.", ephemeral=True)
            return

        success_count = 0
        failed = []

        for (fid,) in members:
            ok, result = await self.redeem_gift_code_for_fid(fid, gift_code)
            if ok:
                success_count += 1
            else:
                failed.append((fid, result))
            await asyncio.sleep(1)

        embed = discord.Embed(
            title="🎁 Gift Code Redemption Complete",
            description=f"Redeemed `{gift_code}` for `{alliance_name}`.",
            color=discord.Color.green() if not failed else discord.Color.orange()
        )
        embed.add_field(name="Total Members", value=f"`{len(members)}`", inline=True)
        embed.add_field(name="Succeeded", value=f"`{success_count}`", inline=True)
        embed.add_field(name="Failed", value=f"`{len(failed)}`", inline=True)

        if failed:
            failed_preview = "\n".join(f"FID {fid}: {reason}" for fid, reason in failed[:10])
            embed.add_field(name="Failures", value=failed_preview, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


class GiftMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    async def _not_configured(self, interaction: discord.Interaction, operation: str):
        await interaction.response.send_message(f"❌ {operation} is not configured in this build.", ephemeral=True)

    @discord.ui.button(label="Create Gift Code", emoji="🎫", style=discord.ButtonStyle.primary, row=0)
    async def create_gift_code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_create_gift_code_modal(interaction)

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


class GiftCodeAllianceSelectView(discord.ui.View):
    def __init__(self, cog, gift_code: str, alliances):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(GiftCodeAllianceSelect(cog, gift_code, alliances))


class GiftCodeAllianceSelect(discord.ui.Select):
    def __init__(self, cog, gift_code: str, alliances):
        self.cog = cog
        self.gift_code = gift_code
        self.alliance_names = {str(alliance_id): name for alliance_id, name in alliances[:25]}
        options = [
            discord.SelectOption(label=name[:100], value=str(alliance_id))
            for alliance_id, name in alliances[:25]
        ]
        super().__init__(
            placeholder="Select an alliance",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        alliance_id = int(self.values[0])
        alliance_name = self.alliance_names.get(self.values[0], f"Alliance {alliance_id}")
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.create_gift_code_for_alliance(interaction, self.gift_code, alliance_id, alliance_name)


class CreateGiftCodeModal(discord.ui.Modal, title="Create Gift Code"):
    gift_code = discord.ui.TextInput(
        label="Gift Code",
        placeholder="Enter gift code",
        max_length=100
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        gift_code_value = str(self.gift_code.value).strip()

        if not gift_code_value:
            await interaction.response.send_message("❌ Gift Code is required.", ephemeral=True)
            return

        try:
            await self.cog.show_gift_code_alliance_select(interaction, gift_code_value)
        except Exception as e:
            print(f"[ERROR] Failed to show alliance select for gift_code={gift_code_value}: {e}")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while loading alliances.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(GiftOperations(bot))