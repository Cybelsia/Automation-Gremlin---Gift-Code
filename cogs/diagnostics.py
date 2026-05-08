from discord.ext import commands
from .permissions import is_owner_or_bot_user
from paths import storage_health_report


async def owner_or_bot_predicate(ctx: commands.Context):
    return is_owner_or_bot_user(ctx.author.id, ctx.bot)


class Diagnostics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="cascade_storage")
    @commands.check(owner_or_bot_predicate)
    async def cascade_storage(self, ctx: commands.Context):
        report = storage_health_report()

        if len(report) > 1900:
            report = report[:1900] + "\n...[truncated]"

        await ctx.send(f"```text\n{report}\n```")


async def setup(bot: commands.Bot):
    await bot.add_cog(Diagnostics(bot))
