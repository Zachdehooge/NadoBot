import asyncio
import io
import json
from collections import deque
from datetime import date
import aiohttp
import discord
from dateutil import parser
from discord import app_commands
from discord.app_commands import checks, CommandOnCooldown
from discord.ext import commands, tasks
from urllib.parse import urlparse, parse_qs

from features.functions import *

load_dotenv()
TOKEN: str = os.getenv("TOKEN")

# Configure Bot
intents = discord.Intents.default()
intents.message_content = True

# Create bot client
client = commands.Bot(command_prefix=None, intents=intents)

USER_AGENT = "NadoBot (Discord Weather Bot)"
CHANNEL_ID = None
CHECK_INTERVAL = 1
CONFIG_FILE = "bot_config.json"

guild_channels = {}

posted_items = {}

global_seen_pids = deque(maxlen=300)
MAX_TRACKED_PIDS = 300
DEBUG_NEW_ALERTS = False

whatsnext_messages = {}  # {(guild_id, channel_id): message_id}


def load_config():
    """Load configuration from file"""
    global guild_channels, posted_items, global_seen_pids, whatsnext_messages
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                # Load guild -> channel mapping
                raw_config = config.get("guild_channels", {})

                # Handle both old format (guild_id: channel_id) and new format (guild_id: {"winter": id, "severe": id, "tornado": id})
                guild_channels = {}
                for k, v in raw_config.items():
                    guild_id = int(k)
                    if isinstance(v, dict):
                        # New format
                        guild_channels[guild_id] = v
                        print(
                            f"  Guild {guild_id} -> Winter: {v.get('winter')}, Severe: {v.get('severe')}, Tornado: {v.get('tornado')}, SWS: {v.get('sws')}"
                        )
                    else:
                        # Old format - migrate to new format with backward compatibility
                        guild_channels[guild_id] = {
                            "winter": v,
                            "severe": v,
                            "tornado": v,
                        }
                        print(
                            f"  Guild {guild_id} -> Migrated old config to all alert types: Channel {v}"
                        )

                    if guild_id not in posted_items:
                        posted_items[guild_id] = set()

                # Load what's next messages
                whatsnext_raw = config.get("whatsnext_messages", {})
                whatsnext_messages = {}
                for key, message_id in whatsnext_raw.items():
                    try:
                        guild_id, channel_id = map(int, key.split("_"))
                        whatsnext_messages[(guild_id, channel_id)] = message_id
                        print(
                            f"  Loaded what's next message for guild {guild_id}, channel {channel_id}"
                        )
                    except:
                        print(f"  Failed to parse what's next message key: {key}")

                print(
                    f"Loaded {len(guild_channels)} guild configurations and {len(whatsnext_messages)} what's next messages"
                )

                # Load global seen PIDs
                saved_pids = config.get("global_seen_pids", [])
                global_seen_pids = deque(saved_pids, maxlen=MAX_TRACKED_PIDS)
                print(f"Loaded {len(global_seen_pids)} previously seen alert IDs")
        except Exception as e:
            print(f"Error loading config: {e}")
    else:
        print("No config file found, starting fresh")
        # Initialize global PIDs tracking only if no config file
        global_seen_pids = deque(maxlen=MAX_TRACKED_PIDS)


def save_config():
    """Save configuration to file"""
    try:
        config = {
            "guild_channels": {str(k): v for k, v in guild_channels.items()},
            "whatsnext_messages": {
                f"{k[0]}_{k[1]}": v for k, v in whatsnext_messages.items()
            },
            "global_seen_pids": list(global_seen_pids),
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        print(
            f"Saved configuration for {len(guild_channels)} guilds and {len(whatsnext_messages)} what's next messages"
        )
    except Exception as e:
        print(f"Error saving config: {e}")


def parse_weather_alert(entry):
    """Parse RSS entry and create Discord embed"""
    title = entry.get("title", "Weather Alert")
    link = entry.get("link", "")
    description = entry.get("description", "")
    pub_date = entry.get("published", "")

    if len(title) > 256:
        title = title[:253] + "..."

    # Create embed
    try:
        timestamp = (
            datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
            if pub_date
            else datetime.now()
        )
    except:
        timestamp = datetime.now()

    embed = discord.Embed(
        title=title, url=link, color=discord.Color.red(), timestamp=timestamp
    )

    # Extract clean description (remove CDATA and pre tags)
    clean_desc = description.replace("<![CDATA[", "").replace("]]>", "")
    clean_desc = clean_desc.replace("<pre>", "").replace("</pre>", "").strip()

    # Truncate if too long (Discord limit is 4096 chars)
    if len(clean_desc) > 4000:
        clean_desc = clean_desc[:4000] + "..."

    embed.description = f"```\n{clean_desc}\n```"
    embed.set_footer(text="Weather Alert System")

    return embed


def extract_pid_from_link(link):
    """Extract unique PID from RSS link URL"""
    try:
        if not link:
            return None

        # Parse URL and extract 'pid' parameter
        parsed = urlparse(link)
        params = parse_qs(parsed.query)
        pid = params.get("pid", [None])[0]

        return pid if pid else None
    except Exception as e:
        print(f"Error extracting PID from link {link}: {e}")
        return None


def get_nws_alert_events():
    return [
        # Winter alerts
        "Winter Storm Warning",
        "Winter Storm Watch",
        "Blizzard Warning",
        "Blizzard Watch",
        "Ice Storm Warning",
        "Ice Storm Watch",
        "Heavy Snow Warning",
        "Snow Squall Warning",
        "Lake Effect Snow Warning",
        "Freezing Rain Advisory",
        "Wind Chill Warning",
        # Severe thunderstorm alerts
        "Severe Thunderstorm Warning",
        "Severe Thunderstorm Watch",
        "Thunderstorm Warning",
        "Thunderstorm Watch",
        # Tornado alerts
        "Tornado Warning",
        "Tornado Watch",
        "Tornado Emergency",
    ]


async def fetch_nws_alerts(session: aiohttp.ClientSession) -> list:
    """Fetch active alerts from NWS API using specific endpoints for each alert type"""
    alert_type_urls = {
        "tornado": "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update&event=tornado%20watch,tornado%20warning,tornado%20emergency",
        "severe": "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update&event=severe%20thunderstorm%20warning,severe%20thunderstorm%20watch,thunderstorm%20warning,thunderstorm%20watch",
        "winter": "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update&event=winter%20storm%20warning,winter%20storm%20watch,blizzard%20warning,blizzard%20watch,ice%20storm%20warning,ice%20storm%20watch,heavy%20snow%20warning,snow%20squall%20warning,lake%20effect%20snow%20warning,freezing%20rain%20advisory,wind%20chill%20warning",
        "sws": "https://api.weather.gov/alerts/active?event=special%20weather%20statement",
    }

    all_alerts = []
    headers = {"User-Agent": USER_AGENT, "accept": "application/geo+json"}

    for alert_type, url in alert_type_urls.items():
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    features = data.get("features", [])
                    for feature in features:
                        props = feature.get("properties", {})
                        props["_nws_alert_type"] = alert_type
                        all_alerts.append(props)
                elif response.status == 204:
                    pass
                else:
                    print(f"NWS API error for {alert_type}: {response.status}")
        except Exception as e:
            print(f"Error fetching NWS alerts for {alert_type}: {e}")

    return all_alerts


def is_winter_alert(event_name: str) -> bool:
    winter_events = [
        "Winter Storm Warning",
        "Winter Storm Watch",
        "Blizzard Warning",
        "Blizzard Watch",
        "Ice Storm Warning",
        "Ice Storm Watch",
        "Heavy Snow Warning",
        "Snow Squall Warning",
        "Lake Effect Snow Warning",
        "Freezing Rain Advisory",
        "Wind Chill Warning",
    ]
    return event_name.lower() in [e.lower() for e in winter_events]


def is_sws_alert(event_name: str) -> bool:
    sws_events = [
        "Special Weather Statement",
    ]
    return event_name.lower() in [e.lower() for e in sws_events]


def is_severe_thunderstorm_alert(event_name: str) -> bool:
    severe_events = [
        "Severe Thunderstorm Warning",
        "Severe Thunderstorm Watch",
        "Thunderstorm Warning",
        "Thunderstorm Watch",
    ]
    return event_name.lower() in [e.lower() for e in severe_events]


def is_tornado_alert(event_name: str) -> bool:
    tornado_events = [
        "Tornado Warning",
        "Tornado Watch",
        "Tornado Emergency",
    ]
    return event_name.lower() in [e.lower() for e in tornado_events]


def is_severe_weather_warning(title):
    """Check if the alert matches any of our tracked alert types (kept for compatibility)"""
    return (
        is_winter_alert(title)
        or is_severe_thunderstorm_alert(title)
        or is_tornado_alert(title)
        or is_sws_alert(title)
    )


@tasks.loop(minutes=CHECK_INTERVAL)
async def check_rss_feed():
    """Check NWS API for active alerts across all configured guilds"""
    global global_seen_pids
    if not guild_channels:
        print("NWS Alert Check: No guilds configured, skipping...")
        return

    try:
        async with aiohttp.ClientSession() as session:
            alerts = await fetch_nws_alerts(session)

        # Clean up global_seen_pids - remove alerts that are no longer active
        active_alert_ids = {alert.get("id", "") for alert in alerts if alert.get("id")}
        if active_alert_ids and len(global_seen_pids) > 0:
            old_count = len(global_seen_pids)
            global_seen_pids = deque(
                [pid for pid in global_seen_pids if pid in active_alert_ids],
                maxlen=MAX_TRACKED_PIDS,
            )
            removed = old_count - len(global_seen_pids)
            if removed > 0:
                print(f"Cleaned up {removed} expired alerts from global_seen_pids")
                save_config()

        if not alerts:
            print("NWS Alert Check: No active alerts found")
            return

        print(f"NWS Alert Check: Found {len(alerts)} total alerts")

        new_alerts_count = 0

        for alert in alerts:
            event = alert.get("event", "")
            alert_id = alert.get("id", "")
            title = alert.get("headline", "") or alert.get("event", "")
            description = alert.get("description", "")[:500]
            area_desc = alert.get("areaDesc", "Unknown")
            severity = alert.get("severity", "Unknown")
            urgency = alert.get("urgency", "Unknown")
            certainty = alert.get("certainty", "Unknown")
            sent = alert.get("sent", "")
            expires = alert.get("expires", "")
            expires_timestamp = int(parser.parse(expires).timestamp()) if expires else 0
            link = ""

            if not alert_id:
                continue

            # Skip if already in global_seen_pids (from previous session or already posted)
            if alert_id in global_seen_pids:
                continue

            alert_type = alert.get("_nws_alert_type", "")

            if not alert_type:
                if is_winter_alert(event):
                    alert_type = "winter"
                elif is_severe_thunderstorm_alert(event):
                    alert_type = "severe"
                elif is_tornado_alert(event):
                    alert_type = "tornado"
                elif is_sws_alert(event):
                    alert_type = "sws"
                else:
                    continue

            alert_type_urls = {
                "tornado": "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update&event=tornado%20watch,tornado%20warning,tornado%20emergency",
                "severe": "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update&event=severe%20thunderstorm%20warning,severe%20thunderstorm%20watch,thunderstorm%20warning,thunderstorm%20watch",
                "winter": "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update&event=winter%20storm%20warning,winter%20storm%20watch,blizzard%20warning,blizzard%20watch,ice%20storm%20warning,ice%20storm%20watch,heavy%20snow%20warning,snow%20squall%20warning,lake%20effect%20snow%20warning,freezing%20rain%20advisory,wind%20chill%20warning",
                "sws": "https://api.weather.gov/alerts/active?event=special%20weather%20statement",
            }
            link = alert_type_urls.get(alert_type, "https://www.weather.gov/")

            print(
                f"NEW ALERT DETECTED: ID={alert_id}, Event={event}, Type={alert_type}"
            )

            for guild_id, channels_config in guild_channels.items():
                if guild_id not in posted_items:
                    posted_items[guild_id] = set()

                # Skip if already posted to this guild
                if alert_id in posted_items[guild_id]:
                    continue

                channel_id = channels_config.get(alert_type)
                if not channel_id:
                    continue

                channel = client.get_channel(channel_id)
                if not channel:
                    print(
                        f"NWS Alert Check: Channel {channel_id} not found for guild {guild_id} ({alert_type})"
                    )
                    continue

                try:
                    embed = discord.Embed(
                        title=f"⚠️ {event}",
                        description=f"**Area:** {area_desc}\n**Severity:** {severity}\n**Urgency:** {urgency}\n**Certainty:** {certainty}\n\n{description}...",
                        color=(
                            discord.Color.red()
                            if "warning" in event.lower()
                            else discord.Color.orange()
                        ),
                        url=link,
                        timestamp=parser.parse(expires) if expires else None,
                    )
                    embed.add_field(
                        name="Expires:",
                        value=(
                            "<t:{}:R>".format(int(parser.parse(expires).timestamp()))
                            if expires
                            else "Unknown"
                        ),
                        inline=False,
                    )

                    await channel.send(embed=embed)

                    posted_items[guild_id].add(alert_id)
                    new_alerts_count += 1

                    if DEBUG_NEW_ALERTS:
                        print(f"Posted {alert_type} alert to guild {guild_id}: {event}")

                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"Error posting {alert_type} alert to guild {guild_id}: {e}")

            global_seen_pids.append(alert_id)

        for guild_id in guild_channels.keys():
            if guild_id in posted_items:
                if len(posted_items[guild_id]) > 100:
                    posted_items_list = list(posted_items[guild_id])
                    posted_items[guild_id].clear()
                    posted_items[guild_id].update(posted_items_list[-100:])

        if DEBUG_NEW_ALERTS:
            print(f"Global PIDs tracked: {len(global_seen_pids)}/{MAX_TRACKED_PIDS}")

        if new_alerts_count > 0:
            print(
                f"NWS Alert Check: Posted {new_alerts_count} new alerts across all guilds"
            )
            save_config()

    except Exception as e:
        print(f"Error checking NWS API: {e}")
        import traceback

        traceback.print_exc()


@check_rss_feed.before_loop
async def before_check_rss():
    """Wait until client is ready before starting the loop"""
    await client.wait_until_ready()
    print("Starting NWS alert checker...")


async def mark_existing_alerts_as_posted():
    """Mark all current NWS alerts as already posted to avoid spam on startup"""
    global global_seen_pids
    try:
        async with aiohttp.ClientSession() as session:
            alerts = await fetch_nws_alerts(session)

        added_count = 0
        for alert in alerts:
            alert_id = alert.get("id", "")
            if alert_id and alert_id not in global_seen_pids:
                global_seen_pids.append(alert_id)
                added_count += 1

        print(
            f"Marked {len(alerts)} existing alerts as already seen ({added_count} new)"
        )
        print(f"Global PIDs initialized: {len(global_seen_pids)}")
        if added_count > 0:
            save_config()
    except Exception as e:
        print(f"Error marking existing alerts: {e}")


@tasks.loop(minutes=1)
async def update_whatsnext_messages():
    """Update all what's next messages with fresh schedule data"""
    if not whatsnext_messages:
        return

    # Create list of messages to remove if they fail
    messages_to_remove = []

    for (guild_id, channel_id), message_id in list(whatsnext_messages.items()):
        try:
            channel = client.get_channel(channel_id)
            if not channel:
                messages_to_remove.append((guild_id, channel_id))
                continue

            # Try to fetch the message
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                messages_to_remove.append((guild_id, channel_id))
                continue
            except discord.Forbidden:
                messages_to_remove.append((guild_id, channel_id))
                continue

            # Update the message with new embed
            new_embed = create_whatsnext_embed()
            await message.edit(embed=new_embed)

        except Exception as e:
            print(
                f"Error updating what's next message for guild {guild_id}, channel {channel_id}: {e}"
            )
            messages_to_remove.append((guild_id, channel_id))

    # Remove failed messages from tracking
    for key in messages_to_remove:
        if key in whatsnext_messages:
            del whatsnext_messages[key]
            print(
                f"Removed what's next message for guild {key[0]}, channel {key[1]} (not found or inaccessible)"
            )

    # Save config if we removed any messages
    if messages_to_remove:
        save_config()


@update_whatsnext_messages.before_loop
async def before_update_whatsnext():
    await client.wait_until_ready()


@tasks.loop(seconds=15)
async def update_utc_status():
    now_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name=f"{now_utc}",
    )
    await client.change_presence(activity=activity)


@update_utc_status.before_loop
async def before_update_utc_status():
    await client.wait_until_ready()


# Events
@client.event
async def on_ready() -> None:
    # Load saved configurations
    load_config()

    await client.tree.sync()
    print(f"Logged in as {client.user}")
    print(f"Monitoring NWS API for active alerts")
    print(f"Configured for {len(guild_channels)} guilds")

    # Mark existing alerts to avoid spam on startup
    await mark_existing_alerts_as_posted()

    check_rss_feed.start()
    update_utc_status.start()
    update_whatsnext_messages.start()


@client.event
async def on_guild_remove(guild):
    """Clean up when bot is removed from a guild"""
    global guild_channels, whatsnext_messages
    if guild.id in guild_channels:
        del guild_channels[guild.id]
        if guild.id in posted_items:
            del posted_items[guild.id]

        # Remove any what's next messages for this guild
        messages_to_remove = [
            (g_id, c_id)
            for (g_id, c_id) in whatsnext_messages.keys()
            if g_id == guild.id
        ]
        for key in messages_to_remove:
            if key in whatsnext_messages:
                del whatsnext_messages[key]

        save_config()
        print(
            f"Removed configuration for guild {guild.id} ({guild.name}) including {len(messages_to_remove)} what's next messages"
        )


model_dict = {
    "2024": {"model": "_2024_", "extra": "", "notExtra": "abs"},
    "2024abs": {
        "model": "_2024_",
        "extra": "abs",
        "notExtra": "?",
    },
    "2022": {"model": "_2022_", "extra": "", "notExtra": "abs"},
    "2022abs": {
        "model": "_2022_",
        "extra": "abs",
        "notExtra": "?",
    },
    "": {
        "model": "",
        "extra": "",
        "notExtra": "?",
    },
}

abreviations = {
    "tor": "tornado",
    "wind": "wind",
    "hail": "hail",
}

# Valid time ranges (We can remove this later, but it's good to have for now)
validD1TimeRanges = ["f01-23", "f02-23", "f02-17", "f01-17", "f12-35"]


@client.tree.command(
    name="help",
    description="Shows this help message.",
)
async def help_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Weather Alert Bot Help",
        description="List of available slash commands:",
        color=discord.Color.blurple(),
    )

    # Group commands by category
    categories = {
        "Alert Channel Configuration": [
            "setchannel",
            "setwinterchannel",
            "setseverechannel",
            "settornadocommand",
            "currentalertchannels",
            "currentchannel",
            "removechannel",
        ],
        "Weather Information": [
            "getoffice",
            "getutc",
            "getoutlook",
            "fetch",
            "whatsnext",
        ],
        "Utility": ["help"],
    }

    all_commands = {
        cmd.name: cmd.description or "No description."
        for cmd in client.tree.get_commands()
    }

    for category, command_names in categories.items():
        embed.add_field(
            name=f"📋 {category}",
            value="\n".join(
                f"**/{name}** - {all_commands.get(name, 'No description.')}"
                for name in command_names
                if name in all_commands
            ),
            inline=False,
        )

    embed.set_footer(
        text="Use /help to see this message again. All channel configuration and /whatsnext commands require administrator permissions."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# Command to fetch the forecast office for a location passed by the user
@client.tree.command(
    name="getoffice",
    description="Get the NWS forecast office for a location",
)
@app_commands.describe(location="The location you want to look up")
@checks.cooldown(1, 30.0, key=lambda i: i.user.id)
async def getoffice(interaction: discord.Interaction, location: str):
    office = forecastOffice(location)
    await interaction.response.send_message(
        f"The NWS Office for **{location}** is: **{office}**"
    )


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, CommandOnCooldown):
        await interaction.response.send_message(
            f"Please wait {error.retry_after:.1f} seconds before using this command again.",
            ephemeral=True,
        )


# Commands
@client.tree.command(
    name="setchannel",
    description="Set the channel for weather alerts (for all alert types)",
)
@app_commands.describe(channel="The channel to send alerts to")
@app_commands.default_permissions(administrator=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global guild_channels

    guild_id = interaction.guild_id

    # Initialize guild config if not exists
    if guild_id not in guild_channels:
        guild_channels[guild_id] = {}

    # Set all alert types to this channel
    guild_channels[guild_id] = {
        "winter": channel.id,
        "severe": channel.id,
        "tornado": channel.id,
        "sws": channel.id,
    }

    # Initialize posted_items for this guild if needed
    if guild_id not in posted_items:
        posted_items[guild_id] = set()

    save_config()

    await interaction.response.send_message(
        f"All weather alerts will now be posted to {channel.mention} in this server.",
        ephemeral=True,
    )
    print(
        f"All channels set for guild {guild_id} ({interaction.guild.name}): {channel.name} (ID: {channel.id})"
    )


@client.tree.command(
    name="setwinterchannel", description="Set the channel for winter storm alerts"
)
@app_commands.describe(channel="The channel to send winter alerts too")
@app_commands.default_permissions(administrator=True)
async def set_winter_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    global guild_channels

    guild_id = interaction.guild_id

    # Initialize guild config if not exists
    if guild_id not in guild_channels:
        guild_channels[guild_id] = {}

    guild_channels[guild_id]["winter"] = channel.id

    # Initialize posted_items for this guild if needed
    if guild_id not in posted_items:
        posted_items[guild_id] = set()

    save_config()

    await interaction.response.send_message(
        f"Winter weather alerts will now be posted to {channel.mention} in this server.",
        ephemeral=True,
    )
    print(
        f"Winter channel set for guild {guild_id} ({interaction.guild.name}): {channel.name} (ID: {channel.id})"
    )


@client.tree.command(name="setswschannel", description="Set the channel for sws alerts")
@app_commands.describe(channel="The channel to send sws alerts too")
@app_commands.default_permissions(administrator=True)
async def set_sws_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    global guild_channels

    guild_id = interaction.guild_id

    # Initialize guild config if not exists
    if guild_id not in guild_channels:
        guild_channels[guild_id] = {}

    guild_channels[guild_id]["sws"] = channel.id

    # Initialize posted_items for this guild if needed
    if guild_id not in posted_items:
        posted_items[guild_id] = set()

    save_config()

    await interaction.response.send_message(
        f"Sws alerts will now be posted to {channel.mention} in this server.",
        ephemeral=True,
    )
    print(
        f"Sws channel set for guild {guild_id} ({interaction.guild.name}): {channel.name} (ID: {channel.id})"
    )


@client.tree.command(
    name="setseverechannel",
    description="Set the channel for severe thunderstorm alerts",
)
@app_commands.describe(channel="The channel to send severe thunderstorm alerts to")
@app_commands.default_permissions(administrator=True)
async def set_severe_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    global guild_channels

    guild_id = interaction.guild_id

    # Initialize guild config if not exists
    if guild_id not in guild_channels:
        guild_channels[guild_id] = {}

    guild_channels[guild_id]["severe"] = channel.id

    # Initialize posted_items for this guild if needed
    if guild_id not in posted_items:
        posted_items[guild_id] = set()

    save_config()

    await interaction.response.send_message(
        f"Severe thunderstorm alerts will now be posted to {channel.mention} in this server.",
        ephemeral=True,
    )
    print(
        f"Severe channel set for guild {guild_id} ({interaction.guild.name}): {channel.name} (ID: {channel.id})"
    )


@client.tree.command(
    name="settornadocommand", description="Set the channel for tornado alerts"
)
@app_commands.describe(channel="The channel to send tornado alerts to")
@app_commands.default_permissions(administrator=True)
async def set_tornado_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    global guild_channels

    guild_id = interaction.guild_id

    # Initialize guild config if not exists
    if guild_id not in guild_channels:
        guild_channels[guild_id] = {}

    guild_channels[guild_id]["tornado"] = channel.id

    # Initialize posted_items for this guild if needed
    if guild_id not in posted_items:
        posted_items[guild_id] = set()

    save_config()

    await interaction.response.send_message(
        f"Tornado alerts will now be posted to {channel.mention} in this server.",
        ephemeral=True,
    )
    print(
        f"Tornado channel set for guild {guild_id} ({interaction.guild.name}): {channel.name} (ID: {channel.id})"
    )


@client.tree.command(
    name="currentalertchannels",
    description="Show the current alert channels for all types",
)
@app_commands.default_permissions(administrator=True)
async def current_alert_channels(interaction: discord.Interaction):
    guild_id = interaction.guild_id

    if guild_id not in guild_channels:
        await interaction.response.send_message(
            "No channels are currently set for this server. Use `/setwinterchannel`, `/setseverechannel`, `/setswschannel ` or `/settornadocommand` to set channels.",
            ephemeral=True,
        )
        return

    channels_config = guild_channels[guild_id]
    embed = discord.Embed(
        title="Current Alert Channels",
        description="Configuration for weather alert channels in this server:",
        color=discord.Color.blue(),
    )

    for alert_type, channel_id in channels_config.items():
        channel = client.get_channel(channel_id)
        if channel:
            embed.add_field(
                name=f"{alert_type.capitalize()} Alerts",
                value=f"{channel.mention} (ID: {channel_id})",
                inline=False,
            )
        else:
            embed.add_field(
                name=f"{alert_type.capitalize()} Alerts",
                value=f"Channel ID {channel_id} not found (may have been deleted)",
                inline=False,
            )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(
    name="currentchannel", description="Show the current alert channel (legacy command)"
)
@app_commands.default_permissions(administrator=True)
async def current_channel(interaction: discord.Interaction):
    guild_id = interaction.guild_id

    if guild_id not in guild_channels:
        await interaction.response.send_message(
            "No channel is currently set for this server. Use `/setchannel` to set one.",
            ephemeral=True,
        )
    else:
        # For legacy compatibility, show the first configured channel
        channels_config = guild_channels[guild_id]
        first_channel_id = (
            next(iter(channels_config.values())) if channels_config else None
        )

        if first_channel_id:
            channel = client.get_channel(first_channel_id)
            if channel:
                await interaction.response.send_message(
                    f"Current alert channel: {channel.mention} (Note: Use `/currentalertchannels` to see all configured channels)",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Channel ID {first_channel_id} is set but not found. It may have been deleted.",
                    ephemeral=True,
                )
        else:
            await interaction.response.send_message(
                "No channels are configured. Use `/setwinterchannel`, `/setseverechannel`, or `/settornadocommand` to set channels.",
                ephemeral=True,
            )


@client.tree.command(
    name="removechannel",
    description="Remove all weather alert channels from this server",
)
@app_commands.default_permissions(administrator=True)
async def remove_channel(interaction: discord.Interaction):
    global guild_channels
    guild_id = interaction.guild_id

    if guild_id in guild_channels:
        del guild_channels[guild_id]
        if guild_id in posted_items:
            del posted_items[guild_id]
        save_config()
        await interaction.response.send_message(
            "All weather alert channels have been disabled for this server.",
            ephemeral=True,
        )
        print(f"Removed all channel configurations for guild {guild_id}")
    else:
        await interaction.response.send_message(
            "No channels were configured for this server.", ephemeral=True
        )


@client.tree.command(
    name="getutc",
    description="Get the NWS forecast office for a location",
)
async def getUTC(interaction: discord.Interaction) -> None:
    utc_time = await getUTCTime()
    await interaction.response.send_message(utc_time.strftime("%H:%M %m-%d-%y"))


@client.tree.command(
    name="whatsnext",
    description="Create/update live schedule message for model runs and SPC outlooks",
)
@app_commands.describe(action="Action to perform (start/stop/status)")
@app_commands.choices(
    action=[
        app_commands.Choice(name="Start Live Schedule", value="start"),
        app_commands.Choice(name="Stop Live Schedule", value="stop"),
        app_commands.Choice(name="Show Status", value="status"),
    ]
)
@app_commands.default_permissions(administrator=True)
async def whatsnext(interaction: discord.Interaction, action: str = "start"):
    global whatsnext_messages

    guild_id = interaction.guild_id
    channel_id = interaction.channel.id

    if action == "start":
        # Check if there's already a message in this channel
        if (guild_id, channel_id) in whatsnext_messages:
            await interaction.response.send_message(
                "There's already a live schedule message in this channel. Use `/whatsnext stop` to remove it first.",
                ephemeral=True,
            )
            return

        # Create the initial embed
        initial_embed = create_whatsnext_embed()

        # Send the message
        await interaction.response.send_message(embed=initial_embed)
        message = await interaction.original_response()

        # Store the message reference
        whatsnext_messages[(guild_id, channel_id)] = message.id
        save_config()

        await interaction.followup.send(
            "✅ Live schedule message created! It will update every minute with fresh countdowns.",
            ephemeral=True,
        )
        print(
            f"Created what's next message for guild {guild_id}, channel {channel_id}, message {message.id}"
        )

    elif action == "stop":
        if (guild_id, channel_id) not in whatsnext_messages:
            await interaction.response.send_message(
                "No live schedule message found in this channel.", ephemeral=True
            )
            return

        # Remove from tracking
        message_id = whatsnext_messages[(guild_id, channel_id)]
        del whatsnext_messages[(guild_id, channel_id)]
        save_config()

        await interaction.response.send_message(
            "✅ Live schedule updates stopped. The message will no longer be updated.",
            ephemeral=True,
        )
        print(
            f"Stopped what's next message for guild {guild_id}, channel {channel_id}, message {message_id}"
        )

    elif action == "status":
        active_in_guild = [
            (g_id, c_id, msg_id)
            for (g_id, c_id), msg_id in whatsnext_messages.items()
            if g_id == guild_id
        ]

        if not active_in_guild:
            await interaction.response.send_message(
                "No active live schedule messages in this server.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📊 Live Schedule Status",
            description=f"Found {len(active_in_guild)} active message(s) in this server:",
            color=discord.Color.green(),
        )

        for g_id, c_id, msg_id in active_in_guild:
            channel = client.get_channel(c_id)
            if channel:
                embed.add_field(
                    name=f"Channel: {channel.name}",
                    value=f"Message ID: {msg_id}\nStatus: ✅ Active",
                    inline=False,
                )

        embed.set_footer(text="Use /whatsnext stop to halt updates in any channel")
        await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(
    name="getoutlook",
    description="Usage: getoutlook [city] [state] [start_date] [end_date] [threshold]",
)
@app_commands.describe(
    city="City name",
    state="State abbreviation",
    start_date="Start date (e.g. March 1, 2024)",
    end_date="End date (e.g. April 1, 2024)",
    threshold="Risk threshold (optional)",
)
async def getoutlook(
    interaction: discord.Interaction,
    city: str,
    state: str,
    start_date: str = None,
    end_date: str = None,
    threshold: str = None,
):
    # Ensure interaction is deferred so followup messages are allowed,
    # then create a single followup message we can edit for errors/updates.
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)
    processing_msg = await interaction.followup.send(
        content="Processing your request, please wait...", wait=True
    )

    # Get location from command arguments
    if not city or not state:
        await processing_msg.edit(
            content='Usage: getoutlook [city] [state] [start_date] [end_date] [threshold] // Example: `$getoutlook Dallas TX "March 1, 2024" "April 1, 2024" MRGL` (the risk variable is optional)'
        )
        return

    # Geocode the location
    base_url = "https://geocode.xyz"
    params = {"locate": f"{city} {state}", "region": "US", "json": "1"}

    req_url = f"{base_url}/?{requests.utils.unquote(requests.compat.urlencode(params))}"
    try:
        resp = requests.get(req_url + f"&auth={APIKEY}")
        resp.raise_for_status()
        geocode_data = resp.json()
    except requests.RequestException as err:
        await processing_msg.edit(content=f"Error getting location coordinates: {err}")
        return

    # Check if we got valid coordinates
    if (
        "error" in geocode_data
        or "longt" not in geocode_data
        or "latt" not in geocode_data
    ):
        await processing_msg.edit(
            content=f"Could not find coordinates for {city}, {state}. Please check that you have an APIKEY env var set."
        )
        return

    # Get SPC outlook data
    url = f"https://mesonet.agron.iastate.edu/json/spcoutlook.py?lon={geocode_data['longt']}&lat={geocode_data['latt']}&last=0&day=1&cat=categorical"
    json_data = fetch_json_data(url)

    if not json_data or "error" in json_data:
        # defensive: json_data may be None
        err_msg = (
            json_data.get("error", "Unknown error")
            if isinstance(json_data, dict)
            else "Unknown error"
        )
        await processing_msg.edit(content=f"Error fetching SPC outlook data: {err_msg}")
        return

    # Parse date filters if provided
    parsed_start_date = None
    parsed_end_date = None

    try:
        if start_date:
            parsed_start_date = parser.parse(start_date).replace(tzinfo=pytz.UTC)
        if end_date:
            parsed_end_date = parser.parse(end_date).replace(tzinfo=pytz.UTC)
    except ValueError as e:
        await processing_msg.edit(content=f"Error parsing dates: {e}")
        return

    # Filter outlooks based on user input
    filtered_outlooks = filter_outlooks_by_time_range(
        json_data["outlooks"],
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        threshold=threshold,
    )

    # If no outlooks found
    if not filtered_outlooks:
        await processing_msg.edit(
            content=f"No outlooks found for {city}, {state} with the specified filters."
        )
        return

    # Prepare data for display
    display_data = [
        [
            outlook["threshold"],
            outlook["category"],
            format_utc_date(outlook["utc_issue"]),
            format_utc_date(outlook["utc_expire"]),
            format_utc_date(outlook["utc_product_issue"]),
        ]
        for outlook in filtered_outlooks
    ]

    headers = [
        "Threshold",
        "Category",
        "Local Issue Date",
        "Local Expire Date",
        "Local Product Issue Date",
    ]
    # Create a table using tabulate
    table = create_formatted_table(display_data, headers)

    # Count thresholds
    threshold_counts = Counter(outlook["threshold"] for outlook in filtered_outlooks)
    threshold_summary = "\nThreshold Summary:\n" + "\n".join(
        f"{th}: {count}" for th, count in threshold_counts.items()
    )

    # Create response message
    output = f"**SPC Outlook for {city}, {state}**\n\n"

    # Write table to a file-like buffer
    file_content = f"SPC Outlook for {city}, {state}\n\n{table}\n\n{threshold_summary}\n\nTotal Outlooks: {len(filtered_outlooks)}"
    buffer = io.StringIO(file_content)

    # Send the final file and message using the existing followup
    file = discord.File(
        fp=buffer, filename=f"{city}_{state}_{start_date}_{end_date}.txt"
    )
    await interaction.followup.send(
        content=f"SPC Outlook for {city}, {state} (found {len(filtered_outlooks)} results)",
        file=file,
    )


currentDate = date.today().strftime("%B %d, %Y")


@client.tree.command(
    name="fetch",
    description="Nadocast images for a given date, type, model, and zulu time. `/fetch March 1, 2024 tor 2024 12`",
)
@app_commands.describe(
    date="Date (e.g. March 15, 2025)",
    param="Type (tor, wind, hail, sig, life)",
    models="Model (2024, 2024abs, 2022, 2022abs) [optional] - Defaults to the 2022 model",
    zulu="Zulu hour (0, 12, or 18) [optional]",
)
@app_commands.choices(
    param=[
        app_commands.Choice(name="Tornado", value="tor"),
        app_commands.Choice(name="Wind", value="wind"),
        app_commands.Choice(name="Hail", value="hail"),
        app_commands.Choice(name="Life", value="life"),
        # app_commands.Choice(name="Sig", value="sig"), # If we remove sig
    ],
    zulu=[
        app_commands.Choice(name="0z", value="0"),
        app_commands.Choice(name="12z", value="12"),
        app_commands.Choice(name="18z", value="18"),
    ],
    models=[
        app_commands.Choice(name="2022", value="2022"),
        app_commands.Choice(name="2022 Absolutely Calibrated", value="2022abs"),
        app_commands.Choice(name="2024", value="2024"),
        app_commands.Choice(name="2024 Absolutely Calibrated", value="2024abs"),
    ],
)
async def fetch(
    interaction: discord.Interaction,
    param: str,
    date: str = currentDate,
    models: str = "2022",
    zulu: str = None,
) -> None:
    try:
        await log(
            "DEBUG: Fetch command called with params:",
            date,
            str(param),
            str(models),
            str(zulu),
        )
    except Exception as e:
        await interaction.response.send_message(f"Log error: {e}", ephemeral=True)
        return

    cooldown = cooldowns["fetch"]
    allowed_params = ["life", "tor", "wind", "hail"]
    allowed_zulu = ["0", "12", "18"]
    allowed_models = ["2024", "2024abs", "2022", "2022abs", ""]

    # Always treat 'date' as the date and 'param' as the type
    try:
        fetch_date = datetime.strptime(date, "%B %d, %Y")
    except ValueError:
        await interaction.response.send_message(
            "Invalid date format! Please use e.g. March 1, 2024.",
            ephemeral=True,
        )
        checkOldFolders()
        return
    fetch_type = param

    # Validate type
    if fetch_type not in allowed_params:
        await interaction.response.send_message(
            "Incorrect params! Example of a proper command: `/fetch param: Tornado models: 2024 Absolutely Calibrated zulu: 18z`",
            ephemeral=True,
        )
        checkOldFolders()
        return

    # Validate models argument
    if models not in allowed_models:
        await interaction.response.send_message(
            "Invalid models param! Must be one of: 2024, 2024abs, 2022, 2022abs; or it can be left empty.",
            ephemeral=True,
        )
        checkOldFolders()
        return

    # Validate zulu argument if provided
    # If zulu is None or empty string, use current UTC to determine zulu_hour
    if not zulu:  # covers None and empty string
        try:
            utc_now = await getUTCTime()
        except Exception as e:
            await interaction.response.send_message(
                f"getUTCTime error: {e}", ephemeral=True
            )
            return
        hour = utc_now.hour
        # Pick the most recent valid zulu time <= current hour
        if 13 <= hour < 18:
            zulu_hour = 12
        elif 0 <= hour < 10:
            zulu_hour = 18
        elif 18 <= hour < 24:
            zulu_hour = 18
        else:
            zulu_hour = 0
    else:
        if zulu not in allowed_zulu:
            await interaction.response.send_message(
                "Invalid zulu time! Must be one of: 0, 12, 18.",
                ephemeral=True,
            )
            checkOldFolders()
            return
        zulu_hour = int(zulu)

    # Check cooldown
    remaining = (
        cooldown["last_used"] + cooldown["cooldown"] - datetime.now().timestamp()
    )
    if remaining > 0:
        await interaction.response.send_message(
            f"Please wait {remaining:.1f} seconds before using this command again.",
            ephemeral=True,
        )
        checkOldFolders()
        return

    await interaction.response.send_message("Fetching... please wait.", ephemeral=True)

    # Set model, extra, doNotInclude based on models param
    model = model_dict[models]["model"] if models in model_dict else ""
    extra = model_dict[models]["extra"] if models in model_dict else ""
    doNotInclude = model_dict[models]["notExtra"] if models in model_dict else "?"

    # If date is provided, fetch for the specified or calculated Zulu time
    if fetch_date:
        dt = fetch_date.replace(hour=zulu_hour)
        try:
            await log(
                f"DEBUG: Calling getNadoCastData with dt={dt}, model={model}, extra={extra}, doNotInclude={doNotInclude}"
            )
            result = await getNadoCastData(dt, model, extra, doNotInclude)
            await log(
                f"DEBUG: getNadoCastData returned {len(result) if result else 'None'} results"
            )
        except Exception as e:
            await interaction.followup.send(
                f"getNadoCastData error: {e}", ephemeral=True
            )
            return
        # Filter for the requested type (exact match, not substring)
        type_str = abreviations.get(fetch_type, fetch_type)
        # Only match files with _tornado_ and not sig_tornado for tor
        if fetch_type == "tor":
            files = [f for f in result if "_tornado_" in f and "sig_tornado" not in f]
        else:
            files = [f for f in result if f"_{type_str}_" in f]
        if not files:
            await interaction.followup.send(
                f"No Nadocast images found for {fetch_type} on {date} at {zulu_hour}z.",
                ephemeral=True,
            )
            return
        discord_file = discord.File(files[0], filename="image.png")
        embedData = createWeatherEmbed(
            file=discord_file,
            title=f"{fetch_type}",
            description=f"Image for {date} @ {zulu_hour}z",
            color=0x008000,
        )
        await interaction.followup.send(embed=embedData[0], file=discord_file)
        cooldown["last_used"] = datetime.now().timestamp()
        checkOldFolders()
        return

    # If no date, use current UTC and zulu_hour
    utc_time = await getUTCTime()
    dt = utc_time.replace(hour=zulu_hour)
    try:
        await log(
            f"DEBUG: Calling getNadoCastData for current UTC dt={dt}, model={model}, extra={extra}, doNotInclude={doNotInclude}"
        )
        result = await getNadoCastData(dt, model, extra, doNotInclude)
        await log(
            f"DEBUG: getNadoCastData returned {len(result) if result else 'None'} results"
        )
    except Exception as e:
        await interaction.followup.send(f"getNadoCastData error: {e}", ephemeral=True)
        return

    if result is None or len(result) == 0:
        await log(
            f"Error: No images found for {zulu_hour}Z, current UTC is {utc_time.hour}z."
        )
        await interaction.followup.send(
            f"It appears Nadocast has not put out the new images for this time range ({zulu_hour}z)! Please try again in a minute.",
            ephemeral=True,
        )
        cooldown["last_used"] = datetime.now().timestamp()
        checkOldFolders()
        return

    files = []
    acceptableArgs = ["sig", "life", "tor", "wind", "hail"]
    extras = []
    notExtra = "sig"

    if fetch_type in acceptableArgs:
        extras = [abreviations.get(fetch_type, fetch_type), ""]
    if fetch_type == "sig":
        notExtra = "?"

    if param:
        try:
            extras[1] = abreviations.get(param, param)
        except Exception:
            pass

    for file in result:
        timeRange = file.split("_")[-1].replace(".png", "")
        # Only match files with _tornado_ and not sig_tornado for tor
        if fetch_type == "tor":
            if (
                "_tornado_" in file
                and "sig_tornado" not in file
                and timeRange in validD1TimeRanges
            ):
                files.append(file)
        else:
            if (
                f"{extras[0]}_{extras[1]}" in file
                and timeRange in validD1TimeRanges
                and notExtra not in file
            ):
                files.append(file)

    if len(files) == 0:
        await interaction.followup.send(
            "It appears Nadocast has not put out the new images for this time range! Please try again in a minute.",
            ephemeral=True,
        )
        checkOldFolders()
        return

    text = f"Here are the images for {zulu_hour}z!"
    hexcode = 0x008000

    discord_file = discord.File(files[0], filename="image.png")
    embedData = createWeatherEmbed(
        file=discord_file,
        title=f"{fetch_type} {param or ''}",
        description=text,
        color=hexcode,
    )

    await interaction.followup.send(embed=embedData[0], file=discord_file)
    cooldown["last_used"] = datetime.now().timestamp()
    checkOldFolders()


# Run the bot
if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.makedirs("logs")
    # if the token is empty, print a message to the console
    if type(TOKEN) == type(None) or len(TOKEN) == 0:
        print("Please follow the readme to setup the bot!")
    else:
        client.run(TOKEN)
