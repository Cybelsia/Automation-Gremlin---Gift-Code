import discord
from discord import app_commands
from discord.ext import commands
import sqlite3  
import asyncio
import traceback
from datetime import datetime
from cogs.permissions import check_permission

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
                discord_server_id INTEGER,
                refresh_rate INTEGER
            )
        """)
        self.conn.commit()

    def _check_and_add_column(self):
        self.c.execute("PRAGMA table_info(alliance_list)")
        columns = [info[1] for info in self.c.fetchall()]
        if "discord_server_id" not in columns:
            self.c.execute("ALTER TABLE alliance_list ADD COLUMN discord_server_id INTEGER")
            self.conn.commit()
        if "refresh_rate" not in columns:
            self.c.execute("ALTER TABLE alliance_list ADD COLUMN refresh_rate INTEGER")
            self.conn.commit()
        if "gift_code_channel_id" not in columns:
            self.c.execute("ALTER TABLE alliance_list ADD COLUMN gift_code_channel_id INTEGER")
            self.conn.commit()
        if "results_channel_id" not in columns:
            self.c.execute("ALTER TABLE alliance_list ADD COLUMN results_channel_id INTEGER")
            self.conn.commit()

    @app_commands.command(name="settings", description="Open settings menu.")
    async def settings(self, interaction: discord.Interaction):
        try:
            if not check_permission(interaction.user.id, interaction.guild_id, "mod"):
                await interaction.response.send_message("❌ You don't have permission to use settings.", ephemeral=True)
                return

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
                    "➕ **Add New Alliance**\n"
                    "└ Register a new alliance\n\n"
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
            if interaction.guild_id is None:
                await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
                return

            self.c.execute(
                """
                SELECT alliance_id, name, discord_server_id
                FROM alliance_list
                WHERE discord_server_id = ?
                ORDER BY name
                """,
                (interaction.guild_id,)
            )
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

    async def show_add_alliance_modal(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ You need admin permissions to create an alliance.", ephemeral=True)
            return
        try:
            print(f"[DEBUG] Opening AddAllianceModal guild_id={interaction.guild_id} user_id={interaction.user.id}")
            await interaction.response.send_modal(AddAllianceModal(self))
        except Exception as e:
            print(f"[ERROR] Failed to open AddAllianceModal: {e}")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while opening the alliance modal.", ephemeral=True)

    async def show_edit_alliance_select(self, interaction: discord.Interaction):
        try:
            if interaction.guild_id is None:
                await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
                return
            self.c.execute(
                """
                SELECT alliance_id, name, refresh_rate, gift_code_channel_id, results_channel_id
                FROM alliance_list
                WHERE discord_server_id = ?
                ORDER BY name
                """,
                (interaction.guild_id,)
            )
            alliances = self.c.fetchall()
            if not alliances:
                await interaction.response.send_message("❌ No alliances found to edit.", ephemeral=True)
                return
            embed = discord.Embed(
                title="✏️ Edit Alliance",
                description="Select an alliance to edit.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=EditAllianceSelectView(self, alliances), ephemeral=True)
        except Exception as e:
            print(f"[ERROR] show_edit_alliance_select: {e}")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while loading alliances.", ephemeral=True)

    async def show_edit_alliance_menu(self, interaction: discord.Interaction, alliance_id: int, name: str, refresh_rate, gift_code_channel_id, results_channel_id):
        gift_ch = f"<#{gift_code_channel_id}>" if gift_code_channel_id else "`Not set`"
        results_ch = f"<#{results_channel_id}>" if results_channel_id else "`Not set`"
        embed = discord.Embed(
            title=f"✏️ Editing: {name}",
            description="Choose what you want to update.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Refresh Rate", value=f"`{refresh_rate}` seconds" if refresh_rate else "`Not set`", inline=False)
        embed.add_field(name="Gift Code Channel", value=gift_ch, inline=False)
        embed.add_field(name="Results Channel", value=results_ch, inline=False)
        await interaction.response.edit_message(
            embed=embed,
            view=EditAllianceMenuView(self, alliance_id, name, refresh_rate, gift_code_channel_id, results_channel_id)
        )

    async def show_delete_alliance_select(self, interaction: discord.Interaction):
        try:
            if interaction.guild_id is None:
                await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
                return

            self.c.execute(
                """
                SELECT alliance_id, name
                FROM alliance_list
                WHERE discord_server_id = ?
                ORDER BY name
                """,
                (interaction.guild_id,)
            )
            alliances = self.c.fetchall()

            if not alliances:
                await interaction.response.send_message("❌ No alliances found to delete.", ephemeral=True)
                return

            embed = discord.Embed(
                title="🗑️ Delete Alliance",
                description="Select an alliance to delete.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, view=DeleteAllianceSelectView(self, alliances), ephemeral=True)
        except Exception as e:
            print(f"[ERROR] Failed to show delete alliance select guild_id={interaction.guild_id}: {e}")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while loading alliances.", ephemeral=True)

    async def confirm_delete_alliance(self, interaction: discord.Interaction, alliance_id: int, alliance_name: str):
        embed = discord.Embed(
            title="⚠️ Confirm Alliance Deletion",
            description=(
                f"Are you sure you want to delete `{alliance_name}`?\n\n"
                "This will also remove all members assigned to this alliance."
            ),
            color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=ConfirmDeleteAllianceView(self, alliance_id, alliance_name))

    async def delete_alliance(self, interaction: discord.Interaction, alliance_id: int, alliance_name: str):
        try:
            self.c.execute(
                "DELETE FROM alliance_list WHERE alliance_id = ? AND discord_server_id = ?",
                (alliance_id, interaction.guild_id)
            )
            deleted_alliances = self.c.rowcount
            self.conn.commit()

            self.c_users.execute("DELETE FROM users WHERE alliance = ?", (alliance_id,))
            deleted_members = self.c_users.rowcount
            self.conn_users.commit()

            if deleted_alliances == 0:
                await interaction.response.edit_message(content="❌ Alliance not found.", embed=None, view=None)
                return

            embed = discord.Embed(
                title="✅ Alliance Deleted",
                description=f"Deleted `{alliance_name}` and removed `{deleted_members}` member(s).",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            print(f"[ERROR] Failed to delete alliance alliance_id={alliance_id}: {e}")
            traceback.print_exc()
            await interaction.response.edit_message(content="❌ An error occurred while deleting the alliance.", embed=None, view=None)


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

    @discord.ui.button(label="Add New Alliance", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add_alliance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[DEBUG] Add New Alliance button clicked guild_id={interaction.guild_id} user_id={interaction.user.id}")
        await self.cog.show_add_alliance_modal(interaction)

    @discord.ui.button(label="View Alliances", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def view_alliances_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_alliances(interaction)

    @discord.ui.button(label="Edit Alliance", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
    async def edit_alliance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_edit_alliance_select(interaction)

    @discord.ui.button(label="Delete Alliance", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete_alliance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_delete_alliance_select(interaction)

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_main_menu(interaction)


class EditAllianceSelectView(discord.ui.View):
    def __init__(self, cog, alliances):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(EditAllianceSelect(cog, alliances))


class EditAllianceSelect(discord.ui.Select):
    def __init__(self, cog, alliances):
        self.cog = cog
        self.alliance_data = {str(a[0]): a for a in alliances[:25]}
        options = [
            discord.SelectOption(label=a[1][:100], value=str(a[0]))
            for a in alliances[:25]
        ]
        super().__init__(placeholder="Select an alliance to edit", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        a = self.alliance_data[self.values[0]]
        alliance_id, name, refresh_rate, gift_code_channel_id, results_channel_id = a
        await self.cog.show_edit_alliance_menu(interaction, alliance_id, name, refresh_rate, gift_code_channel_id, results_channel_id)


class EditAllianceMenuView(discord.ui.View):
    def __init__(self, cog, alliance_id: int, name: str, refresh_rate, gift_code_channel_id, results_channel_id):
        super().__init__(timeout=300)
        self.cog = cog
        self.alliance_id = alliance_id
        self.name = name
        self.refresh_rate = refresh_rate
        self.gift_code_channel_id = gift_code_channel_id
        self.results_channel_id = results_channel_id

    @discord.ui.button(label="Edit Name / Refresh Rate", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit_name_refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            EditAllianceModal(self.cog, self.alliance_id, self.name, self.refresh_rate)
        )

    @discord.ui.button(label="Set Gift Code Channel", emoji="📢", style=discord.ButtonStyle.primary, row=0)
    async def edit_gift_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📢 Select Gift Code Channel",
            description="Choose the channel where gift codes will be picked up.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=EditGiftCodeChannelView(self.cog, self.alliance_id, self.name))

    @discord.ui.button(label="Set Results Channel", emoji="📊", style=discord.ButtonStyle.primary, row=1)
    async def edit_results_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📊 Select Results Channel",
            description="Choose the channel where redemption results will be posted.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=EditResultsChannelView(self.cog, self.alliance_id, self.name))


class EditAllianceModal(discord.ui.Modal, title="Edit Alliance"):
    alliance_name = discord.ui.TextInput(label="Alliance Name", placeholder="Enter new name", max_length=100)
    refresh_rate = discord.ui.TextInput(label="Refresh Rate (seconds)", placeholder="e.g. 3600", max_length=20)

    def __init__(self, cog, alliance_id: int, current_name: str, current_refresh_rate):
        super().__init__()
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name.default = current_name
        self.refresh_rate.default = str(current_refresh_rate) if current_refresh_rate else ""

    async def on_submit(self, interaction: discord.Interaction):
        name = str(self.alliance_name.value).strip()
        refresh_rate_value = str(self.refresh_rate.value).strip()
        if not name:
            await interaction.response.send_message("❌ Alliance name is required.", ephemeral=True)
            return
        if not refresh_rate_value.isdigit() or int(refresh_rate_value) <= 0:
            await interaction.response.send_message("❌ Refresh rate must be a positive number of seconds.", ephemeral=True)
            return
        try:
            self.cog.c.execute(
                "UPDATE alliance_list SET name = ?, refresh_rate = ? WHERE alliance_id = ?",
                (name, int(refresh_rate_value), self.alliance_id)
            )
            self.cog.conn.commit()
            embed = discord.Embed(
                title="✅ Alliance Updated",
                color=discord.Color.green()
            )
            embed.add_field(name="Name", value=f"`{name}`", inline=False)
            embed.add_field(name="Refresh Rate", value=f"`{refresh_rate_value}` seconds", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except sqlite3.IntegrityError:
            await interaction.response.send_message("❌ An alliance with that name already exists.", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] EditAllianceModal: {e}")
            traceback.print_exc()
            await interaction.response.send_message("❌ An error occurred while updating the alliance.", ephemeral=True)


class EditGiftCodeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog, alliance_id: int, alliance_name: str):
        super().__init__(placeholder="Select gift code channel", min_values=1, max_values=1, channel_types=[discord.ChannelType.text])
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name = alliance_name

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.c.execute(
            "UPDATE alliance_list SET gift_code_channel_id = ? WHERE alliance_id = ?",
            (channel.id, self.alliance_id)
        )
        self.cog.conn.commit()
        embed = discord.Embed(
            title="✅ Gift Code Channel Updated",
            description=f"`{self.alliance_name}` will now pick up codes from {channel.mention}.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class EditGiftCodeChannelView(discord.ui.View):
    def __init__(self, cog, alliance_id: int, alliance_name: str):
        super().__init__(timeout=180)
        self.add_item(EditGiftCodeChannelSelect(cog, alliance_id, alliance_name))


class EditResultsChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog, alliance_id: int, alliance_name: str):
        super().__init__(placeholder="Select results channel", min_values=1, max_values=1, channel_types=[discord.ChannelType.text])
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name = alliance_name

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.c.execute(
            "UPDATE alliance_list SET results_channel_id = ? WHERE alliance_id = ?",
            (channel.id, self.alliance_id)
        )
        self.cog.conn.commit()
        embed = discord.Embed(
            title="✅ Results Channel Updated",
            description=f"`{self.alliance_name}` will now post results to {channel.mention}.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class EditResultsChannelView(discord.ui.View):
    def __init__(self, cog, alliance_id: int, alliance_name: str):
        super().__init__(timeout=180)
        self.add_item(EditResultsChannelSelect(cog, alliance_id, alliance_name))


class DeleteAllianceSelectView(discord.ui.View):
    def __init__(self, cog, alliances):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(DeleteAllianceSelect(cog, alliances))


class DeleteAllianceSelect(discord.ui.Select):
    def __init__(self, cog, alliances):
        self.cog = cog
        options = [
            discord.SelectOption(label=name[:100], value=str(alliance_id))
            for alliance_id, name in alliances[:25]
        ]
        self.alliance_names = {str(alliance_id): name for alliance_id, name in alliances[:25]}
        super().__init__(
            placeholder="Select an alliance to delete",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        alliance_id = int(self.values[0])
        alliance_name = self.alliance_names.get(self.values[0], f"Alliance {alliance_id}")
        await self.cog.confirm_delete_alliance(interaction, alliance_id, alliance_name)


class ConfirmDeleteAllianceView(discord.ui.View):
    def __init__(self, cog, alliance_id: int, alliance_name: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name = alliance_name

    @discord.ui.button(label="Confirm Delete", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.delete_alliance(interaction, self.alliance_id, self.alliance_name)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Deletion cancelled.", embed=None, view=None)


class AddAllianceModal(discord.ui.Modal, title="Add New Alliance"):
    alliance_name = discord.ui.TextInput(
        label="Alliance Name",
        placeholder="Enter alliance name",
        max_length=100
    )
    refresh_rate = discord.ui.TextInput(
        label="Refresh Rate",
        placeholder="Enter refresh rate in seconds, e.g. 3600",
        max_length=20
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        name = str(self.alliance_name.value).strip()
        refresh_rate_value = str(self.refresh_rate.value).strip()
        print(f"[DEBUG] AddAllianceModal submitted guild_id={interaction.guild_id} user_id={interaction.user.id} name={name} refresh_rate={refresh_rate_value}")

        if not name:
            await interaction.response.send_message("❌ Alliance name is required.", ephemeral=True)
            return

        if not refresh_rate_value.isdigit() or int(refresh_rate_value) <= 0:
            await interaction.response.send_message("❌ Refresh rate must be a positive number of seconds.", ephemeral=True)
            return

        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
            return

        try:
            self.cog.c.execute(
                "INSERT INTO alliance_list (name, discord_server_id, refresh_rate) VALUES (?, ?, ?)",
                (name, interaction.guild_id, int(refresh_rate_value))
            )
            self.cog.conn.commit()
            alliance_id = self.cog.c.lastrowid
            print(f"[DEBUG] Added alliance guild_id={interaction.guild_id} name={name} alliance_id={alliance_id}")
            embed = discord.Embed(
                title="✅ Alliance Added — Step 2 of 3",
                description=f"Alliance `{name}` created. Now select the **gift code channel** where codes will be picked up.",
                color=discord.Color.gold()
            )
            embed.add_field(name="Refresh Rate", value=f"`{refresh_rate_value}` seconds", inline=False)
            await interaction.response.send_message(
                embed=embed,
                view=AllianceGiftCodeChannelSetupView(self.cog, alliance_id, name, int(refresh_rate_value)),
                ephemeral=True
            )
        except sqlite3.IntegrityError as e:
            print(f"[ERROR] Alliance INSERT integrity error guild_id={interaction.guild_id} name={name}: {e}")
            traceback.print_exc()
            await interaction.response.send_message("❌ An alliance with that name already exists.", ephemeral=True)
        except Exception as e:
            print(f"[ERROR] Alliance INSERT failed guild_id={interaction.guild_id} name={name}: {e}")
            traceback.print_exc()
            await interaction.response.send_message("❌ An error occurred while adding the alliance.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[ERROR] AddAllianceModal.on_error guild_id={interaction.guild_id} user_id={interaction.user.id}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while submitting the alliance modal.", ephemeral=True)

class PaginatedChannelView(discord.ui.View):
    def __init__(self, channels, original_callback):
        super().__init__(timeout=300)
        self.channels = channels
        self.original_callback = original_callback


class AllianceGiftCodeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog, alliance_id: int, alliance_name: str, refresh_rate: int):
        super().__init__(
            placeholder="Select gift code channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name = alliance_name
        self.refresh_rate = refresh_rate

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.c.execute(
            "UPDATE alliance_list SET gift_code_channel_id = ? WHERE alliance_id = ?",
            (channel.id, self.alliance_id)
        )
        self.cog.conn.commit()
        print(f"[DEBUG] Set gift_code_channel_id={channel.id} for alliance_id={self.alliance_id}")
        embed = discord.Embed(
            title="✅ Gift Code Channel Set — Step 3 of 3",
            description=f"Gift code channel set to {channel.mention}. Now select the **results channel** where redemption results will be posted.",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(
            embed=embed,
            view=AllianceResultsChannelSetupView(self.cog, self.alliance_id, self.alliance_name, self.refresh_rate, channel.id)
        )


class AllianceGiftCodeChannelSetupView(discord.ui.View):
    def __init__(self, cog, alliance_id: int, alliance_name: str, refresh_rate: int):
        super().__init__(timeout=300)
        self.add_item(AllianceGiftCodeChannelSelect(cog, alliance_id, alliance_name, refresh_rate))


class AllianceResultsChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog, alliance_id: int, alliance_name: str, refresh_rate: int, gift_code_channel_id: int):
        super().__init__(
            placeholder="Select results channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.cog = cog
        self.alliance_id = alliance_id
        self.alliance_name = alliance_name
        self.refresh_rate = refresh_rate
        self.gift_code_channel_id = gift_code_channel_id

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.c.execute(
            "UPDATE alliance_list SET results_channel_id = ? WHERE alliance_id = ?",
            (channel.id, self.alliance_id)
        )
        self.cog.conn.commit()
        print(f"[DEBUG] Set results_channel_id={channel.id} for alliance_id={self.alliance_id}")
        embed = discord.Embed(
            title="✅ Alliance Setup Complete",
            description=f"Alliance `{self.alliance_name}` is fully configured.",
            color=discord.Color.green()
        )
        embed.add_field(name="Refresh Rate", value=f"`{self.refresh_rate}` seconds", inline=False)
        embed.add_field(name="Gift Code Channel", value=f"<#{self.gift_code_channel_id}>", inline=False)
        embed.add_field(name="Results Channel", value=channel.mention, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)


class AllianceResultsChannelSetupView(discord.ui.View):
    def __init__(self, cog, alliance_id: int, alliance_name: str, refresh_rate: int, gift_code_channel_id: int):
        super().__init__(timeout=300)
        self.add_item(AllianceResultsChannelSelect(cog, alliance_id, alliance_name, refresh_rate, gift_code_channel_id))


async def setup(bot):
    conn = sqlite3.connect('db/alliance.sqlite')
    await bot.add_cog(Alliance(bot, conn))