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


# Events
@client.event
async def on_ready() -> None:
    print(f"We have logged in as {client.user}")


# Commands


# TODO: Modify the help command to provide descriptions and category title
class MyHelpCommand(commands.MinimalHelpCommand):
    async def send_pages(self):
        destination = self.get_destination()
        e = discord.Embed(color=discord.Color.blurple(), description="")
        for page in self.paginator.pages:
            e.description += page
        await destination.send(embed=e)


client.help_command = MyHelpCommand()


@client.command(name="getUTC", help="Get the current UTC time.")
async def getUTC(ctx) -> None:
    utc_time = await getUTCTime()
    await ctx.send(utc_time.strftime("%Y-%m-%d %H:%M:%S"))


@client.command(name="fetch", help="Fetch the latest Nadocast images. \n Usage: !fetch <param>\nAllowed params: sig, life, tor, wind, hail")
async def fetch(ctx, *args) -> None:

    await log("DEBUG: Fetch command called with args:", ",".join(args))

    cooldown = cooldowns["fetch"]

    # TODO: This try/except block is hardcoded with the params, needs fixing + adding the life risk param.
    # Currently works and is not urgent.
    allowed_params = ["sig", "life", "tor", "wind", "hail"]

    # Lets check the args to make sure we should do this request.
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

    await ctx.send("Fetching... please wait.")
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
    if result == None:
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

    for file in result:
        # TODO: Add a case for when the user wants to fetch all images &
        # for tor life risk. (This was recently added in the Nadocast website, under 2024 models)
        # TODO: For some reason, the forecast hours are still changing. This this needs to be created better.
        # As of today (Nov 3rd, 2024), a new range has been introduced: f12-35, strange.

        # Checks if the file is the correct to what the user wants, and if so, adds it to an list to send later.
        if (
            args[0] != "sig"
            and args[0] != "None"
            and args[0] in file
            and "sig" not in file
            and (
                "f01-23" in file
                or "f02-23" in file
                or "f02-17" in file
                or "f01-17" in file
                or "f12-35" in file
            )
        ):
            files.append(discord.File(file))
            # Also for debug (the line below)
            debug.append(file)
            continue
        if (
            args[0] == "sig"
            and args[1] != "None"
            and f"{args[0]}_{args[1]}" in file
            and (
                "f01-23" in file
                or "f02-23" in file
                or "f02-17" in file
                or "f01-17" in file
                or "f12-35" in file
            )
        ):
            files.append(discord.File(file))
            # Also for debug (the line below)
            debug.append(file)
            continue

    # This is never triggered, but if it is, something went wrong.
    if len(files) == 0:
        return await ctx.send(
            "It appears Nadocast has not put out the new images for this time range! Please try again in a minute."
        )

    # can be removed, i think, should just be for debugging
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

    embed = discord.Embed(title=f"{"".join(args)}", description=text, color=hexcode)

    # Send the embed then the files (as of right now, files go above embeds... for some reason, so they must be split)
    await ctx.send(embed=embed)
    await ctx.send(files=files)

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
        model = os.getenv("MODELS")
        if model == "2024abs":
            model = "_2024_"
            extra = "abs"
            notExtra = "?"
        if model == "2024":
            model = "_2024_"
            extra = ""
            notExtra = "abs"
        if model == "2022abs":
            model = "_2022_"
            extra = "abs"
            notExtra = "?"
        if model == "2022":
            model = "_2022_"
            extra = ""
            notExtra = "abs"

        # If they leave it blank, we will fetch all models.
        if model == "":
            extra = ""
            notExtra = "?"

        client.models = {"model": model, "extra": extra, "doNotInclude": notExtra}
        client.run(TOKEN)
