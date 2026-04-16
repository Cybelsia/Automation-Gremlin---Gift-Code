import sqlite3
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

DB_FILE = "gremlin.db"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS admins ("
        " guild_id INTEGER NOT NULL,"
        " user_id INTEGER NOT NULL,"
        " PRIMARY KEY (guild_id, user_id)"
        ")"
    )
    return conn


def is_admin_in_guild(guild_id: int, user_id: int) -> bool:
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT 1 FROM admins WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def admin_required():
    """Slash-command check: only allow registered admins (or server owner)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
        elif interaction.user.id == interaction.guild.owner_id:
            return True
        elif is_admin_in_guild(interaction.guild.id, interaction.user.id):
            return True
        else:
            await interaction.response.send_message(
                "You are not registered as an Automation Gremlin admin.",
                ephemeral=True,
            )
        return False

    return app_commands.check(predicate)


class PermissionHandler(commands.Cog):
    """Manage who is an Automation Gremlin admin in this server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _has_manage_guild(self, interaction: discord.Interaction) -> bool:
        """Only people who can manage the server may edit admins."""
        if interaction.user.id == interaction.guild.owner_id:
            return True
        perms = interaction.user.guild_permissions
        return perms.manage_guild or perms.administrator

    @app_commands.command(
        name="ag_admin_add",
        description="Register a user as an Automation Gremlin admin.",
    )
    @app_commands.describe(user="The user to make an admin.")
    async def ag_admin_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not self._has_manage_guild(interaction):
            await interaction.response.send_message(
                "You must have Manage Server (or be the owner) to add admins.",
                ephemeral=True,
            )
            return

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO admins (guild_id, user_id) VALUES (?, ?)",
                (interaction.guild.id, user.id),
            )
            conn.commit()
        finally:
            conn.close()

        await interaction.response.send_message(
            f"{user.mention} is now registered as an Automation Gremlin admin.",
            ephemeral=True,
        )

    @app_commands.command(
        name="ag_admin_remove",
        description="Remove a user from Automation Gremlin admins.",
    )
    @app_commands.describe(user="The user to remove as admin.")
    async def ag_admin_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not self._has_manage_guild(interaction):
            await interaction.response.send_message(
                "You must have Manage Server (or be the owner) to remove admins.",
                ephemeral=True,
            )
            return

        conn = get_db_connection()
        try:
            cur = conn.execute(
                "DELETE FROM admins WHERE guild_id = ? AND user_id = ?",
                (interaction.guild.id, user.id),
            )
            conn.commit()
            removed = cur.rowcount > 0
        finally:
            conn.close()

        if removed:
            msg = f"{user.mention} is no longer an Automation Gremlin admin."
        else:
            msg = f"{user.mention} was not registered as an admin."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(
        name="ag_admin_list",
        description="Show the list of Automation Gremlin admins in this server.",
    )
    async def ag_admin_list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        conn = get_db_connection()
        try:
            cur = conn.execute(
                "SELECT user_id FROM admins WHERE guild_id = ?",
                (interaction.guild.id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            await interaction.response.send_message(
                "No Automation Gremlin admins are registered yet.",
                ephemeral=True,
            )
            return

        ids: List[int] = [r[0] for r in rows]
        mentions = []
        for uid in ids:
            member = interaction.guild.get_member(uid)
            if member is not None:
                mentions.append(member.mention)
            else:
                mentions.append(f"<@{uid}> (no longer in server?)")

        joined = "
".join(mentions)
        await interaction.response.send_message(
            f"Automation Gremlin admins in this server:
{joined}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PermissionHandler(bot))
