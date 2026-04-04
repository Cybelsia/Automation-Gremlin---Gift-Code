import sqlite3
import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

DB_FILE = "gremlin.db"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    # Keep row format simple (tuples)
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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS code_config ("
        " guild_id          INTEGER PRIMARY KEY,"
        " codes_channel_id  INTEGER,"
        " log_channel_id    INTEGER,"
        " admin_log_id      INTEGER"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS codes ("
        " id               INTEGER PRIMARY KEY AUTOINCREMENT,"
        " guild_id         INTEGER NOT NULL,"
        " code_text        TEXT NOT NULL,"
        " first_seen_at    TEXT NOT NULL,"
        " last_processed_at TEXT"
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
    class GiftOperations(commands.Cog):
    """Scan code channel and redeem gift codes every 6 hours."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scan_codes.start()

    def cog_unload(self):
        self.scan_codes.cancel()

    def _get_config(
        self,
        guild_id: int,
    ) -> tuple[Optional[int], Optional[int], Optional[int]]:
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "SELECT codes_channel_id, log_channel_id, admin_log_id "
                "FROM code_config WHERE guild_id = ?",
                (guild_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()

        if row is None:
            return (None, None, None)
        return row[0], row[1], row[2]

    def _set_config(
        self,
        guild_id: int,
        codes_channel_id: int,
        log_channel_id: int,
        admin_log_id: int,
    ) -> None:
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO code_config "
                "(guild_id, codes_channel_id, log_channel_id, admin_log_id) "
                "VALUES (?, ?, ?, ?)",
                (guild_id, codes_channel_id, log_channel_id, admin_log_id),
            )
            conn.commit()
        finally:
            conn.close()

    @app_commands.command(
        name="ag_codes_config",
        description="Configure the gift code channels for this server.",
    )
    @app_commands.describe(
        codes_channel="Channel where gift codes are posted.",
        log_channel="Channel for public summary messages.",
        admin_log="Admin-only channel for failure details.",
    )
    async def ag_codes_config(
        self,
        interaction: discord.Interaction,
        codes_channel: discord.TextChannel,
        log_channel: discord.TextChannel,
        admin_log: discord.TextChannel,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "You must be a Gremlin admin or the server owner to configure codes.",
                ephemeral=True,
            )
            return

        self._set_config(
            interaction.guild.id,
            codes_channel.id,
            log_channel.id,
            admin_log.id,
        )

        await interaction.response.send_message(
            "Gift code configuration saved for this server.",
            ephemeral=True,
        )
            def _extract_codes_from_message(self, content: str) -> list[str]:
        """Very simple parser to pull out code-like tokens from a message."""
        if not content:
            return []

        tokens = content.replace("
", " ").split()
        codes: list[str] = []
        for token in tokens:
            cleaned = token.strip().strip(",.;!?:")
            # Simple rule: 6–20 chars, all uppercase letters or digits
            if 6 <= len(cleaned) <= 20 and cleaned.isalnum() and cleaned.upper() == cleaned:
                codes.append(cleaned)
        return codes
    @tasks.loop(hours=6)
    async def scan_codes(self):
        """Background task: scan configured channels every 6 hours."""
        if not self.bot.guilds:
            return

        now = datetime.datetime.utcnow().isoformat(timespec="seconds")

        for guild in self.bot.guilds:
            codes_channel_id, log_channel_id, admin_log_id = self._get_config(guild.id)
            if not codes_channel_id or not log_channel_id:
                continue  # not configured

            codes_channel = guild.get_channel(codes_channel_id)
            log_channel = guild.get_channel(log_channel_id)
            admin_log_channel = guild.get_channel(admin_log_id) if admin_log_id else None

            if codes_channel is None or log_channel is None:
                continue

            # Fetch recent messages (up to 100) and look for new code strings
            try:
                messages = [m async for m in codes_channel.history(limit=100)]
            except discord.Forbidden:
                continue

            new_codes = []

            conn = get_db_connection()
            try:
                for msg in messages:
                    code_texts = self._extract_codes_from_message(msg.content)
                    for code in code_texts:
                        cur = conn.execute(
                            "SELECT id FROM codes WHERE guild_id = ? AND code_text = ?",
                            (guild.id, code),
                        )
                        if cur.fetchone() is None:
                            conn.execute(
                                "INSERT INTO codes (guild_id, code_text, first_seen_at, last_processed_at) "
                                "VALUES (?, ?, ?, NULL)",
                                (guild.id, code, now),
                            )
                            new_codes.append(code)
                conn.commit()
            finally:
                conn.close()

            if not new_codes:
                continue

            # In the future: actually redeem codes here.
            # For now we just announce that we detected them.
            codes_list = ", ".join(new_codes)
            try:
                await log_channel.send(
                    f"Detected {len(new_codes)} new gift code(s): {codes_list}"
                )
            except discord.Forbidden:
                pass

            if admin_log_channel is not None:
                try:
                    await admin_log_channel.send(
                        f"New codes detected (no redemption logic yet): {codes_list}"
                    )
                except discord.Forbidden:
                    pass

    @scan_codes.before_loop
    async def before_scan_codes(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(GiftOperations(bot))