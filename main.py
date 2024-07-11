from discord.ext import commands
from dotenv import load_dotenv
from functions import *
import discord
import time
import os

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
@client.command(name="getUTC")
async def getUTC(ctx) -> None:
    utc_time = await getUTCTime()
    await ctx.send(utc_time.strftime("%Y-%m-%d %H:%M:%S"))


@client.command(name="fetch")
async def fetch(ctx, *args) -> None:

    cooldown = cooldowns["fetch"]

    allowed_params = ["sig", "tor", "wind", "hail"]

    # Lets check the args to make sure we should do this request.
    try:
        allowed_params.index(args[0])

        if args[0] == "sig" and args[1] != None:
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
    result = await getNadoCastData(UTC)

    timeNow = UTC.strftime("%H")
    timeNowInt = int(timeNow)

    # Since the data is only available at 0Z, 12Z, 18Z, we need to round the time to the nearest available time
    if timeNowInt < 13:
        timeNow = 0
    elif 13 <= timeNowInt < 18:
        timeNow = 12
    elif 18 <= timeNowInt < 24:
        timeNow = 18

    if result == None:
        await log(f"Error: No images found for {timeNow}Z, current UTC is {timeNowInt}z.")
        await ctx.send(
            f"It appears Nadocast has not put out the new images for this time range ({timeNow}z)! Please try again in a minute."
        )
        cooldown["last_used"] = datetime.now().timestamp()
        return

    # Send the images
    files = []
    # debug = []
    # print(args)

    for file in result:
        if (
            args[0] != "sig"
            and args[0] != "None"
            and args[0] in file
            and "sig" not in file
            and "f02-23" in file
        ):
            files.append(discord.File(file))
            # debug.append(file)
            continue
        if (
            args[0] == "sig"
            and args[1] != "None"
            and f"{args[0]}_{args[1]}" in file
            and "f02-23" in file
        ):
            files.append(discord.File(file))
            # debug.append(file)
            continue

    if len(files) == 0:
        return await ctx.send(
            "It appears Nadocast has not put out the new images for this time range! Please try again in a minute."
        )
    # debug.sort()
    # await ctx.send(debug)
    text = ""

    if f"{timeNow}z" in result[0]:
        text = f"Here are the images for {timeNow}z!"
    else:
        UTC = UTC - timedelta(hours=6)

        hour = int(UTC.strftime("%H"))

        if hour < 13:
            hour = 0
        elif 13 <= hour < 18:
            hour = 12
        elif 18 <= hour < 24:
            hour = 18
        text = f"Sorry! It appears Nadocast hasn't uploaded the images for {timeNow}z, here are {hour}z's instead!"
        
    await ctx.send(text, files=files)


if type(TOKEN) == type(None):
    print("Please follow the readme to setup the bot!")

if __name__ == "__main__":
    client.run(TOKEN)
