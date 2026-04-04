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
        " user_id  INTEGER NOT NULL,"
        " PRIMARY KEY (guild_id, user_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS members ("
        " guild_id INTEGER NOT NULL,"
        " user_id  INTEGER NOT NULL,"
        " game_id  TEXT NOT NULL,"
        " PRIMARY KEY (guild_id, user_id)"
        ")"
    )
    return conn


def is_admin_or_owner(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False

    if interaction.user.id == interaction.guild.owner_id:
        return True

    conn = get_db_connection()
    try:
        cur = conn.execute(
            "SELECT 1 FROM admins WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    return row is not None


class Registration(commands.Cog):
    """Handle mapping Discord users to game IDs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
            @app_commands.command(
        name="ag_member_set",
        description="Set or update a member's game ID.",
    )
    @app_commands.describe(
        user="The Discord member.",
        game_id="The in-game ID for this member.",
    )
    async def ag_member_set(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        game_id: str,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "You must be a Gremlin admin or the server owner to set IDs.",
                ephemeral=True,
            )
            return

        game_id = game_id.strip()
        if not game_id:
            await interaction.response.send_message(
                "Game ID cannot be empty.",
                ephemeral=True,
            )
            return

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO members (guild_id, user_id, game_id)"
                " VALUES (?, ?, ?)",
                (interaction.guild.id, user.id, game_id),
            )
            conn.commit()
        finally:
            conn.close()

        await interaction.response.send_message(
            f"Stored game ID for {user.mention}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="ag_member_clear",
        description="Clear a member's stored game ID.",
    )
    @app_commands.describe(user="The Discord member.")
    async def ag_member_clear(
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

        if not is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "You must be a Gremlin admin or the server owner to clear IDs.",
                ephemeral=True,
            )
            return

        conn = get_db_connection()
        try:
            cur = conn.execute(
                "DELETE FROM members WHERE guild_id = ? AND user_id = ?",
                (interaction.guild.id, user.id),
            )
            conn.commit()
            removed = cur.rowcount > 0
        finally:
            conn.close()

        if removed:
            msg = f"Cleared stored game ID for {user.mention}."
        else:
            msg = f"No stored game ID found for {user.mention}."
        await interaction.response.send_message(msg, ephemeral=True)
            @app_commands.command(
        name="ag_member_list",
        description="Show members with stored game IDs (limited list).",
    )
    async def ag_member_list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "You must be a Gremlin admin or the server owner to view IDs.",
                ephemeral=True,
            )
            return

        conn = get_db_connection()
        try:
            cur = conn.execute(
                "SELECT user_id, game_id FROM members WHERE guild_id = ?",
                (interaction.guild.id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            await interaction.response.send_message(
                "No members have stored game IDs yet.",
                ephemeral=True,
            )
            return

        lines: List[str] = []
        max_rows = 25
        for idx, (user_id, game_id) in enumerate(rows):
            if idx >= max_rows:
                lines.append(f"...and {len(rows) - max_rows} more.")
                break
            member = interaction.guild.get_member(user_id)
            if member is not None:
                lines.append(f"{member.mention} -> {game_id}")
            else:
                lines.append(f"<@{user_id}> (left server?) -> {game_id}")

        text = "
".join(lines)
        await interaction.response.send_message(
            f"Stored game IDs for this server:
{text}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Registration(bot))