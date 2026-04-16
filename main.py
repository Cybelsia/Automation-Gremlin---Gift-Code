import os

# Load the GUILD_ID environment variable
GUILD_ID = os.getenv('GUILD_ID')

if GUILD_ID is None:
    raise ValueError("GUILD_ID environment variable is required")


def on_error(event, error):
    """Handles errors that occur during events.

    Suppresses error code 10062 (connection lost) to
    prevent unnecessary logs and actions.
    """
    if error.code == 10062:
        return
    # Handle other errors appropriately


def on_ready():
    if GUILD_ID:
        # Sync guild-specific data if the GUILD_ID is set
        sync_guild(GUILD_ID)


def load_cogs(bot):
    """Loads all cogs for the bot. This allows modularity
    and easier management of bot commands and events.
    """
    # Load cogs here
