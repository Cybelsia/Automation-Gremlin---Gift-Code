import discord
from discord.ext import commands
from cogs.permissions import BOT_OWNER_ID


class SupportRequestModal(discord.ui.Modal, title="Support Request"):
    issue_type = discord.ui.TextInput(
        label="Issue Type",
        placeholder="Bug / Feature Request / Question / Other",
        max_length=50,
        required=True
    )
    summary = discord.ui.TextInput(
        label="Short Summary",
        placeholder="One line describing your issue",
        max_length=100,
        required=True
    )
    details = discord.ui.TextInput(
        label="Details",
        placeholder="What happened? What did you expect? Any extra info...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            owner = await self.bot.fetch_user(BOT_OWNER_ID)
            if owner:
                dm_embed = discord.Embed(
                    title="📩 Support Request",
                    color=discord.Color.blue()
                )
                dm_embed.description = (
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 **From:** {interaction.user} (`{interaction.user.id}`)\n"
                    f"🌐 **Server:** {interaction.guild.name} (`{interaction.guild_id}`)\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📋 **Type:** {self.issue_type.value}\n"
                    f"📌 **Summary:** {self.summary.value}\n"
                    f"📝 **Details:**\n{self.details.value}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                )
                await owner.send(embed=dm_embed)

            await interaction.response.send_message(
                "✅ Your support request has been sent. You will be contacted if needed.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Could not deliver your request. Please try again later.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error sending support request: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while sending your request.",
                ephemeral=True
            )


class SupportOperations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def show_support_menu(self, interaction: discord.Interaction):
        support_menu_embed = discord.Embed(
            title="🎯 Support Operations",
            description=(
                "Please select an operation:\n\n"
                "**Available Operations**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📝 **Request Support**\n"
                "└ Submit a support request\n\n"
                "📖 **About Original Bot**\n"
                "└ About the original bot and its developer\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.blue()
        )

        view = SupportView(self)

        try:
            await interaction.response.edit_message(embed=support_menu_embed, view=view)
        except discord.errors.InteractionResponded:
            await interaction.message.edit(embed=support_menu_embed, view=view)


class SupportView(discord.ui.View):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    @discord.ui.button(
        label="Request Support",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="request_support"
    )
    async def support_request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SupportRequestModal(self.cog.bot))

    @discord.ui.button(
        label="About Original Bot",
        emoji="📖",
        style=discord.ButtonStyle.primary,
        custom_id="developer_about"
    )
    async def developer_about_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        about_embed = discord.Embed(
            title="📖 About the Original Bot",
            description=(
                "This bot is based on the original Whiteout Survival Discord Bot "
                "created by **Reloisback**. This version has been customised and extended "
                "but the original work and foundation belongs to them.\n\n"
                "**Original Developer**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "👤 **Developer:** Reloisback\n"
                "🌐 **Discord Server:** [Click Here](https://discord.gg/h8w6N6my4a)\n\n"
                "**Support the Original Developer**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "The original bot is and always will be free. If you'd like to support "
                "the original developer:\n"
                "[☕ Buy me a coffee](https://www.buymeacoffee.com/reloisback)\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.purple()
        )
        about_embed.set_footer(text="Original bot made with ❤️ by Reloisback")

        try:
            await interaction.response.send_message(embed=about_embed, ephemeral=True)
            try:
                await interaction.user.send(embed=about_embed)
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ Could not send DM because your DMs are closed!",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Error sending developer info: {e}")

    @discord.ui.button(
        label="Main Menu",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        custom_id="main_menu"
    )
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            try:
                await interaction.message.edit(content=None, embed=None, view=None)
                await alliance_cog.show_main_menu(interaction)
            except discord.errors.InteractionResponded:
                await interaction.message.edit(content=None, embed=None, view=None)
                await alliance_cog.show_main_menu(interaction)


async def setup(bot):
    await bot.add_cog(SupportOperations(bot))
