import os
from datetime import datetime, time, timedelta, timezone
import shutil
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from discord import Embed, File
from typing import List
from dotenv import load_dotenv
import pytz
from collections import Counter

load_dotenv()
APIKEY = os.getenv("APIKEY")


cooldowns = {"fetch": {"last_used": 0, "cooldown": 60}}


async def getUTCTime() -> datetime:
    dt = datetime.now(timezone.utc)

    utc_time = dt.replace(tzinfo=timezone.utc)

    return utc_time


async def getNadoCastData(
    time: datetime, models: str, extra: str, doNotInclude: str
) -> list[str]:

    # Get specific data from the datetime object
    month = time.strftime("%m")
    day = time.strftime("%d")
    year = time.strftime("%Y")
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
    folder_location = f"Nadocast_{timeNow}"

    # Get the html text from the url

    if os.path.exists(folder_location):
        if os.listdir(folder_location) != []:
            for file in os.listdir(folder_location):
                print(file)
                if isAcceptableFile(file, models, extra, doNotInclude):
                    file_list.append(os.path.join(folder_location, file))

            file_list.sort()
            if len(file_list) == 0:
                await log(
                    f"Images already are up to date for {timeNow}z, but no images were found, attempting to fetch new images."
                )
            else:
                await log(
                    f"Images already are up to date for {timeNow}z, returning them."
                )
                return file_list

    await log(f"Images out of date, trying to fetch images for {timeNow}z (from {url})")

    response = requests.get(url)

    # Check if the response is valid
    if response.status_code != 200:
        # Create fallback

        time = time - timedelta(hours=6)

        month = time.strftime("%m")
        day = time.strftime("%d")
        year = time.strftime("%Y")
        timeNow = time.strftime("%H")
        timeNowInt = int(timeNow)

        # Since the data is only available at 0Z, 12Z, 18Z, we need to round the time to the nearest available time
        if timeNowInt < 12:
            timeNow = 0
        elif 12 <= timeNowInt < 18:
            timeNow = 12
        elif 18 <= timeNowInt < 24:
            timeNow = 18

        url = "{4}{2}{1}/{2}{1}{0}/t{3}z/".format(
            day, month, year, timeNow, os.getenv("URL")
        )
        await log(
            f"Previous URL was 404, had to fallback, fetching images for {timeNow}z (from {url})"
        )
        await log("DEBUG: ", str(url), str(timeNowInt), str(timeNow))

        folder_location = f"Nadocast_{timeNow}"

    if os.path.exists(folder_location) and os.listdir(folder_location) != []:
        for file in os.listdir(folder_location):
            if isAcceptableFile(file, models, extra, doNotInclude):
                file_list.append(os.path.join(folder_location, file))
        file_list.sort()
        # await log(f"Images fetched for {timeNow}z: {file_list}")
        if len(file_list) == 0:
            await log(
                f"Images for {timeNow}z have already been downloaded, but no images were found, attempting to fetch new images."
            )
        else:
            await log(
                f"Images for {timeNow}z have already been downloaded, returning them instead of downloading new ones."
            )
            return file_list

    response = requests.get(url)

    if not os.path.exists(folder_location):
        await log(f"Had to create a new folder ({folder_location})")
        os.makedirs(folder_location)

    # Parse the html text
    soup = BeautifulSoup(response.text, "html.parser")

    # Download the images
    for link in soup.select("a[href$='.png']"):
        # await log(f"Found image: {link['href']}")
        # Name the png files using the last portion of each link which are unique in this case
        filename = os.path.join(folder_location, link["href"].split("/")[-1])
        true_file_name = filename.split("\\")[-1]

        if isAcceptableFile(true_file_name, models, extra, doNotInclude):
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
            f.write(
                f"{datetime.now()} - No images found for {folder_location}. Command locked for 1 minute. [THIS SHOULD NOT TRIGGER]\n"
            )
        return None
    return file_list


async def log(*params):
    with open("logs/general.log", "a") as f:
        text = " ".join(params)
        f.write(f"{datetime.now()} - {text} \n")


def isAcceptableFile(file: str, model: str, extra: str, doNotInclude: str) -> bool:
    if model in file and extra in file and doNotInclude not in file:
        return True
    return False

def checkOldFolders():
    time = datetime.now()
    timeNow = time.strftime("%H")
    timeNowInt = int(timeNow)

    if timeNowInt < 13:
        #timeNow = 0
        timeNow = 12
        shutil.rmtree(f"Nadocast_{timeNow}")
        timeNow = 18
        shutil.rmtree(f"Nadocast_{timeNow}")
    elif 13 <= timeNowInt < 18:
        #timeNow = 12
        timeNow = 0
        shutil.rmtree(f"Nadocast_{timeNow}")
        timeNow = 18
        shutil.rmtree(f"Nadocast_{timeNow}")
    elif 18 <= timeNowInt < 24:
        #timeNow = 18
        timeNow = 12
        shutil.rmtree(f"Nadocast_{timeNow}")
        timeNow = 0
        shutil.rmtree(f"Nadocast_{timeNow}")

def createWeatherEmbed(file: File, title: str, description: str, color) -> List:
    # file = File(filePath, filename="image.png")

    embed = Embed()

    embed.title = title
    embed.description = description
    embed.color = color

    embed.set_image(url="attachment://image.png")

    return [embed, file]


def forecastOffice(*args) -> str:

    result = f"{args}"

    base_url = "https://geocode.xyz"
    params = {
        "locate": result,
        "region": "US",
        "json": "1"
    }

    req_url = f"{base_url}/?{requests.utils.unquote(requests.compat.urlencode(params))}"
    try:
        resp = requests.get(req_url)
        resp.raise_for_status()
    except requests.RequestException as err:
        print("Error:", err)
        exit()

    geocode_data = resp.json()

    # Uncomment to debug coords being passed
    # print(f"\nLatitude: {geocode_data['latt']}, Longitude: {geocode_data['longt']}\n")

    points_url = f"https://api.weather.gov/points/{geocode_data['latt']},{geocode_data['longt']}"
    try:
        points_resp = requests.get(points_url)
        points_resp.raise_for_status()
    except requests.RequestException as err:
        print("Error:", err)
        return "There was an error processing the supplied location, please try again in a moment"

    points_data = points_resp.json()

    office_url = f"{points_data['properties']['forecastOffice']}"

    office_code = f"{points_data['properties']['cwa']}"
    try:
        office_resp = requests.get(office_url)
        office_resp.raise_for_status()
    except requests.RequestException as err:
        print("Error:", err)
        return "There was an error finding the forecast office, please try again in a moment"

    office_data = office_resp.json()

    #print(type(office_data['name']))
    return office_data['name'] + " | " + "NWS Website: https://www.weather.gov/" + office_code

def fetch_json_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def parse_utc_date(utc_date_str):
    """Parse UTC date string to datetime object with UTC timezone"""
    parsed_date = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
    return parsed_date.replace(tzinfo=pytz.UTC)


def format_utc_date(utc_date_str):
    """Convert UTC ISO format date to a more readable format in local time"""
    utc_date = parse_utc_date(utc_date_str)
    local_tz = datetime.now(pytz.UTC).astimezone().tzinfo
    local_date = utc_date.astimezone(local_tz)
    return local_date.strftime("%B %d, %Y at %I:%M %p %Z")


def filter_outlooks_by_time_range(
    outlooks, start_date=None, end_date=None, threshold=None
):
    """Filter outlooks based on time range and optional threshold"""
    filtered_outlooks = []

    for outlook in outlooks:
        # Parse the UTC issue date (already timezone-aware)
        issue_date = parse_utc_date(outlook["utc_issue"])

        # Check date range
        date_in_range = True
        if start_date:
            date_in_range = date_in_range and issue_date >= start_date
        if end_date:
            date_in_range = date_in_range and issue_date <= end_date

        # Check threshold if specified
        threshold_match = not threshold or outlook["threshold"] == threshold

        # Add to filtered list if both conditions are met
        if date_in_range and threshold_match:
            filtered_outlooks.append(outlook)

    return filtered_outlooks


def create_formatted_table(data, headers):
    """Create a custom formatted table with proper header alignment"""
    if not data:
        return "No data available"

    # Get the maximum width for each column
    col_widths = [max(len(str(row[i])) for row in data) for i in range(len(data[0]))]

    for i, header in enumerate(headers):
        col_widths[i] = max(col_widths[i], len(header))

    # Create the header row with proper alignment
    header_row = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * w for w in col_widths)

    # Create data rows
    data_rows = [
        " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
        for row in data
    ]

    # Combine all parts
    table = f"{header_row}\n{separator}\n" + "\n".join(data_rows)
    return table