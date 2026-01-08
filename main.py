import io
from datetime import date

import discord
from dateutil import parser
from discord import app_commands
from discord.app_commands import checks, CommandOnCooldown
from discord.ext import commands

from features.functions import *

# Retrieve token from .env
load_dotenv()
TOKEN: str = os.getenv("TOKEN")

# Configure Bot
intents = discord.Intents.default()
intents.message_content = True

# Create bot client
client = commands.Bot(command_prefix=None, intents=intents)


# Events
@client.event
async def on_ready() -> None:
    activity = discord.Activity(type=discord.ActivityType.listening, name="/help")
    await client.change_presence(activity=activity)
    await client.tree.sync()
    print(f"Logged in as {client.user}")


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
        title="Help",
        description="List of available slash commands:",
        color=discord.Color.blurple(),
    )
    for cmd in client.tree.get_commands():
        embed.add_field(
            name=f"/{cmd.name}",
            value=cmd.description or "No description.",
            inline=False,
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


@client.tree.command(
    name="getutc",
    description="Get the NWS forecast office for a location",
)
async def getUTC(interaction: discord.Interaction) -> None:
    utc_time = await getUTCTime()
    await interaction.response.send_message(utc_time.strftime("%H:%M %m-%d-%y"))

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
