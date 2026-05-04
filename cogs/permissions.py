import os
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands


BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "1237812594140512347"))
ROLE_LEVELS = {
    "mod": 1,
    "admin": 2,
    "owner": 3,
}


class Permissions(commands.Cog):
    admin = app_commands.Group(name="admin", description="Manage server administrators")
    mod = app_commands.Group(name="mod", description="Manage server moderators")

    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('db/settings.sqlite', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.setup_database()

    def setup_database(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'mod')),
                appointed_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_alliances (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                alliance_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id, alliance_id)
            )
        """)
        self.conn.commit()

    def is_owner(self, user_id: int) -> bool:
        return user_id == BOT_OWNER_ID

    def get_role(self, user_id: int, guild_id: int | None) -> str | None:
        if self.is_owner(user_id):
            return "owner"
        if guild_id is None:
            return None
        self.cursor.execute(
            "SELECT role FROM permissions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def check_permission(self, user_id: int, guild_id: int | None, min_role: str) -> bool:
        role = self.get_role(user_id, guild_id)
        if role is None:
            return False
        return ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS.get(min_role, 0)

    async def _require_permission(self, interaction: discord.Interaction, min_role: str) -> bool:
        if self.check_permission(interaction.user.id, interaction.guild_id, min_role):
            return True
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return False

    async def do_admin_add(self, guild_id: int, user: discord.Member, appointed_by_id: int) -> str:
        """Core logic for adding an admin. Returns a result message string."""
        if user.bot:
            return "❌ Bots cannot be appointed as admins."
        if self.is_owner(user.id):
            return "❌ The bot owner cannot be assigned a role."
        self.cursor.execute(
            "SELECT user_id FROM permissions WHERE guild_id = ? AND role = 'admin'",
            (guild_id,)
        )
        existing_admin = self.cursor.fetchone()
        if existing_admin and existing_admin[0] != user.id:
            return "❌ This server already has an admin. Remove them before appointing a new one."
        self.cursor.execute(
            """
            INSERT INTO permissions (guild_id, user_id, role, appointed_by)
            VALUES (?, ?, 'admin', ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                role = excluded.role,
                appointed_by = excluded.appointed_by,
                created_at = CURRENT_TIMESTAMP
            """,
            (guild_id, user.id, appointed_by_id)
        )
        self.conn.commit()
        return f"✅ {user.mention} is now this server's admin."

    async def do_admin_remove(self, guild_id: int, user: discord.Member) -> str:
        """Core logic for removing an admin. Returns a result message string."""
        self.cursor.execute(
            "DELETE FROM permissions WHERE guild_id = ? AND user_id = ? AND role = 'admin'",
            (guild_id, user.id)
        )
        self.conn.commit()
        if self.cursor.rowcount == 0:
            return "❌ That user is not this server's admin."
        return f"✅ Removed {user.mention} as this server's admin."

    async def do_mod_add(self, guild_id: int, user: discord.Member, appointed_by_id: int) -> str:
        """Core logic for adding a mod. Returns a result message string."""
        if user.bot:
            return "❌ Bots cannot be appointed as mods."
        if self.is_owner(user.id):
            return "❌ The bot owner cannot be changed to a mod."
        self.cursor.execute(
            "SELECT role FROM permissions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user.id)
        )
        existing = self.cursor.fetchone()
        if existing and existing[0] == "admin":
            return "❌ This user is already this server's admin."
        self.cursor.execute(
            """
            INSERT INTO permissions (guild_id, user_id, role, appointed_by)
            VALUES (?, ?, 'mod', ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                role = excluded.role,
                appointed_by = excluded.appointed_by,
                created_at = CURRENT_TIMESTAMP
            """,
            (guild_id, user.id, appointed_by_id)
        )
        self.conn.commit()
        return f"✅ {user.mention} is now a server mod."

    async def do_mod_remove(self, guild_id: int, user: discord.Member) -> str:
        """Core logic for removing a mod. Returns a result message string."""
        self.cursor.execute(
            "DELETE FROM permissions WHERE guild_id = ? AND user_id = ? AND role = 'mod'",
            (guild_id, user.id)
        )
        self.conn.commit()
        if self.cursor.rowcount == 0:
            return "❌ That user is not a server mod."
        return f"✅ Removed {user.mention} as server mod."

    @admin.command(name="add", description="Appoint this server's administrator")
    @app_commands.describe(user="User to appoint as this server's admin")
    async def admin_add(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._require_permission(interaction, "owner"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        msg = await self.do_admin_add(interaction.guild_id, user, interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=True)

    @admin.command(name="list", description="List this server's administrators")
    async def admin_list(self, interaction: discord.Interaction):
        if not await self._require_permission(interaction, "owner"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        self.cursor.execute(
            "SELECT user_id, appointed_by, created_at FROM permissions WHERE guild_id = ? AND role = 'admin'",
            (interaction.guild_id,)
        )
        rows = self.cursor.fetchall()
        if not rows:
            await interaction.response.send_message("No admins assigned for this server.", ephemeral=True)
            return
        embed = discord.Embed(title="🛡️ Server Admins", color=discord.Color.blue())
        for user_id, appointed_by, created_at in rows:
            embed.add_field(
                name=f"<@{user_id}> (`{user_id}`)",
                value=f"Appointed by: <@{appointed_by}>\nDate: `{created_at}`",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin.command(name="remove", description="Remove this server's administrator")
    @app_commands.describe(user="Admin to remove")
    async def admin_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._require_permission(interaction, "owner"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        msg = await self.do_admin_remove(interaction.guild_id, user)
        await interaction.response.send_message(msg, ephemeral=True)

    @mod.command(name="add", description="Appoint a server moderator")
    @app_commands.describe(user="User to appoint as moderator")
    async def mod_add(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._require_permission(interaction, "admin"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        msg = await self.do_mod_add(interaction.guild_id, user, interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=True)

    @mod.command(name="list", description="List this server's moderators")
    async def mod_list(self, interaction: discord.Interaction):
        if not await self._require_permission(interaction, "admin"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        self.cursor.execute(
            "SELECT user_id, appointed_by, created_at FROM permissions WHERE guild_id = ? AND role = 'mod'",
            (interaction.guild_id,)
        )
        rows = self.cursor.fetchall()
        if not rows:
            await interaction.response.send_message("No mods assigned for this server.", ephemeral=True)
            return
        embed = discord.Embed(title="🔧 Server Mods", color=discord.Color.blue())
        for user_id, appointed_by, created_at in rows:
            embed.add_field(
                name=f"<@{user_id}> (`{user_id}`)",
                value=f"Appointed by: <@{appointed_by}>\nDate: `{created_at}`",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mod.command(name="remove", description="Remove a server moderator")
    @app_commands.describe(user="Moderator to remove")
    async def mod_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._require_permission(interaction, "admin"):
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        msg = await self.do_mod_remove(interaction.guild_id, user)
        await interaction.response.send_message(msg, ephemeral=True)

    def cog_unload(self):
        self.conn.close()


def check_permission(user_id: int, guild_id: int | None, min_role: str) -> bool:
    if user_id == BOT_OWNER_ID:
        return True
    if guild_id is None:
        return False

    with sqlite3.connect('db/settings.sqlite') as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role FROM permissions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        result = cursor.fetchone()

    if result is None:
        return False
    return ROLE_LEVELS.get(result[0], 0) >= ROLE_LEVELS.get(min_role, 0)


async def setup(bot):
    await bot.add_cog(Permissions(bot))
