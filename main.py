import io
from dateutil import parser
import pytz
from collections import Counter
from discord.ext import commands
from dotenv import load_dotenv
from functions import *
import discord
import time
import os
import json

# Retrieve token from .env
load_dotenv()
TOKEN: str = os.getenv("TOKEN")
APIKEY = os.getenv("APIKEY")

# Configure Bot
intents = discord.Intents.default()
intents.message_content = True

# Create bot client
client = commands.Bot(command_prefix="$", intents=intents)

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


# Events
@client.event
async def on_ready() -> None:
    print(f"We have logged in as {client.user}")


# Commands


# TODO: Modify the help command to provide descriptions and category title through an embed
class MyHelpCommand(commands.MinimalHelpCommand):
    async def send_pages(self):
        destination = self.get_destination()
        e = discord.Embed(color=discord.Color.blurple(), description="")
        for page in self.paginator.pages:
            e.description += page
        await destination.send(embed=e)


client.help_command = MyHelpCommand()

# Command to fetch the forecast office for a location passed by the user


@client.command(
    name="getoffice",
    help="Retrieves the forecast office for a city. Usage: $getOffice (city) (state abbreviation) (Las Vegas NV)",
)
async def getoffice(ctx, *args):
    await ctx.send(
        "The NWS Office for "
        + " ".join(args)
        + " is: "
        + forecastOffice(" ".join(args))
    )

def fetch_json_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}

def parse_utc_date(utc_date_str):
    """Parse UTC date string to datetime object with UTC timezone"""
    parsed_date = datetime.fromisoformat(utc_date_str.replace('Z', '+00:00'))
    return parsed_date.replace(tzinfo=pytz.UTC)

def format_utc_date(utc_date_str):
    """Convert UTC ISO format date to a more readable format in local time"""
    utc_date = parse_utc_date(utc_date_str)
    local_tz = datetime.now(pytz.UTC).astimezone().tzinfo
    local_date = utc_date.astimezone(local_tz)
    return local_date.strftime("%B %d, %Y at %I:%M %p %Z")

def filter_outlooks_by_time_range(outlooks, start_date=None, end_date=None, threshold=None):
    """Filter outlooks based on time range and optional threshold"""
    filtered_outlooks = []

    for outlook in outlooks:
        # Parse the UTC issue date (already timezone-aware)
        issue_date = parse_utc_date(outlook['utc_issue'])

        # Check date range
        date_in_range = True
        if start_date:
            date_in_range = date_in_range and issue_date >= start_date
        if end_date:
            date_in_range = date_in_range and issue_date <= end_date

        # Check threshold if specified
        threshold_match = not threshold or outlook['threshold'] == threshold

        # Add to filtered list if both conditions are met
        if date_in_range and threshold_match:
            filtered_outlooks.append(outlook)

    return filtered_outlooks


def create_formatted_table(data, headers):
    """Create a custom formatted table with proper header alignment"""
    if not data:
        return "No data available"

    # Format dates to ensure timezone doesn't wrap
    for row in data:
        for i in range(len(row)):
            # Check if this cell contains a date with timezone at the end
            cell_str = str(row[i])
            if " EDT" in cell_str or " EST" in cell_str or " PDT" in cell_str or " PST" in cell_str:
                # Replace the full timezone with a shorter version
                # For example: "March 30, 2025, at 01:15 PM EDT" -> "Mar 30, 2025 01:15PM ET"
                parts = cell_str.split()
                if len(parts) >= 7:  # Make sure it's the expected format
                    month = parts[0][:3]  # Abbreviate month name
                    day = parts[1].rstrip(',')
                    year = parts[2]
                    time = parts[4]
                    ampm = parts[5]
                    tz = parts[6][0] + "T"  # Just take first letter + T
                    row[i] = f"{month} {day}, {year} {time}{ampm} {tz}"

    # Get the maximum width for each column
    col_widths = [max(len(str(row[i])) for row in data) for i in range(len(data[0]))]
    for i, header in enumerate(headers):
        col_widths[i] = max(col_widths[i], len(header))

    # Create the header row with proper alignment
    header_row = ' | '.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = '-+-'.join('-' * w for w in col_widths)

    # Create data rows
    data_rows = [' | '.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)) for row in data]

    # Combine all parts
    table = f"{header_row}\n{separator}\n" + "\n".join(data_rows)
    return table

@client.command(
    name="getoutlook",
    help="Retrieves the the convective outlooks for a particular city over a period of time",
)
async def spc_outlook(ctx, city: str = None, state: str = None, start_date: str = None, end_date: str = None,
                      threshold: str = None):
    """
    Get SPC outlooks for a specific location
    Usage: !spcoutlook [city] [state] [start_date] [end_date] [threshold]
    Example: !spcoutlook Dallas TX "March 1, 2024" "April 1, 2024" MRGL
    """
    # Inform user that we're processing
    processing_msg = await ctx.send("Processing your request, please wait...")

    # Get location from command arguments
    if not city or not state:
        await processing_msg.edit(content="Please provide city, state, start date, and end date. Example: `$getoutlook Atlanta GA \"January 1 2025\" \"March 1 2025\"`")
        return

    # Geocode the location
    base_url = "https://geocode.xyz"
    params = {
        "locate": f"{city} {state}",
        "region": "US",
        "json": "1"
    }

    req_url = f"{base_url}/?{requests.utils.unquote(requests.compat.urlencode(params))}"
    try:
        resp = requests.get(req_url + f"&auth={APIKEY}")
        resp.raise_for_status()
        geocode_data = resp.json()
    except requests.RequestException as err:
        await processing_msg.edit(content=f"Error getting location coordinates: {err}")
        return

    # Check if we got valid coordinates
    if 'error' in geocode_data or 'longt' not in geocode_data or 'latt' not in geocode_data:
        await processing_msg.edit(
            content=f"Could not find coordinates for {city}, {state}. Please check your spelling.")
        return

    # Get SPC outlook data
    url = f"https://mesonet.agron.iastate.edu/json/spcoutlook.py?lon={geocode_data['longt']}&lat={geocode_data['latt']}&last=0&day=1&cat=categorical"
    json_data = fetch_json_data(url)

    if not json_data or 'error' in json_data:
        await processing_msg.edit(content=f"Error fetching SPC outlook data: {json_data.get('error', 'Unknown error')}")
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
        json_data['outlooks'],
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        threshold=threshold
    )

    # If no outlooks found
    if not filtered_outlooks:
        await processing_msg.edit(content=f"No outlooks found for {city}, {state} with the specified filters.")
        return

    # Prepare data for display
    display_data = [
        [
            outlook['threshold'],
            outlook['category'],
            format_utc_date(outlook['utc_issue']),
            format_utc_date(outlook['utc_expire']),
            format_utc_date(outlook['utc_product_issue'])
        ]
        for outlook in filtered_outlooks
    ]

    headers = ['Threshold', 'Category', 'Local Issue Date', 'Local Expire Date', 'Local Product Issue Date']
    # Create a table using tabulate
    table = create_formatted_table(display_data, headers)

    # Count thresholds
    threshold_counts = Counter(outlook['threshold'] for outlook in filtered_outlooks)
    threshold_summary = "\n**Threshold Summary:**\n" + "\n".join(
        f"{threshold}: {count}" for threshold, count in threshold_counts.items())

    # Create response message
    output = f"**SPC Outlook for {city}, {state}**\n\n"

    # Combine response parts based on length
    # If the table is too long for a Discord message, send it as a file
    if len(table) > 1950:
        # Write table to a file
        file_content = f"SPC Outlook for {city}, {state}\n\n{table}\n\n{threshold_summary}\n\nTotal Outlooks: {len(filtered_outlooks)}"
        buffer = io.StringIO(file_content)

        # Send the file
        await processing_msg.delete()
        file = File(fp=buffer, filename="spc_outlook.txt")
        await ctx.send(content=f"SPC Outlook for {city}, {state} (found {len(filtered_outlooks)} results)", file=file)
    else:
        # Add the table to the message with code block formatting
        output += f"```\n{table}\n```\n"
        output += threshold_summary
        output += f"\n\n**Total Outlooks:** {len(filtered_outlooks)}"

        # Send the message
        await processing_msg.edit(content=output)

@client.command(name="getUTC", help="Gets the current UTC time.")
async def getUTC(ctx) -> None:
    utc_time = await getUTCTime()
    await ctx.send(utc_time.strftime("%H:%M %m-%d-%y"))


@client.command(
    name="fetch",
    help="Fetches the latest Nadocast images. \n Usage: $fetch <params> \n Allowed params: sig, tor, wind, hail\n Examples: `$fetch tor`, `$fetch sig tor`",
)
async def fetch(ctx, *args) -> None:

    await log("DEBUG: Fetch command called with args:", ",".join(args))

    cooldown = cooldowns["fetch"]

    # TODO: This try/except block is hardcoded with the params, needs fixing + adding the life risk param.
    # Currently works and is not urgent.
    allowed_params = ["sig", "life", "tor", "wind", "hail"]

    # Let's check the args to make sure we should do this request.
    try:
        allowed_params.index(args[0])

        if (args[0] == "sig" or args[0] == "life") and args[1] != None:
            allowed_params.index(args[1])

    except:
        return await ctx.send(
            "Incorrect params! Example of proper commands: \n$fetch sig tor \n$fetch tor"
        )

    # Check if we are in cooldown
    if cooldown["last_used"] + cooldown["cooldown"] > datetime.now().timestamp():
        return await ctx.send("Please wait a minute before using this command again!")

    utc_time = await getUTCTime()
    await ctx.send("Fetching... please wait.")
    await ctx.send(f"Current UTC Time: {utc_time.strftime("%H:%M | %m-%d-%y")}")
    UTC = await getUTCTime()
    # Fetch data, get our list of images

    model, extra, doNotInclude = ctx.bot.models.values()
    result = await getNadoCastData(UTC, model, extra, doNotInclude)

    timeNow = UTC.strftime("%H")
    timeNowInt = int(timeNow)

    # Since the data is only available at 0Z, 12Z, 18Z, we need to round the time to the nearest available time
    if timeNowInt < 12:
        timeNow = 0
    elif 12 <= timeNowInt < 18:
        timeNow = 12
    elif 18 <= timeNowInt < 24:
        timeNow = 18

    # This shouldn't trigger, but if it does, something went wrong.
    if result is None:
        await log(
            f"Error: No images found for {timeNow}Z, current UTC is {timeNowInt}z."
        )
        await ctx.send(
            f"It appears Nadocast has not put out the new images for this time range ({timeNow}z)! Please try again in a minute."
        )
        cooldown["last_used"] = datetime.now().timestamp()
        return

    # Send the images
    files = []
    file_names = []
    debug = []
    # print(args)

    fileNumber = 0
    for file in result:
        # TODO: Add a case for when the user wants to fetch all images &
        # for tor life risk. (This was recently added in the Nadocast website, under 2024 models)

        # TODO: For some reason, the forecast hours are still changing. This this needs to be created better.
        # As of today (Nov 3rd, 2024), a new range has been introduced: f12-35, strange.

        timeRange = file.split("_")[-1].replace(".png", "")

        # Checks if the file is the correct to what the user wants, and if so, adds it to a list to send later.
        acceptableArgs = ["sig", "life", "tor", "wind", "hail"]

        # TODO: This "extras" for a name should really be renamed, alongside other things. But I have not really been thinking of better names.
        # TL;DR: Change names of variables to something more accurate.

        extras = []
        notExtra = "sig"

        if args[0] in acceptableArgs:
            extras = [abreviations[f"{args[0]}"], ""]

        if args[0] == "sig":
            notExtra = "?"

        try:
            extras[1] = abreviations[f"{args[1]}"]
        except Exception as e:
            pass

        # The list of files to send
        if (
            f"{extras[0]}_{extras[1]}" in file
            and timeRange in validD1TimeRanges
            and notExtra not in file
        ):
            files.append(discord.File(file, filename="image.png"))
            # Also for debug (the line below)
            debug.append(file)
            continue

    # This is never triggered, but if it is, something went wrong.
    if len(files) == 0:
        return await ctx.send(
            "It appears Nadocast has not put out the new images for this time range! Please try again in a minute."
        )

    # can be removed, I think, should just be for debugging
    debug.sort()

    # This text will be displayed in the embed
    text = ""
    # Default color is green, as it's good
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
        text = f"Sorry! It appears Nadocast hasn't uploaded the images for {
            timeNow}z, here are {hour}z's instead!"
        # Update our hexcode to yellow to note a "warning" that it's not the current time.
        hexcode = 0xFFFF00

    embedData = createWeatherEmbed(
        file=files[0], title=f"{"".join(args)}", description=text, color=hexcode
    )

    await ctx.send(embed=embedData[0], files=[embedData[1]])

    await log("Removing Nadocast Folder")
    checkOldFolders()

    # Debug for the files we return, uncomment if you want to see the files we are returning in logs/general.log
    # await log("Files: {\n", "\n".join(debug), "\n}")


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
