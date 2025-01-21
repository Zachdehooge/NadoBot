from discord.ext import commands
from dotenv import load_dotenv
from functions import *
import discord
import time
import os
import json

# Retrive token from .env
load_dotenv()
TOKEN: str = os.getenv("TOKEN")

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
# TODO: Handle multi-word cities

@client.command(name="getOffice", help="Retrieves the forecast office for a city. Usage: $getOffice (city) (state abbreviation) (Aurora, CO)")
async def getOffice(ctx, *args):
    await ctx.send("The NWS Office for " + ' '.join(args) + " is: " + forecastOffice(' '.join(args)))

@client.command(name="getUTC", help="Gets the current UTC time.")
async def getUTC(ctx) -> None:
    utc_time = await getUTCTime()
    await ctx.send(utc_time.strftime("%H:%M %m-%d-%y"))



@client.command(name="fetch", help="Fetches the latest Nadocast images. \n Usage: $fetch <params> \n Allowed params: sig, tor, wind, hail\n Examples: `$fetch tor`, `$fetch sig tor`")
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
