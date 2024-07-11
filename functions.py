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


async def getNadoCastData(time: datetime) -> list[str]:

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
    if os.path.exists(folder_location):
        for file in os.listdir(folder_location):
            file_list.append(os.path.join(folder_location, file))
        file_list.sort()
        return file_list

    if not os.path.exists(folder_location):
        os.makedirs(folder_location)

    # Get the html text from the url
    response = requests.get(url)

    # Parse the html text
    soup = BeautifulSoup(response.text, "html.parser")

    # Download the images
    for link in soup.select("a[href$='.png']"):
        # Name the png files using the last portion of each link which are unique in this case
        filename = os.path.join(folder_location, link["href"].split("/")[-1])

        file_list.append(filename)

        with open(filename, "wb") as f:
            f.write(requests.get(urljoin(url, link["href"])).content)

    file_list.sort()
    if len(file_list) == 0:
        os.rmdir(folder_location)
        with open("error.log", "a") as f:
            f.write(
                f"{datetime.now()} - No images found for {folder_location}. Command locked for 1 minute. Folder deleted. \n"
            )
        return None
    return file_list
