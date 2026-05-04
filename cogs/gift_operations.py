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

        self.gift_operations_conn = sqlite3.connect('db/gift_operations.sqlite')
        self.gift_operations_cursor = self.gift_operations_conn.cursor()
        self.gift_operations_cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_gift_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                results_channel_id INTEGER
            )
        """)
        self.gift_operations_cursor.execute("PRAGMA table_info(auto_gift_settings)")
        auto_gift_settings_columns = [column[1] for column in self.gift_operations_cursor.fetchall()]
        if "results_channel_id" not in auto_gift_settings_columns:
            self.gift_operations_cursor.execute("ALTER TABLE auto_gift_settings ADD COLUMN results_channel_id INTEGER")
        self.gift_operations_cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_gift_alliances (
                guild_id INTEGER,
                alliance_id INTEGER,
                PRIMARY KEY (guild_id, alliance_id)
            )
        """)
        self.gift_operations_conn.commit()
        
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

        # Per-alliance scheduler: tracks last run time keyed by alliance_id
        self._last_run: dict[int, float] = {}
        self.alliance_scheduler.start()
        self.weekly_member_scan.start()

    def cog_unload(self):
        self.alliance_scheduler.cancel()
        self.weekly_member_scan.cancel()

    @tasks.loop(seconds=60)
    async def alliance_scheduler(self):
        """Runs every 60 seconds. For each alliance, checks if its refresh_rate has elapsed
        since last run, then scans its gift code channel and redeems any found codes."""
        try:
            now = asyncio.get_event_loop().time()
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name, discord_server_id, refresh_rate,
                       gift_code_channel_id, results_channel_id
                FROM alliance_list
                WHERE gift_code_channel_id IS NOT NULL
                  AND refresh_rate IS NOT NULL
                  AND refresh_rate > 0
                """
            )
            alliances = self.alliance_cursor.fetchall()

            for alliance_id, name, guild_id, refresh_rate, gift_channel_id, results_channel_id in alliances:
                last_run = self._last_run.get(alliance_id, 0)
                if now - last_run < refresh_rate:
                    continue

                self._last_run[alliance_id] = now
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    print(f"[SCHEDULER] Guild {guild_id} not found for alliance {alliance_id}, skipping")
                    continue

                gift_channel = guild.get_channel(gift_channel_id)
                if gift_channel is None:
                    print(f"[SCHEDULER] Gift code channel {gift_channel_id} not found for alliance {alliance_id}, skipping")
                    continue

                results_channel = guild.get_channel(results_channel_id) if results_channel_id else gift_channel

                print(f"[SCHEDULER] Scanning alliance_id={alliance_id} name={name} channel={gift_channel_id}")

                found_codes = []
                async for message in gift_channel.history(limit=50):
                    code = self.extract_auto_gift_code(message.content)
                    if code and code not in found_codes:
                        found_codes.append(code)

                if not found_codes:
                    print(f"[SCHEDULER] No codes found for alliance_id={alliance_id}")
                    continue

                # Redeem only for this specific alliance
                with sqlite3.connect('db/users.sqlite') as users_conn:
                    users_cursor = users_conn.cursor()
                    users_cursor.execute("SELECT fid FROM users WHERE alliance = ?", (alliance_id,))
                    members = users_cursor.fetchall()

                if not members:
                    print(f"[SCHEDULER] No members for alliance_id={alliance_id}, skipping")
                    continue

                total_success = 0
                total_failed = 0
                for gift_code in found_codes:
                    for (fid,) in members:
                        ok, _ = await self.redeem_gift_code_for_fid(fid, gift_code)
                        if ok:
                            total_success += 1
                        else:
                            total_failed += 1
                        await asyncio.sleep(1)

                embed = discord.Embed(
                    title="⏰ Scheduled Gift Code Redemption",
                    description=f"Alliance: `{name}`",
                    color=discord.Color.green() if total_failed == 0 else discord.Color.orange()
                )
                embed.add_field(name="Codes Found", value=f"`{len(found_codes)}`", inline=True)
                embed.add_field(name="Members Processed", value=f"`{len(members)}`", inline=True)
                embed.add_field(name="Succeeded", value=f"`{total_success}`", inline=True)
                embed.add_field(name="Failed", value=f"`{total_failed}`", inline=True)
                await results_channel.send(embed=embed)

        except Exception as e:
            print(f"[SCHEDULER] Error in alliance_scheduler: {e}")
            traceback.print_exc()

    @alliance_scheduler.before_loop
    async def before_alliance_scheduler(self):
        await self.bot.wait_until_ready()

    async def run_member_scan(self, label: str = "Weekly"):
        """Runs the member scan for all alliances with a results channel. Called by scheduler and manual trigger."""
        now = datetime.utcnow()
        print(f"[{label.upper()} SCAN] Starting member scan at {now}")
        try:
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name, discord_server_id, results_channel_id
                FROM alliance_list
                WHERE results_channel_id IS NOT NULL
                """
            )
            alliances = self.alliance_cursor.fetchall()

            for alliance_id, alliance_name, guild_id, results_channel_id in alliances:
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    print(f"[{label.upper()} SCAN] Guild {guild_id} not found for alliance {alliance_id}, skipping")
                    continue

                results_channel = guild.get_channel(results_channel_id)
                if results_channel is None:
                    print(f"[{label.upper()} SCAN] Results channel {results_channel_id} not found for alliance {alliance_id}, skipping")
                    continue

                with sqlite3.connect('db/users.sqlite') as users_conn:
                    users_cursor = users_conn.cursor()
                    users_cursor.execute(
                        "SELECT fid, nickname, furnace_lv FROM users WHERE alliance = ?",
                        (alliance_id,)
                    )
                    members = users_cursor.fetchall()

                if not members:
                    print(f"[{label.upper()} SCAN] No members for alliance {alliance_id}, skipping")
                    continue

                name_changes = []
                furnace_changes = []
                errors = []

                for fid, old_nickname, old_furnace_lv in members:
                    try:
                        time_val = int(datetime.utcnow().timestamp())
                        form = f"fid={fid}&time={time_val}"
                        sign = hashlib.md5((form + self.wos_encrypt_key).encode('utf-8')).hexdigest()
                        form_data = f"fid={fid}&sign={sign}&time={time_val}"
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
                            async with session.post(self.wos_player_info_url, headers=headers, data=form_data) as response:
                                data = await response.json()

                        player = data.get('data', {})
                        new_nickname = player.get('nickname')
                        new_furnace_lv = player.get('stove_lv')

                        updated = False
                        if new_nickname and new_nickname != old_nickname:
                            name_changes.append((fid, old_nickname, new_nickname))
                            updated = True
                        if new_furnace_lv is not None and new_furnace_lv != old_furnace_lv:
                            furnace_changes.append((fid, old_furnace_lv, new_furnace_lv))
                            updated = True

                        if updated:
                            with sqlite3.connect('db/users.sqlite') as users_conn:
                                users_conn.execute(
                                    "UPDATE users SET nickname = ?, furnace_lv = ? WHERE fid = ?",
                                    (new_nickname or old_nickname, new_furnace_lv if new_furnace_lv is not None else old_furnace_lv, fid)
                                )
                                users_conn.commit()

                        await asyncio.sleep(1)

                    except Exception as e:
                        print(f"[{label.upper()} SCAN] Error fetching fid={fid}: {e}")
                        errors.append(fid)

                embed = discord.Embed(
                    title=f"📊 {label} Member Scan — {alliance_name}",
                    description=f"Scan completed for `{len(members)}` members.",
                    color=discord.Color.blue()
                )
                if name_changes:
                    name_lines = "\n".join(f"FID `{fid}`: `{old}` → `{new}`" for fid, old, new in name_changes[:20])
                    embed.add_field(name=f"✏️ Name Changes ({len(name_changes)})", value=name_lines, inline=False)
                else:
                    embed.add_field(name="✏️ Name Changes", value="None", inline=False)
                if furnace_changes:
                    furnace_lines = "\n".join(f"FID `{fid}`: Lv `{old}` → Lv `{new}`" for fid, old, new in furnace_changes[:20])
                    embed.add_field(name=f"🔥 Furnace Changes ({len(furnace_changes)})", value=furnace_lines, inline=False)
                else:
                    embed.add_field(name="🔥 Furnace Changes", value="None", inline=False)
                if errors:
                    embed.add_field(name="⚠️ Errors", value=f"`{len(errors)}` members could not be fetched", inline=False)
                embed.set_footer(text=f"Scan time: {now.strftime('%Y-%m-%d %H:%M UTC')}")
                await results_channel.send(embed=embed)
                print(f"[{label.upper()} SCAN] Done for alliance {alliance_id} — {len(name_changes)} name changes, {len(furnace_changes)} furnace changes")

        except Exception as e:
            print(f"[{label.upper()} SCAN] Fatal error: {e}")
            traceback.print_exc()

    @tasks.loop(hours=1)
    async def weekly_member_scan(self):
        """Runs every hour but only executes on Sunday at 00:00 UTC."""
        now = datetime.utcnow()
        if not (now.weekday() == 6 and now.hour == 0):
            return
        await self.run_member_scan(label="Weekly")

    @weekly_member_scan.before_loop
    async def before_weekly_member_scan(self):
        await self.bot.wait_until_ready()

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

    async def show_auto_gift_settings(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        self.gift_operations_cursor.execute(
            "SELECT channel_id, results_channel_id FROM auto_gift_settings WHERE guild_id = ?",
            (interaction.guild_id,)
        )
        channel_row = self.gift_operations_cursor.fetchone()
        channel_text = f"<#{channel_row[0]}>" if channel_row and channel_row[0] else "`Not set`"
        results_channel_text = f"<#{channel_row[1]}>" if channel_row and channel_row[1] else "`Not set`"

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
        enabled_alliances = self.get_auto_gift_enabled_alliances(interaction.guild_id, alliances)

        embed = discord.Embed(
            title="⚙️ Auto Gift Code Settings",
            description=(
                "**Available Options**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📢 **Set Gift Code Channel**\n"
                "└ Save the channel used for auto gift code messages\n\n"
                "📊 **Set Results Channel**\n"
                "└ Save the channel used for auto redemption results\n\n"
                "🛡️ **Configure Alliances**\n"
                "└ Toggle which alliances participate in auto-redemption\n\n"
                "🔍 **Scan Gift Code Channel**\n"
                "└ Scan the last 50 messages for gift codes\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.gold()
        )
        embed.add_field(name="Gift Code Channel", value=channel_text, inline=False)
        embed.add_field(name="Results Channel", value=results_channel_text, inline=False)
        embed.add_field(name="Enabled Alliances", value=f"`{len(enabled_alliances)}` / `{len(alliances)}`", inline=False)
        await interaction.response.send_message(embed=embed, view=AutoGiftSettingsView(self), ephemeral=True)

    def get_auto_gift_enabled_alliances(self, guild_id: int, alliances):
        all_alliance_ids = [alliance_id for alliance_id, _ in alliances]
        self.gift_operations_cursor.execute(
            "SELECT alliance_id FROM auto_gift_alliances WHERE guild_id = ?",
            (guild_id,)
        )
        rows = self.gift_operations_cursor.fetchall()
        if not rows:
            return all_alliance_ids
        return [row[0] for row in rows]

    async def save_auto_gift_channel(self, interaction: discord.Interaction, channel):
        self.gift_operations_cursor.execute(
            """
            INSERT OR REPLACE INTO auto_gift_settings (guild_id, channel_id)
            VALUES (?, ?)
            """,
            (interaction.guild_id, channel.id)
        )
        self.gift_operations_conn.commit()
        embed = discord.Embed(
            title="✅ Gift Code Channel Updated",
            description=f"Auto gift codes will now be read from {channel.mention}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Channel", value=channel.name, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def save_auto_gift_results_channel(self, interaction: discord.Interaction, channel):
        self.gift_operations_cursor.execute(
            """
            INSERT INTO auto_gift_settings (guild_id, results_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET results_channel_id = excluded.results_channel_id
            """,
            (interaction.guild_id, channel.id)
        )
        self.gift_operations_conn.commit()
        embed = discord.Embed(
            title="✅ Results Channel Updated",
            description=f"Auto gift redemption results will now be posted in {channel.mention}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Channel", value=channel.name, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def show_auto_gift_alliance_select(self, interaction: discord.Interaction):
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

        enabled_alliances = self.get_auto_gift_enabled_alliances(interaction.guild_id, alliances)
        embed = discord.Embed(
            title="🛡️ Configure Auto Gift Alliances",
            description="Select the alliances that should participate in auto-redemption.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(
            embed=embed,
            view=AutoGiftAllianceSelectView(self, alliances, enabled_alliances),
            ephemeral=True
        )

    async def save_auto_gift_alliances(self, interaction: discord.Interaction, alliance_ids):
        self.gift_operations_cursor.execute(
            "DELETE FROM auto_gift_alliances WHERE guild_id = ?",
            (interaction.guild_id,)
        )
        self.gift_operations_cursor.executemany(
            """
            INSERT OR IGNORE INTO auto_gift_alliances (guild_id, alliance_id)
            VALUES (?, ?)
            """,
            [(interaction.guild_id, alliance_id) for alliance_id in alliance_ids]
        )
        self.gift_operations_conn.commit()
        await interaction.response.send_message(f"✅ Auto gift alliances updated. Enabled: `{len(alliance_ids)}`.", ephemeral=True)

    def extract_auto_gift_code(self, content: str):
        content = content.strip()
        if not content:
            return None

        code_match = re.search(r"Code:\s*(\S+)", content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()

        if re.fullmatch(r"[A-Za-z0-9]+", content):
            return content

        return None

    def get_auto_gift_channel_id(self, guild_id: int):
        self.gift_operations_cursor.execute(
            "SELECT channel_id FROM auto_gift_settings WHERE guild_id = ?",
            (guild_id,)
        )
        row = self.gift_operations_cursor.fetchone()
        return row[0] if row else None

    def get_auto_gift_results_channel_id(self, guild_id: int):
        self.gift_operations_cursor.execute(
            "SELECT results_channel_id FROM auto_gift_settings WHERE guild_id = ?",
            (guild_id,)
        )
        row = self.gift_operations_cursor.fetchone()
        return row[0] if row else None

    def get_guild_alliances(self, guild_id: int):
        self.alliance_cursor.execute(
            """
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
            """,
            (guild_id,)
        )
        return self.alliance_cursor.fetchall()

    def get_enabled_auto_gift_alliances_for_guild(self, guild_id: int):
        alliances = self.get_guild_alliances(guild_id)
        self.gift_operations_cursor.execute(
            "SELECT alliance_id FROM auto_gift_alliances WHERE guild_id = ?",
            (guild_id,)
        )
        enabled_rows = self.gift_operations_cursor.fetchall()

        if not enabled_rows:
            return alliances

        enabled_ids = {row[0] for row in enabled_rows}
        return [(alliance_id, name) for alliance_id, name in alliances if alliance_id in enabled_ids]

    def get_auto_gift_results_channel(self, guild: discord.Guild, fallback_channel):
        results_channel_id = self.get_auto_gift_results_channel_id(guild.id)
        results_channel = guild.get_channel(results_channel_id) if results_channel_id else fallback_channel
        if results_channel is None:
            results_channel = fallback_channel
        return results_channel

    async def redeem_auto_gift_codes(self, guild_id: int, gift_codes):
        alliances = self.get_enabled_auto_gift_alliances_for_guild(guild_id)
        total_success = 0
        total_failed = 0
        processed_alliances = 0
        processed_codes = 0

        for gift_code in gift_codes:
            processed_codes += 1
            for alliance_id, alliance_name in alliances:
                with sqlite3.connect('db/users.sqlite') as users_conn:
                    users_cursor = users_conn.cursor()
                    users_cursor.execute("SELECT fid FROM users WHERE alliance = ?", (alliance_id,))
                    members = users_cursor.fetchall()

                if members:
                    processed_alliances += 1

                for (fid,) in members:
                    ok, result = await self.redeem_gift_code_for_fid(fid, gift_code)
                    if ok:
                        total_success += 1
                    else:
                        total_failed += 1
                    await asyncio.sleep(1)

        return {
            "alliances": alliances,
            "processed_codes": processed_codes,
            "processed_alliances": processed_alliances,
            "total_success": total_success,
            "total_failed": total_failed
        }

    async def scan_gift_code_channel(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        configured_channel_id = self.get_auto_gift_channel_id(interaction.guild_id)
        if not configured_channel_id:
            await interaction.response.send_message("❌ Gift code channel is not configured.", ephemeral=True)
            return

        gift_channel = interaction.guild.get_channel(configured_channel_id)
        if gift_channel is None:
            await interaction.response.send_message("❌ Configured gift code channel was not found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        found_codes = []
        async for message in gift_channel.history(limit=50):
            gift_code = self.extract_auto_gift_code(message.content)
            if gift_code and gift_code not in found_codes:
                found_codes.append(gift_code)

        results_channel = self.get_auto_gift_results_channel(interaction.guild, gift_channel)

        if not found_codes:
            embed = discord.Embed(
                title="🔍 Gift Code Channel Scan Complete",
                description="No gift codes found in the last 50 messages.",
                color=discord.Color.orange()
            )
            await results_channel.send(embed=embed)
            await interaction.followup.send("✅ Scan complete. No gift codes found.", ephemeral=True)
            return

        results = await self.redeem_auto_gift_codes(interaction.guild_id, found_codes)
        embed = discord.Embed(
            title="🔍 Gift Code Channel Scan Complete",
            color=discord.Color.green() if results["total_failed"] == 0 else discord.Color.orange()
        )
        embed.add_field(name="Codes Found", value=f"`{len(found_codes)}`", inline=True)
        embed.add_field(name="Codes Processed", value=f"`{results['processed_codes']}`", inline=True)
        embed.add_field(name="Total Succeeded", value=f"`{results['total_success']}`", inline=True)
        embed.add_field(name="Total Failed", value=f"`{results['total_failed']}`", inline=True)
        await results_channel.send(embed=embed)
        await interaction.followup.send("✅ Gift code channel scan complete.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        try:
            configured_channel_id = self.get_auto_gift_channel_id(message.guild.id)
            if not configured_channel_id or message.channel.id != configured_channel_id:
                return

            gift_code = self.extract_auto_gift_code(message.content)
            if not gift_code:
                return

            results_channel = self.get_auto_gift_results_channel(message.guild, message.channel)
            results = await self.redeem_auto_gift_codes(message.guild.id, [gift_code])
            if not results["alliances"]:
                await results_channel.send("❌ No enabled alliances found for auto gift redemption.")
                return

            embed = discord.Embed(
                title="🎁 Auto Gift Code Redemption Complete",
                color=discord.Color.green() if results["total_failed"] == 0 else discord.Color.orange()
            )
            embed.add_field(name="Gift Code Used", value=f"`{gift_code}`", inline=False)
            embed.add_field(name="Alliances Processed", value=f"`{results['processed_alliances']}`", inline=True)
            embed.add_field(name="Total Succeeded", value=f"`{results['total_success']}`", inline=True)
            embed.add_field(name="Total Failed", value=f"`{results['total_failed']}`", inline=True)
            await results_channel.send(embed=embed)

        except Exception as e:
            print(f"[ERROR] Auto gift code redemption failed: {e}")
            traceback.print_exc()

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
        await self.cog.show_auto_gift_settings(interaction)

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


class AutoGiftSettingsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Set Gift Code Channel", emoji="📢", style=discord.ButtonStyle.primary, row=0)
    async def set_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📢 Select Gift Code Channel",
            description="Choose the channel where auto gift codes will be detected.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=AutoGiftChannelSelectView(self.cog), ephemeral=True)

    @discord.ui.button(label="Set Results Channel", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def set_results_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📊 Select Results Channel",
            description="Choose the channel where auto gift redemption results will be posted.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=AutoGiftResultsChannelSelectView(self.cog), ephemeral=True)

    @discord.ui.button(label="Configure Alliances", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
    async def configure_alliances_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return
        await self.cog.show_auto_gift_alliance_select(interaction)

    @discord.ui.button(label="Scan Gift Code Channel", emoji="🔍", style=discord.ButtonStyle.success, row=1)
    async def scan_gift_code_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.scan_gift_code_channel(interaction)




class AutoGiftChannelSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(AutoGiftChannelSelect(cog))


class AutoGiftChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        super().__init__(
            placeholder="Select gift code channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        channel = self.values[0]
        await self.cog.save_auto_gift_channel(interaction, channel)


class AutoGiftResultsChannelSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(AutoGiftResultsChannelSelect(cog))


class AutoGiftResultsChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        super().__init__(
            placeholder="Select results channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        channel = self.values[0]
        await self.cog.save_auto_gift_results_channel(interaction, channel)


class AutoGiftAllianceSelectView(discord.ui.View):
    def __init__(self, cog, alliances, enabled_alliances):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(AutoGiftAllianceSelect(cog, alliances, enabled_alliances))


class AutoGiftAllianceSelect(discord.ui.Select):
    def __init__(self, cog, alliances, enabled_alliances):
        self.cog = cog
        options = [
            discord.SelectOption(
                label=name[:100],
                value=str(alliance_id),
                default=alliance_id in enabled_alliances
            )
            for alliance_id, name in alliances[:25]
        ]
        super().__init__(
            placeholder="Select enabled auto gift alliances",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        alliance_ids = [int(value) for value in self.values]
        await self.cog.save_auto_gift_alliances(interaction, alliance_ids)


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