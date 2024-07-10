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


@client.command(name="test")
async def test(ctx, *args) -> None:
    await ctx.send(args[0])


@client.command(name="fetch")
async def fetch(ctx, *args) -> None:
    await ctx.send("Fetching...")

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

    # Fetch data, get our list of images
    result = await getNadoCastData(await getUTCTime())
    # print(result)
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
        ):
            files.append(discord.File(file))
            # debug.append(file)
            continue
        if args[0] == "sig" and args[1] != "None" and f"{args[0]}_{args[1]}" in file:
            files.append(discord.File(file))
            # debug.append(file)
            continue

    if len(files) == 0:
        return await ctx.send(
            "It appears Nadocast has not put out the new images for this time range! Please try again in a minute."
        )
    # debug.sort()
    # await ctx.send(debug)
    await ctx.send(files=files)


if type(TOKEN) == type(None):
    print("Please follow the readme to setup the bot!")

if __name__ == "__main__":
    client.run(TOKEN)
