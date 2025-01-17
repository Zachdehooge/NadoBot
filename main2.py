from discord.ext import commands
from dotenv import load_dotenv
from functions2 import *
import discord
import os

# Retrive token from .env and if we are debugging
load_dotenv()
TOKEN: str = os.getenv("TOKEN")
DEBUG: bool = str(os.getenv("DEBUG")).lower() == "true"

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

allowed_args = {"before": ["sig"], "middle": ["tor", "wind", "hail"], "after": ["life"]}

activeImages = {
    "none": {
        "tor": [],
        "wind": [],
        "hail": [],
    },
    "sig": {
        "tor": [],
        "wind": [],
        "hail": [],
    },
    "life": {
        "tor": [],
        "wind": [],
        "hail": [],
    },
}

__currentModel = {}

# Valid time ranges (We can remove this later, but it's good to have for now)
validD1TimeRanges = ["f01-23", "f02-23", "f02-17", "f01-17", "f12-35"]


# TODO: Modify the help command to provide descriptions and category title
class MyHelpCommand(commands.MinimalHelpCommand):
    async def send_pages(self):
        destination = self.get_destination()
        e = discord.Embed(color=discord.Color.blurple(), description="")
        for page in self.paginator.pages:
            e.description += page
        await destination.send(embed=e)


client.help_command = MyHelpCommand()


@client.command(name="getUTC", help="Gets the current UTC time")
async def getUTC(ctx) -> None:
    await ctx.send(getUTCTime().strftime("%Y-%m-%d %H:%M:%S"))


@client.command(
    name="fetch",
    help="Fetches the latest Nadocast images. \n Usage: $fetch <params> \n Allowed params: sig, tor, wind, hail, life\n Please note: sig can be a \n Examples: `$fetch tor`, `$fetch sig tor`, `$fetch tor life`",
)
async def fetch(ctx, *args) -> None:

    await log("DEBUG: Fetch command called with args:", ",".join(args))

    fetchCooldown = cooldowns["fetch"]

    if len(args) == 0:
        await ctx.send("You must provide at least one argument.")
        return

    if len(args) > 2:
        await ctx.send(
            "You can only provide up to two arguments. (ex. sig tor life isn't a file we have, so it doesn't exist)"
        )
        return

    for arg in args:
        if (
            arg
            not in allowed_args["before"]
            + allowed_args["middle"]
            + allowed_args["after"]
        ):
            await ctx.send(
                f"Invalid argument: {arg}, please retry with proper arguments."
            )
            return

    if (
        fetchCooldown["last_used"] + fetchCooldown["cooldown"]
        > datetime.now().timestamp()
    ):
        return await ctx.send("Please wait a minute before using this command again!")
    
    result = await getNadocastData()

    embed, files, buttons = await createWeatherEmbed(result, "Nadocast", "Nadocast", 0x00FF00)
    currentFile = files[0]

    ctx.send(embed=embed, file=currentFile, components=buttons)

if DEBUG:
    @client.event
    async def on_command_error(ctx, error):
        await ctx.send(f"An error occurred: {str(error)}")

    @client.event
    async def on_command(ctx):
        print(f"Command {ctx.command} called with args: {ctx.args}")

# Very strange to put this here but we are having issues
# with the imports, so we are putting it here for now.
def getCurrentModel():
    print(__currentModel)
    return __currentModel

def getActiveImages():
    return activeImages


if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.makedirs("logs")
    # if the token is empty, print a message to the console
    if type(TOKEN) == type(None) or len(TOKEN) == 0:
        print("Please follow the README to setup the bot!")
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

        __currentModel = {"model": model, "extra": extra, "doNotInclude": notExtra}
        client.run(TOKEN)



print(__currentModel)