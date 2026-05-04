import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
import requests
from .alliance_member_operations import AllianceSelectView
from cogs.permissions import check_permission

VERSION_URL = "https://raw.githubusercontent.com/Reloisback/Whiteout-Survival-Discord-Bot/refs/heads/main/autoupdateinfo.txt"

BOT_OWNER_ID = 1237812594140512347

class BotOperations(commands.Cog):
    def __init__(self, bot, conn):
        self.bot = bot
        self.conn = conn
        self.settings_db = sqlite3.connect('db/settings.sqlite', check_same_thread=False)
        self.settings_cursor = self.settings_db.cursor()
        self.alliance_db = sqlite3.connect('db/alliance.sqlite', check_same_thread=False)
        self.c_alliance = self.alliance_db.cursor()

    def __del__(self):
        try:
            self.settings_db.close()
            self.alliance_db.close()
        except:
            pass

    def is_owner(self, user_id: int) -> bool:
        return user_id == BOT_OWNER_ID

    async def show_bot_operations_menu(self, interaction: discord.Interaction):
        try:
            if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
                await interaction.response.send_message("❌ You don't have permission to use bot operations.", ephemeral=True)
                return

            embed = discord.Embed(
                title="🛡️ Admin Panel",
                description=(
                    "Please choose an operation:\n\n"
                    "**Available Operations**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👥 **Admin Management**\n"
                    "└ Add, remove, and view administrators\n\n"
                    "🔧 **Mod Management**\n"
                    "└ Add and remove server moderators\n\n"
                    "🔍 **Admin Permissions**\n"
                    "└ Assign alliances and manage permissions\n"
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
                label="Add Mod",
                emoji="➕",
                style=discord.ButtonStyle.success,
                custom_id="add_mod",
                row=2
            ))
            view.add_item(discord.ui.Button(
                label="Remove Mod",
                emoji="➖",
                style=discord.ButtonStyle.danger,
                custom_id="remove_mod",
                row=2
            ))
            view.add_item(discord.ui.Button(
                label="Assign Alliance to Admin",
                emoji="🔗",
                style=discord.ButtonStyle.success,
                custom_id="assign_alliance",
                row=3
            ))
            view.add_item(discord.ui.Button(
                label="Delete Admin Permissions",
                emoji="➖",
                style=discord.ButtonStyle.danger,
                custom_id="view_admin_permissions",
                row=3
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
                DELETE FROM permissions
                WHERE user_id = ? AND guild_id = ?
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

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")

        # ── Add Admin ─────────────────────────────────────────────
        if custom_id == "add_admin":
            if not self.is_owner(interaction.user.id):
                await interaction.response.send_message("❌ Only the bot owner can add admins.", ephemeral=True)
                return

            embed = discord.Embed(
                title="➕ Add Admin",
                description="Select a server member to appoint as admin:",
                color=discord.Color.green()
            )
            view = discord.ui.View(timeout=60)
            select = discord.ui.UserSelect(placeholder="Select a member", custom_id="add_admin_select")

            async def add_admin_callback(si: discord.Interaction):
                perms_cog = self.bot.get_cog("Permissions")
                if not perms_cog:
                    await si.response.send_message("❌ Permissions module not found.", ephemeral=True)
                    return
                user_id = int(list(si.data["resolved"]["users"].keys())[0])
                member = si.guild.get_member(user_id)
                if not member:
                    await si.response.send_message("❌ Could not find that member in this server.", ephemeral=True)
                    return
                msg = await perms_cog.do_admin_add(si.guild_id, member, si.user.id)
                await si.response.send_message(msg, ephemeral=True)

            select.callback = add_admin_callback
            view.add_item(select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── Remove Admin ──────────────────────────────────────────
        elif custom_id == "remove_admin":
            if not self.is_owner(interaction.user.id):
                await interaction.response.send_message("❌ Only the bot owner can remove admins.", ephemeral=True)
                return

            embed = discord.Embed(
                title="➖ Remove Admin",
                description="Select the admin to remove:",
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=60)
            select = discord.ui.UserSelect(placeholder="Select an admin to remove", custom_id="remove_admin_select")

            async def remove_admin_callback(si: discord.Interaction):
                perms_cog = self.bot.get_cog("Permissions")
                if not perms_cog:
                    await si.response.send_message("❌ Permissions module not found.", ephemeral=True)
                    return
                user_id = int(list(si.data["resolved"]["users"].keys())[0])
                member = si.guild.get_member(user_id)
                if not member:
                    await si.response.send_message("❌ Could not find that member in this server.", ephemeral=True)
                    return
                msg = await perms_cog.do_admin_remove(si.guild_id, member)
                await si.response.send_message(msg, ephemeral=True)

            select.callback = remove_admin_callback
            view.add_item(select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── View Administrators ───────────────────────────────────
        elif custom_id == "view_administrators":
            if not self.is_owner(interaction.user.id):
                await interaction.response.send_message("❌ Only the bot owner can view administrators.", ephemeral=True)
                return

            self.settings_cursor.execute(
                "SELECT user_id, appointed_by, created_at FROM permissions WHERE guild_id = ? AND role = 'admin'",
                (interaction.guild_id,)
            )
            rows = self.settings_cursor.fetchall()

            embed = discord.Embed(title="👥 Server Administrators", color=discord.Color.blue())

            if not rows:
                embed.description = "No admins assigned for this server."
            else:
                for user_id, appointed_by, created_at in rows:
                    # Get assigned alliances
                    self.settings_cursor.execute(
                        "SELECT alliance_id FROM admin_alliances WHERE guild_id = ? AND user_id = ?",
                        (interaction.guild_id, user_id)
                    )
                    alliance_rows = self.settings_cursor.fetchall()
                    if alliance_rows:
                        alliance_ids = [str(r[0]) for r in alliance_rows]
                        # Look up names
                        names = []
                        for aid in alliance_ids:
                            self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (aid,))
                            result = self.c_alliance.fetchone()
                            names.append(result[0] if result else f"ID {aid}")
                        alliance_str = ", ".join(names)
                    else:
                        alliance_str = "None assigned"

                    embed.add_field(
                        name=f"<@{user_id}> (`{user_id}`)",
                        value=(
                            f"Appointed by: <@{appointed_by}>\n"
                            f"Date: `{created_at}`\n"
                            f"Alliances: {alliance_str}"
                        ),
                        inline=False
                    )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        # ── Assign Alliance to Admin ───────────────────────────────
        elif custom_id == "assign_alliance":
            if not self.is_owner(interaction.user.id):
                await interaction.response.send_message("❌ Only the bot owner can assign alliances.", ephemeral=True)
                return

            # Step 1: pick the admin
            self.settings_cursor.execute(
                "SELECT user_id FROM permissions WHERE guild_id = ? AND role = 'admin'",
                (interaction.guild_id,)
            )
            admin_rows = self.settings_cursor.fetchall()
            if not admin_rows:
                await interaction.response.send_message("❌ No admins found for this server.", ephemeral=True)
                return

            embed = discord.Embed(
                title="🔗 Assign Alliance to Admin",
                description="Step 1: Select the admin to assign an alliance to:",
                color=discord.Color.green()
            )
            view = discord.ui.View(timeout=120)
            admin_select = discord.ui.UserSelect(placeholder="Select an admin", custom_id="assign_admin_select")

            async def admin_selected(si: discord.Interaction):
                selected_admin_id = int(list(si.data["resolved"]["users"].keys())[0])

                # Verify they are actually an admin
                self.settings_cursor.execute(
                    "SELECT role FROM permissions WHERE guild_id = ? AND user_id = ?",
                    (si.guild_id, selected_admin_id)
                )
                result = self.settings_cursor.fetchone()
                if not result or result[0] != "admin":
                    await si.response.send_message("❌ That user is not an admin on this server.", ephemeral=True)
                    return

                # Step 2: pick the alliance
                self.c_alliance.execute(
                    "SELECT alliance_id, name FROM alliance_list WHERE discord_server_id = ? ORDER BY name",
                    (si.guild_id,)
                )
                alliances = self.c_alliance.fetchall()
                if not alliances:
                    await si.response.send_message("❌ No alliances found for this server.", ephemeral=True)
                    return

                options = [
                    discord.SelectOption(label=name, value=str(aid))
                    for aid, name in alliances
                ]
                alliance_embed = discord.Embed(
                    title="🔗 Assign Alliance to Admin",
                    description=f"Step 2: Select the alliance to assign to <@{selected_admin_id}>:",
                    color=discord.Color.green()
                )
                alliance_view = discord.ui.View(timeout=120)
                alliance_select = discord.ui.Select(
                    placeholder="Select an alliance",
                    options=options,
                    custom_id="assign_alliance_select"
                )

                async def alliance_selected(si2: discord.Interaction):
                    alliance_id = int(si2.data["values"][0])
                    try:
                        self.settings_cursor.execute(
                            """
                            INSERT OR IGNORE INTO admin_alliances (guild_id, user_id, alliance_id)
                            VALUES (?, ?, ?)
                            """,
                            (si2.guild_id, selected_admin_id, alliance_id)
                        )
                        self.settings_db.commit()
                        self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
                        aname = self.c_alliance.fetchone()
                        aname = aname[0] if aname else str(alliance_id)
                        await si2.response.send_message(
                            f"✅ Alliance **{aname}** assigned to <@{selected_admin_id}>.",
                            ephemeral=True
                        )
                    except Exception as e:
                        print(f"Error assigning alliance: {e}")
                        await si2.response.send_message("❌ An error occurred while assigning the alliance.", ephemeral=True)

                alliance_select.callback = alliance_selected
                alliance_view.add_item(alliance_select)
                await si.response.send_message(embed=alliance_embed, view=alliance_view, ephemeral=True)

            admin_select.callback = admin_selected
            view.add_item(admin_select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── Delete Admin Permissions (sever alliance link) ─────────
        elif custom_id == "view_admin_permissions":
            if not self.is_owner(interaction.user.id):
                await interaction.response.send_message("❌ Only the bot owner can remove alliance assignments.", ephemeral=True)
                return

            self.settings_cursor.execute(
                """
                SELECT aa.user_id, aa.alliance_id
                FROM admin_alliances aa
                WHERE aa.guild_id = ?
                """,
                (interaction.guild_id,)
            )
            rows = self.settings_cursor.fetchall()
            if not rows:
                await interaction.response.send_message("❌ No alliance assignments found for this server.", ephemeral=True)
                return

            # Build select options: one per admin-alliance pair
            options = []
            for user_id, alliance_id in rows:
                self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
                aresult = self.c_alliance.fetchone()
                aname = aresult[0] if aresult else str(alliance_id)
                options.append(
                    discord.SelectOption(
                        label=f"<ID {user_id}> → {aname}",
                        description=f"User {user_id} | Alliance {aname}",
                        value=f"{user_id}:{alliance_id}"
                    )
                )

            embed = discord.Embed(
                title="➖ Delete Admin Permissions",
                description="Select an admin–alliance link to remove:",
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=60)
            select = discord.ui.Select(
                placeholder="Select a link to remove",
                options=options,
                custom_id="delete_admin_perm_select"
            )

            async def delete_perm_callback(si: discord.Interaction):
                value = si.data["values"][0]
                user_id, alliance_id = value.split(":")
                user_id, alliance_id = int(user_id), int(alliance_id)
                self.settings_cursor.execute(
                    "DELETE FROM admin_alliances WHERE guild_id = ? AND user_id = ? AND alliance_id = ?",
                    (si.guild_id, user_id, alliance_id)
                )
                self.settings_db.commit()
                self.c_alliance.execute("SELECT name FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
                aresult = self.c_alliance.fetchone()
                aname = aresult[0] if aresult else str(alliance_id)
                await si.response.send_message(
                    f"✅ Removed alliance **{aname}** from <@{user_id}>.",
                    ephemeral=True
                )

            select.callback = delete_perm_callback
            view.add_item(select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── Add Mod ───────────────────────────────────────────────
        elif custom_id == "add_mod":
            if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
                await interaction.response.send_message("❌ Only admins can add mods.", ephemeral=True)
                return

            embed = discord.Embed(
                title="➕ Add Mod",
                description="Select a server member to appoint as mod:",
                color=discord.Color.green()
            )
            view = discord.ui.View(timeout=60)
            select = discord.ui.UserSelect(placeholder="Select a member", custom_id="add_mod_select")

            async def add_mod_callback(si: discord.Interaction):
                perms_cog = self.bot.get_cog("Permissions")
                if not perms_cog:
                    await si.response.send_message("❌ Permissions module not found.", ephemeral=True)
                    return
                user_id = int(list(si.data["resolved"]["users"].keys())[0])
                member = si.guild.get_member(user_id)
                if not member:
                    await si.response.send_message("❌ Could not find that member in this server.", ephemeral=True)
                    return
                msg = await perms_cog.do_mod_add(si.guild_id, member, si.user.id)
                await si.response.send_message(msg, ephemeral=True)

            select.callback = add_mod_callback
            view.add_item(select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── Remove Mod ────────────────────────────────────────────
        elif custom_id == "remove_mod":
            if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
                await interaction.response.send_message("❌ Only admins can remove mods.", ephemeral=True)
                return

            embed = discord.Embed(
                title="➖ Remove Mod",
                description="Select a mod to remove:",
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=60)
            select = discord.ui.UserSelect(placeholder="Select a mod to remove", custom_id="remove_mod_select")

            async def remove_mod_callback(si: discord.Interaction):
                perms_cog = self.bot.get_cog("Permissions")
                if not perms_cog:
                    await si.response.send_message("❌ Permissions module not found.", ephemeral=True)
                    return
                user_id = int(list(si.data["resolved"]["users"].keys())[0])
                member = si.guild.get_member(user_id)
                if not member:
                    await si.response.send_message("❌ Could not find that member in this server.", ephemeral=True)
                    return
                msg = await perms_cog.do_mod_remove(si.guild_id, member)
                await si.response.send_message(msg, ephemeral=True)

            select.callback = remove_mod_callback
            view.add_item(select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ── Main Menu ─────────────────────────────────────────────
        elif custom_id == "main_menu":
            alliance_cog = self.bot.get_cog("Alliance")
            if alliance_cog:
                await alliance_cog.show_main_menu(interaction)
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Main menu not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotOperations(bot, sqlite3.connect('db/settings.sqlite')))
