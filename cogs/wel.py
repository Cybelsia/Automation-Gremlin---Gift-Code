import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from .permissions import BOT_OWNER_ID

class GNCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('db/settings.sqlite')
        self.c = self.conn.cursor()
        self.c.execute("CREATE TABLE IF NOT EXISTS auto (value INTEGER NOT NULL DEFAULT 1)")
        self.c.execute("INSERT INTO auto (value) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM auto)")
        self.conn.commit()

    def cog_unload(self):
        if hasattr(self, 'conn'):
            self.conn.close()

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            admin_user = await self.bot.fetch_user(BOT_OWNER_ID)

            if admin_user:
                self.c.execute("SELECT value FROM auto LIMIT 1")
                auto_result = self.c.fetchone()
                auto_value = auto_result[0] if auto_result else 1

                status_embed = discord.Embed(
                    title="🤖 Bot Successfully Activated",
                    description=(
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "**System Status**\n"
                        "✅ Bot is now online and operational\n"
                        "✅ Database connections established\n"
                        "✅ Command systems initialized\n"
                        f"{'✅' if auto_value == 1 else '❌'} Alliance Control Messages\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                    ),
                    color=discord.Color.green()
                )

                status_embed.add_field(
                    name="📌 Support Information",
                    value=(
                        "**Developer:** <@918825495456514088>\n"
                        "**Discord Server:** [Click to Join](https://discord.gg/whiteoutall)\n"
                        "**Support:** [Buy me a coffee ☕](https://www.buymeacoffee.com/reloisback)\n"
                        "━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    inline=False
                )

                status_embed.set_thumbnail(url="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png")
                status_embed.set_footer(text="Thank you for using our bot! Feel free to contact for support.")

                await admin_user.send(embed=status_embed)

                with sqlite3.connect('db/alliance.sqlite') as alliance_db:
                    cursor = alliance_db.cursor()
                    cursor.execute("SELECT alliance_id, name FROM alliance_list")
                    alliances = cursor.fetchall()

                if alliances:
                    alliance_info = []

                    for alliance_id, name in alliances:
                        info_parts = []

                        with sqlite3.connect('db/users.sqlite') as users_db:
                            cursor = users_db.cursor()
                            cursor.execute("SELECT COUNT(*) FROM users WHERE alliance = ?", (alliance_id,))
                            user_count = cursor.fetchone()[0]
                            info_parts.append(f"👥 Members: {user_count}")

                        with sqlite3.connect('db/alliance.sqlite') as alliance_db:
                            cursor = alliance_db.cursor()
                            cursor.execute("SELECT discord_server_id FROM alliance_list WHERE alliance_id = ?", (alliance_id,))
                            discord_server = cursor.fetchone()
                            if discord_server and discord_server[0]:
                                info_parts.append(f"🌐 Server ID: {discord_server[0]}")

                            cursor.execute("SELECT channel_id, interval FROM alliancesettings WHERE alliance_id = ?", (alliance_id,))
                            settings = cursor.fetchone()
                            if settings:
                                if settings[0]:
                                    info_parts.append(f"📢 Channel: <#{settings[0]}>")
                                interval_text = f"⏱️ Auto Check: {settings[1]} minutes" if settings[1] > 0 else "⏱️ No Auto Check"
                                info_parts.append(interval_text)

                        with sqlite3.connect('db/giftcode.sqlite') as gift_db:
                            cursor = gift_db.cursor()
                            cursor.execute("SELECT status FROM giftcodecontrol WHERE alliance_id = ?", (alliance_id,))
                            gift_status = cursor.fetchone()
                            gift_text = "🎁 Gift System: Active" if gift_status and gift_status[0] == 1 else "🎁 Gift System: Inactive"
                            info_parts.append(gift_text)

                            cursor.execute("SELECT channel_id FROM giftcode_channel WHERE alliance_id = ?", (alliance_id,))
                            gift_channel = cursor.fetchone()
                            if gift_channel and gift_channel[0]:
                                info_parts.append(f"🎉 Gift Channel: <#{gift_channel[0]}>")

                        alliance_info.append(
                            f"**{name}**\n" + 
                            "\n".join(f"> {part}" for part in info_parts) +
                            "\n━━━━━━━━━━━━━━━━━━━━━━"
                        )

                    pages = [alliance_info[i:i + 5] for i in range(0, len(alliance_info), 5)]

                    for page_num, page in enumerate(pages, 1):
                        alliance_embed = discord.Embed(
                            title=f"📊 Alliance Information (Page {page_num}/{len(pages)})",
                            color=discord.Color.blue()
                        )
                        alliance_embed.description = "\n".join(page)
                        await admin_user.send(embed=alliance_embed)

                else:
                    alliance_embed = discord.Embed(
                        title="📊 Alliance Information",
                        description="No alliances currently registered.",
                        color=discord.Color.blue()
                    )
                    await admin_user.send(embed=alliance_embed)

                print("Activation messages sent to bot owner.")
            else:
                print(f"Bot owner with ID {BOT_OWNER_ID} not found.")
        except Exception as e:
            print(f"An error occurred: {e}")

    @app_commands.command(name="channel", description="Learn the ID of a channel.")
    @app_commands.describe(channel="The channel you want to learn the ID of")
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_message(
            f"The ID of the selected channel is: {channel.id}",
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(GNCommands(bot))
