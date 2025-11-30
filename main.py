import io
import json
import os
import time

import discord
from dateutil import parser
from discord import app_commands
from discord.app_commands import checks, CommandOnCooldown
from discord.ext import commands

from functions import *

# Retrieve token from .env
load_dotenv()
TOKEN: str = os.getenv("TOKEN")
OWNER_GUILD: str = os.getenv("GUILD")

# Configure Bot
intents = discord.Intents.default()
intents.message_content = True

# Create bot client
client = commands.Bot(command_prefix=None, intents=intents)


# Events
@client.event
async def on_ready() -> None:
    activity = discord.Activity(type=discord.ActivityType.listening, name="$help")
    await client.change_presence(activity=activity)
    guild = discord.Object(id=OWNER_GUILD)
    await client.tree.sync(guild=guild)
    print(f"Logged in as {client.user}")


# Dictionary to change the if statements to a more readable format
models = {
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

@client.tree.command(name="help", description="Shows this help message.", guild=discord.Object(id=OWNER_GUILD))
async def help_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="Help", description="List of available slash commands:", color=discord.Color.blurple())
    for cmd in client.tree.get_commands(guild=discord.Object(id=OWNER_GUILD)):
        embed.add_field(name=f"/{cmd.name}", value=cmd.description or "No description.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command to fetch the forecast office for a location passed by the user
@client.tree.command(
    name="getoffice",
    description="Get the NWS forecast office for a location",
    guild=discord.Object(id=OWNER_GUILD),
)
@app_commands.describe(location="The location you want to look up")
@checks.cooldown(1, 30.0, key=lambda i: (i.guild_id, i.user.id))
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
            ephemeral=True
        )

@client.tree.command(
    name="getutc",
    description="Get the NWS forecast office for a location",
    guild=discord.Object(id=OWNER_GUILD),
)
async def getUTC(interaction: discord.Interaction) -> None:
    utc_time = await getUTCTime()
    await interaction.response.send_message(utc_time.strftime("%H:%M %m-%d-%y"))


@client.tree.command(
    name="getoutlook",
    description="Usage: getoutlook [city] [state] [start_date] [end_date] [threshold]",
    guild=discord.Object(id=OWNER_GUILD),
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

@client.tree.command(
    name="fetch",
    description="Fetches the latest Nadocast images. Example: `/fetch tor`, `/fetch sig tor`",
    guild=discord.Object(id=OWNER_GUILD),
)
@app_commands.describe(
    param1="Primary parameter (sig, life, tor, wind, hail)",
    param2="Secondary parameter (optional: tor, wind, hail)"
)
async def fetch(interaction: discord.Interaction, param1: str, param2: str = None) -> None:
    await log("DEBUG: Fetch command called with params:", param1, str(param2))

    cooldown = cooldowns["fetch"]

    allowed_params = ["sig", "life", "tor", "wind", "hail"]

    # Validate params
    if param1 not in allowed_params:
        await interaction.response.send_message(
            "Incorrect params! Example of proper commands: `/fetch sig tor`, `/fetch tor`",
            ephemeral=True
        )
        return
    if param1 in ["sig", "life"] and param2 and param2 not in allowed_params:
        await interaction.response.send_message(
            "Incorrect secondary param! Example: `/fetch sig tor`",
            ephemeral=True
        )
        return

    # Check cooldown
    if cooldown["last_used"] + cooldown["cooldown"] > datetime.now().timestamp():
        await interaction.response.send_message(
            "Please wait a minute before using this command again!",
            ephemeral=True
        )
        return

    utc_time = await getUTCTime()
    await interaction.response.send_message("Fetching... please wait.", ephemeral=True)
    await interaction.followup.send(f"Current UTC Time: {utc_time.strftime('%H:%M | %m-%d-%y')}", ephemeral=True)
    UTC = utc_time

    # Fetch data, get our list of images
    model = client.models["model"]
    extra = client.models["extra"]
    doNotInclude = client.models["doNotInclude"]
    result = await getNadoCastData(UTC, model, extra, doNotInclude)

    timeNow = UTC.strftime("%H")
    timeNowInt = int(timeNow)

    # Round time to nearest available time
    if timeNowInt < 12:
        timeNow = 0
    elif 12 <= timeNowInt < 18:
        timeNow = 12
    elif 18 <= timeNowInt < 24:
        timeNow = 18

    if result is None:
        await log(
            f"Error: No images found for {timeNow}Z, current UTC is {timeNowInt}z."
        )
        await interaction.followup.send(
            f"It appears Nadocast has not put out the new images for this time range ({timeNow}z)! Please try again in a minute.",
            ephemeral=True
        )
        cooldown["last_used"] = datetime.now().timestamp()
        return

    files = []
    debug = []

    # Argument mapping
    acceptableArgs = ["sig", "life", "tor", "wind", "hail"]
    extras = []
    notExtra = "sig"

    if param1 in acceptableArgs:
        extras = [abreviations.get(param1, param1), ""]
    if param1 == "sig":
        notExtra = "?"

    if param2:
        try:
            extras[1] = abreviations.get(param2, param2)
        except Exception:
            pass

    for file in result:
        timeRange = file.split("_")[-1].replace(".png", "")
        if (
            f"{extras[0]}_{extras[1]}" in file
            and timeRange in validD1TimeRanges
            and notExtra not in file
        ):
            files.append(discord.File(file, filename="image.png"))
            debug.append(file)
            continue

    if len(files) == 0:
        await interaction.followup.send(
            "It appears Nadocast has not put out the new images for this time range! Please try again in a minute.",
            ephemeral=True
        )
        return

    debug.sort()
    text = ""
    hexcode = 0x008000

    if f"{timeNow}z" in result[0]:
        text = f"Here are the images for {timeNow}z!"
    else:
        UTC = UTC - timedelta(hours=6)
        hour = int(UTC.strftime("%H"))
        if hour < 12:
            hour = 0
        elif 12 <= hour < 18:
            hour = 12
        elif 18 <= hour < 24:
            hour = 18
        text = f"Sorry! It appears Nadocast hasn't uploaded the images for {timeNow}z, here are {hour}z's instead!"
        hexcode = 0xFFFF00

    embedData = createWeatherEmbed(
        file=files[0], title=f"{param1} {param2 or ''}", description=text, color=hexcode
    )

    await interaction.followup.send(embed=embedData[0], files=[embedData[1]])

    await log("Removing Nadocast Folder")
    checkOldFolders()

# Run the bot
if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.makedirs("logs")
    # if the token is empty, print a message to the console
    if type(TOKEN) == type(None) or len(TOKEN) == 0:
        print("Please follow the readme to setup the bot!")
    else:
        # Sets the model and extra from .env and stores it to client.models (ctx.bot.models)
        model = ""
        extra = ""
        setModel = os.getenv("MODELS")
        model = models[f"{setModel}"]["model"]
        extra = models[f"{setModel}"]["extra"]
        notExtra = models[f"{setModel}"]["notExtra"]

        # If they leave it blank, we will fetch all models.
        if model == "":
            extra = ""
            notExtra = "?"

        client.models = {"model": model, "extra": extra, "doNotInclude": notExtra}
        client.run(TOKEN)
