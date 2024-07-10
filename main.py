from discord.ext import commands
from dotenv import load_dotenv
from functions import *
import discord
import time
import os

#Retrive token from .env
load_dotenv()
TOKEN = os.getenv("TOKEN")

#configure bot
intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix="$", intents=intents)

#commands
@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")

@client.command(name="getUTC")
async def getUnixTime(ctx):
    await ctx.send(f'<t:{int(time.time())}:f>')

client.run(TOKEN)
