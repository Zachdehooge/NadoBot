import os
from datetime import datetime, timedelta, timezone
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

cooldowns = {"fetch": {"last_used": 0, "cooldown": 60}}


# discontinued?
async def getUTCTime() -> datetime:
    dt = datetime.now(timezone.utc)

    utc_time = dt.replace(tzinfo=timezone.utc)

    return utc_time


async def getNadoCastData(time: datetime, models: str, extra: str) -> list[str]:

    print("Models:", models, "Extra:", extra)

    # Get specific data from the datetime object
    month = time.strftime("%m")
    day = time.strftime("%d")
    year = time.strftime("20%y")
    timeNow = time.strftime("%H")
    timeNowInt = int(timeNow)

    # Since the data is only available at 0Z, 12Z, 18Z, we need to round the time to the nearest available time
    if timeNowInt < 13:
        timeNow = 0
    elif 13 <= timeNowInt < 18:
        timeNow = 12
    elif 18 <= timeNowInt < 24:
        timeNow = 18

    # URL Structure
    url = "{4}{2}{1}/{2}{1}{0}/t{3}z/".format(
        day, month, year, timeNow, os.getenv("URL")
    )

    # Create a list so we can use it back in main.py
    file_list = []

    # Folder Structure, and create the folder if it doesn't exist, but if it does, return the already downloaded images
    folder_location = r"Nadocast\\{1}_{0}_{2}_{3}z".format(day, month, year, timeNow)

    # Get the html text from the url

    if os.path.exists(folder_location):
        if os.listdir(folder_location) != []:
            for file in os.listdir(folder_location):
                print(file)
                if models in file and extra in file:
                    file_list.append(os.path.join(folder_location, file))

            file_list.sort()
            await log(f"Images already are up to date for {timeNow}z, returning them.")
            return file_list

    await log(f"Images out of date, trying to fetch images for {timeNow}z (from {url})")

    response = requests.get(url)

    # Check if the response is valid
    if response.status_code != 200:
        # Create fallback

        time = time - timedelta(hours=6)

        month = time.strftime("%m")
        day = time.strftime("%d")
        year = time.strftime("20%y")
        timeNow = time.strftime("%H")
        timeNowInt = int(timeNow)

        # Since the data is only available at 0Z, 12Z, 18Z, we need to round the time to the nearest available time
        if timeNowInt < 12:
            timeNow = 0
        elif 12 <= timeNowInt < 18:
            timeNow = 12
        elif 18 <= timeNowInt < 24:
            timeNow = 18

        url = "{4}{2}{1}/{2}{1}{0}/t{3}z/".format(day, month, year, timeNow, os.getenv("URL"))
        await log(f"Previous URL was 404, had to fallback, fetching images for {timeNow}z (from {url})")
        await log("DEBUG: ", str(url), str(timeNowInt), str(timeNow))

        folder_location = r"Nadocast\\{1}_{0}_{2}_{3}z".format(day, month, year, timeNow)

    if os.path.exists(folder_location) and os.listdir(folder_location) != []:
        for file in os.listdir(folder_location):
            if models in file and extra in file:
                file_list.append(os.path.join(folder_location, file))
        file_list.sort()
        # await log(f"Images fetched for {timeNow}z: {file_list}")
        await log(f"Images for {timeNow}z have already been downloaded, returning them instead of downloading new ones.")
        return file_list

    response = requests.get(url)

    if not os.path.exists(folder_location):
        await log(f"Had to create a new folder ({folder_location})")
        os.makedirs(folder_location)

    # Parse the html text
    soup = BeautifulSoup(response.text, "html.parser")

    # Download the images
    for link in soup.select("a[href$='.png']"):
        await log(f"Found image: {link['href']}")
        # Name the png files using the last portion of each link which are unique in this case
        filename = os.path.join(folder_location, link["href"].split("/")[-1])
        print(filename, models, extra)
        true_file_name = filename.split("\\")[-1]

        if models in true_file_name and extra in true_file_name:
            file_list.append(filename)
            with open(filename, "wb") as f:
                f.write(requests.get(urljoin(url, link["href"])).content)

    sepeartor = " ,"
    text = sepeartor.join(file_list)
    if text == "":
        text = "No images found"
    # await log(f"Images fetched for {timeNow}z: {file_list}")
    await log(f"New images have been downloaded for {timeNow}z, returning them.")

    file_list.sort()

    # OLD CODE, KEPT incase this does get triggered, meaning the list is somehow empty when that should not be possible.
    if len(file_list) == 0:
        with open("logs/error.log", "a") as f:
            f.write(f"{datetime.now()} - No images found for {folder_location}. Command locked for 1 minute. [THIS SHOULD NOT TRIGGER]\n")
        return None
    return file_list


async def log(*params):
    if not os.path.exists("logs"):
        os.makedirs("logs")
    with open("logs/general.log", "a") as f:
        text = " ".join(params)
        f.write(f"{datetime.now()} - {text} \n")
