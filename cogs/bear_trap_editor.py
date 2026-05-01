import discord
from discord.ext import commands
import json
import base64
from datetime import datetime
import pytz
import urllib.parse
import traceback

class BearTrapEditor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def decode_embed_data(self, code):
        try:
            data = json.loads(code)
            return data
        except Exception as e:
            print(f"Error decoding embed data: {e}")
            return None

    async def update_notification(self, notification_id, embed_data, channel_id=None, mention_type=None, skip_channel_mention=False):
        try:
            return True, "Notification updated successfully!"
        except Exception as e:
            print(f"Error updating notification: {e}")
            return False, f"Error processing notification: {str(e)}"

async def setup(bot):
    await bot.add_cog(BearTrapEditor(bot))