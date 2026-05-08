import discord
from discord.ext import commands
import aiohttp
import asyncio
import hashlib
import sqlite3
import ssl
import traceback
from datetime import datetime
from cogs.permissions import check_permission
from paths import *

class OtherFeatures(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def upsert_api_pull_member(self, fid, nickname, furnace_lv, kid, stove_lv_content, alliance_id):
        with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
            users_conn.execute(
                """
                UPDATE users
                SET nickname = ?,
                    furnace_lv = ?,
                    kid = ?,
                    stove_lv_content = ?
                WHERE fid = ? AND alliance = ?
                """,
                (nickname, furnace_lv, kid, stove_lv_content, fid, alliance_id)
            )
            users_conn.commit()

    async def fetch_player_info(self, gift_cog, fid: int):
        time_val = int(datetime.utcnow().timestamp())
        form = f"fid={fid}&time={time_val}"
        sign = hashlib.md5((form + gift_cog.wos_encrypt_key).encode('utf-8')).hexdigest()
        form_data = f"fid={fid}&sign={sign}&time={time_val}"
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded",
            "origin": gift_cog.wos_giftcode_redemption_url,
            "referer": f"{gift_cog.wos_giftcode_redemption_url}/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(gift_cog.wos_player_info_url, headers=headers, data=form_data) as response:
                data = await response.json()
                return data.get('data', {})

    async def show_api_pull_alliance_select(self, interaction: discord.Interaction):
        try:
            if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
                await interaction.response.send_message("❌ Only admins can run the API pull.", ephemeral=True)
                return

            gift_cog = self.bot.get_cog("GiftOperations")
            if not gift_cog or not hasattr(gift_cog, "get_guild_alliances"):
                await interaction.response.send_message("❌ Gift Operations module not found.", ephemeral=True)
                return

            alliances = gift_cog.get_guild_alliances(interaction.guild_id)

            if not alliances:
                await interaction.response.send_message("❌ No alliances found for this server.", ephemeral=True)
                return

            embed = discord.Embed(
                title="🌐 API Pull Alliance Members",
                description="Choose one alliance to refresh from the API.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=ApiPullAllianceSelectView(self, alliances), ephemeral=True)
        except Exception:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while loading API Pull alliances.", ephemeral=True)
            else:
                await interaction.followup.send("❌ An error occurred while loading API Pull alliances.", ephemeral=True)

    async def pull_alliance_members_from_api(self, interaction: discord.Interaction, alliance_id: int, alliance_name: str):
        try:
            if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
                await interaction.followup.send("❌ Only admins can run the API pull.", ephemeral=True)
                return

            gift_cog = self.bot.get_cog("GiftOperations")
            if not gift_cog:
                await interaction.followup.send("❌ Gift Operations module not found.", ephemeral=True)
                return

            with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
                users_cursor = users_conn.cursor()
                users_cursor.execute(
                    "SELECT fid, nickname, furnace_lv, kid, stove_lv_content FROM users WHERE alliance = ?",
                    (alliance_id,)
                )
                members = users_cursor.fetchall()

            if not members:
                await interaction.followup.send(f"❌ No stored members found for `{alliance_name}`.", ephemeral=True)
                return

            updated = 0
            unchanged = 0
            failed = 0

            for fid, old_nickname, old_furnace_lv, old_kid, old_stove_lv_content in members:
                try:
                    player = await self.fetch_player_info(gift_cog, fid)
                    if not player:
                        failed += 1
                        continue

                    new_nickname = player.get('nickname') or old_nickname
                    new_furnace_lv = player.get('stove_lv') if player.get('stove_lv') is not None else old_furnace_lv
                    new_kid = player.get('kid') if player.get('kid') is not None else old_kid
                    new_stove_lv_content = player.get('stove_lv_content') or old_stove_lv_content

                    if (
                        new_nickname != old_nickname
                        or new_furnace_lv != old_furnace_lv
                        or new_kid != old_kid
                        or new_stove_lv_content != old_stove_lv_content
                    ):
                        updated += 1
                    else:
                        unchanged += 1

                    self.upsert_api_pull_member(
                        fid,
                        new_nickname,
                        new_furnace_lv,
                        new_kid,
                        new_stove_lv_content,
                        alliance_id
                    )
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"[API PULL] Error fetching fid={fid}: {e}")
                    failed += 1

            embed = discord.Embed(
                title="✅ API Pull Complete",
                description=f"Alliance: `{alliance_name}`",
                color=discord.Color.green() if failed == 0 else discord.Color.orange()
            )
            embed.add_field(name="Updated", value=f"`{updated}`", inline=True)
            embed.add_field(name="Unchanged", value=f"`{unchanged}`", inline=True)
            embed.add_field(name="Failed", value=f"`{failed}`", inline=True)
            embed.set_footer(text=f"Processed {len(members)} stored member(s)")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred during API Pull Alliance Members.", ephemeral=True)
            else:
                await interaction.followup.send("❌ An error occurred during API Pull Alliance Members.", ephemeral=True)
        
    async def show_other_features_menu(self, interaction: discord.Interaction):
        try:
            embed = discord.Embed(
                title="🔧 Other Features",
                description=(
                    "This section was created according to users' requests:\n\n"
                    "**Available Operations**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🆔 **FID Number Lookup**\n"
                    "└ Create and manage FID lookup channels\n"
                    "└ Automatic ID verification system\n"
                    "└ Custom channel settings\n\n"
                    "💾 **Backup System**\n"
                    "└ Automatic database backup\n"
                    "└ Secure backup storage\n"
                    "└ Only for Global Admins\n\n"
                    "📊 **Member Scan**\n"
                    "└ Manually scan all alliance members\n"
                    "└ Checks for name and furnace changes\n"
                    "└ Posts results to each alliance results channel\n\n"
                    "🌐 **API Pull Alliance Members**\n"
                    "└ Refresh stored members for one alliance\n"
                    "└ Updates current API details in users table\n\n"
                    "🧪 **Redeem Diagnostics**\n"
                    "└ Manual admin test for gift code redemption\n"
                    "└ Run a one-off FID + code check\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.blue()
            )
            
            view = OtherFeaturesView(self)
            
            try:
                await interaction.response.edit_message(embed=embed, view=view)
            except discord.InteractionResponded:
                pass
                
        except Exception as e:
            print(f"Error in show_other_features_menu: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred. Please try again.",
                    ephemeral=True
                )

class OtherFeaturesView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="FID Number Lookup",
        emoji="🆔",
        style=discord.ButtonStyle.primary,
        custom_id="id_channel",
        row=0
    )
    async def id_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            id_channel_cog = self.cog.bot.get_cog("IDChannel")
            if id_channel_cog:
                await id_channel_cog.show_id_channel_menu(interaction)
            else:
                await interaction.response.send_message(
                    "❌ ID Channel module not found.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Error loading ID Channel menu: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while loading ID Channel menu.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Backup System",
        emoji="💾",
        style=discord.ButtonStyle.primary,
        custom_id="backup_system",
        row=1
    )
    async def backup_system_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            backup_cog = self.cog.bot.get_cog("BackupOperations")
            if backup_cog:
                await backup_cog.show_backup_menu(interaction)
            else:
                await interaction.response.send_message(
                    "❌ Backup System module not found.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Error loading Backup System menu: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while loading Backup System menu.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Member Scan",
        emoji="📊",
        style=discord.ButtonStyle.primary,
        custom_id="member_scan",
        row=1
    )
    async def member_scan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins can run the member scan.", ephemeral=True)
            return
        gift_cog = self.cog.bot.get_cog("GiftOperations")
        if not gift_cog:
            await interaction.response.send_message("❌ Gift Operations module not found.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await gift_cog.run_member_scan(label="Manual")
        await interaction.followup.send("✅ Member scan complete. Results posted to each alliance's results channel.", ephemeral=True)

    @discord.ui.button(
        label="API Pull Alliance Members",
        emoji="🌐",
        style=discord.ButtonStyle.primary,
        custom_id="api_pull_alliance_members",
        row=2
    )
    async def api_pull_alliance_members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_api_pull_alliance_select(interaction)

    @discord.ui.button(
        label="Redeem Diagnostics",
        emoji="🧪",
        style=discord.ButtonStyle.primary,
        custom_id="redeem_diagnostics",
        row=2
    )
    async def redeem_diagnostics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins can use Redeem Diagnostics.", ephemeral=True)
            return
        gift_cog = self.cog.bot.get_cog("GiftOperations")
        if not gift_cog:
            await interaction.response.send_message("❌ Gift Operations module not found.", ephemeral=True)
            return
        await gift_cog.show_redeem_diagnostics_menu(interaction)

    @discord.ui.button(
        label="Main Menu",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        custom_id="main_menu",
        row=3
    )
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            alliance_cog = self.cog.bot.get_cog("Alliance")
            if alliance_cog:
                await alliance_cog.show_main_menu(interaction)
        except Exception as e:
            print(f"Error returning to main menu: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while returning to main menu.",
                ephemeral=True
            )

class ApiPullAllianceSelectView(discord.ui.View):
    def __init__(self, cog, alliances):
        super().__init__(timeout=180)
        self.add_item(ApiPullAllianceSelect(cog, alliances))

class ApiPullAllianceSelect(discord.ui.Select):
    def __init__(self, cog, alliances):
        self.cog = cog
        self.alliance_names = {str(alliance_id): name for alliance_id, name in alliances[:25]}
        options = [
            discord.SelectOption(label=name[:100], value=str(alliance_id))
            for alliance_id, name in alliances[:25]
        ]
        super().__init__(
            placeholder="Select an alliance to refresh",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            alliance_id = int(self.values[0])
            alliance_name = self.alliance_names.get(self.values[0], f"Alliance {alliance_id}")
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.cog.pull_alliance_members_from_api(interaction, alliance_id, alliance_name)
        except Exception:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while starting API Pull Alliance Members.", ephemeral=True)
            else:
                await interaction.followup.send("❌ An error occurred while starting API Pull Alliance Members.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(OtherFeatures(bot)) 
