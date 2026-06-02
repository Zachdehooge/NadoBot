import os
import shutil
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import List
from urllib.parse import urljoin

try:
    import pytz
except ImportError:
    pytz = None

import requests
from bs4 import BeautifulSoup
from discord import Embed, File
from dotenv import load_dotenv

load_dotenv()
APIKEY = os.getenv("APIKEY")


cooldowns = {"fetch": {"last_used": 0, "cooldown": 30}}


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
    for folder in ["Nadocast_0", "Nadocast_12", "Nadocast_18"]:
        try:
            shutil.rmtree(folder)
        except FileNotFoundError:
            continue

def createWeatherEmbed(file: File, title: str, description: str, color) -> List:
    # file = File(filePath, filename="image.png")

    embed = Embed()

    embed.title = title
    embed.description = description
    embed.color = color

    embed.set_image(url="attachment://image.png")

    return [embed, file]


def forecastOffice(location) -> str:
    result = f"{location}"

    base_url = "https://geocode.xyz"
    params = {"locate": result, "region": "US", "json": "1"}

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

    points_url = (
        f"https://api.weather.gov/points/{geocode_data['latt']},{geocode_data['longt']}"
    )
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

    # print(type(office_data['name']))
    return (
        office_data["name"]
        + " | "
        + "NWS Website: https://www.weather.gov/"
        + office_code
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


def get_next_nadocast_runs():
    """Get next NadoCast model runs within the next 24 hours"""
    from datetime import datetime, timedelta, timezone
    
    now_utc = datetime.now(timezone.utc)
    runs = []
    
    # NadoCast runs at 0z, 12z, 18z
    nadocast_times = [0, 12, 18]
    
    for hour_offset in range(25):  # Check next 25 hours to find all runs
        check_time = now_utc + timedelta(hours=hour_offset)
        if check_time.hour in nadocast_times:
            # Round to the exact hour
            run_time = check_time.replace(minute=0, second=0, microsecond=0)
            time_until = run_time - now_utc
            
            if time_until.total_seconds() > 0:  # Only future runs
                runs.append({
                    'time': run_time,
                    'time_until_hours': time_until.total_seconds() / 3600,
                    'run_hour': check_time.hour,
                    'type': 'nadocast'
                })
    
    return runs


def get_next_spc_outlooks():
    """Get next SPC outlook issuances within the next 24 hours"""
    from datetime import datetime, timedelta, timezone
    
    now_utc = datetime.now(timezone.utc)
    outlooks = []
    
    # Day 1 outlooks: 0600Z, 1300Z, 1630Z, 2000Z, 0100Z
    day1_times = [(6, 0), (13, 0), (16, 30), (20, 0), (1, 0)]
    
    # Day 2 outlooks: 0100Z (1 AM CST/CDT), 1730Z  
    day2_times = [(1, 0), (17, 30)]
    
    # Day 3 outlooks: 0830Z standard time, 0730Z daylight time
    # We'll use 0800Z as an approximation since this changes with DST
    day3_times = [(8, 0)]
    
    # Combine all outlook times with labels
    all_outlooks = []
    
    for hour, minute in day1_times:
        all_outlooks.append(('Day 1', hour, minute))
    for hour, minute in day2_times:
        all_outlooks.append(('Day 2', hour, minute))
    for hour, minute in day3_times:
        all_outlooks.append(('Day 3', hour, minute))
    
    for hour_offset in range(25):  # Check next 25 hours
        check_time = now_utc + timedelta(hours=hour_offset)
        
        for day_type, outlook_hour, outlook_minute in all_outlooks:
            # Check if current time matches outlook time (within 30 minutes)
            if (check_time.hour == outlook_hour and 
                abs(check_time.minute - outlook_minute) < 30):
                
                # Set to exact outlook time
                run_time = check_time.replace(
                    hour=outlook_hour, 
                    minute=outlook_minute, 
                    second=0, 
                    microsecond=0
                )
                
                time_until = run_time - now_utc
                
                if time_until.total_seconds() > 0:  # Only future outlooks
                    outlooks.append({
                        'type': 'spc',
                        'day': day_type,
                        'time': run_time,
                        'time_until_hours': time_until.total_seconds() / 3600,
                        'time_str': f"{run_time.hour:02d}:{run_time.minute:02d}Z"
                    })
    
    # Sort by time
    outlooks.sort(key=lambda x: x['time'])
    
    return outlooks


def format_time_until(hours, use_discord_timestamp=True):
    """Format time until an event in a readable way"""
    from datetime import datetime, timezone, timedelta
    
    if hours < 0.0167:  # Less than 1 minute
        return "now" if not use_discord_timestamp else f"<t:{int((datetime.now(timezone.utc) + timedelta(seconds=0)).timestamp())}:R>"
    elif hours < 1:
        minutes = int(hours * 60)
        if use_discord_timestamp:
            future_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            return f"<t:{int(future_time.timestamp())}:R>"
        else:
            return f"in {minutes}m"
    elif hours < 24:
        hours_int = int(hours)
        minutes = int((hours % 1) * 60)
        if use_discord_timestamp:
            future_time = datetime.now(timezone.utc) + timedelta(hours=hours_int, minutes=minutes)
            return f"<t:{int(future_time.timestamp())}:R>"
        else:
            if minutes > 0:
                return f"in {hours_int}h {minutes}m"
            else:
                return f"in {hours_int}h"
    else:
        days = int(hours // 24)
        remaining_hours = int(hours % 24)
        if use_discord_timestamp:
            future_time = datetime.now(timezone.utc) + timedelta(days=days, hours=remaining_hours)
            return f"<t:{int(future_time.timestamp())}:R>"
        else:
            if remaining_hours > 0:
                return f"in {days}d {remaining_hours}h"
            else:
                return f"in {days}d"


def format_datetime_local(utc_dt):
    """Format UTC datetime in local time"""
    if pytz:
        local_tz = datetime.now(pytz.UTC).astimezone().tzinfo
        local_dt = utc_dt.astimezone(local_tz)
        return local_dt.strftime("%I:%M %p %Z")
    else:
        # Fallback to system timezone if pytz not available
        local_dt = utc_dt.replace(tzinfo=timezone.utc).astimezone()
        return local_dt.strftime("%I:%M %p")


def get_event_status(time_until_hours, is_next=False):
    """Get status indicator and color for an event"""
    if time_until_hours < 0:
        return {"status": "✅ DONE", "color": "⚫"}
    elif time_until_hours < 0.0167:  # Less than 1 minute
        return {"status": "🔴 NOW", "color": "🔴"}
    elif is_next:
        return {"status": "🔴 NEXT", "color": "🔴"}
    else:
        return {"status": "⏭️ THEN", "color": "⏭️"}


def create_whatsnext_embed():
    """Create comprehensive 'What's Next' embed"""
    from datetime import datetime, timezone
    import discord
    
    now_utc = datetime.now(timezone.utc)
    
    # Get all upcoming events
    nadocast_runs = get_next_nadocast_runs()
    spc_outlooks = get_next_spc_outlooks()
    
    # Combine and sort all events
    all_events = nadocast_runs + spc_outlooks
    all_events.sort(key=lambda x: x['time_until_hours'])
    
    # Filter events within 24 hours
    future_events = [e for e in all_events if 0 <= e['time_until_hours'] <= 24]
    
    embed = discord.Embed(
        title="⏰ What's Next - Live Schedule",
        color=discord.Color.blue(),
        timestamp=now_utc
    )
    
    # Build embed content
    content_lines = []
    
    # NadoCast Section
    nadocast_events = [e for e in future_events if e['type'] == 'nadocast']
    content_lines.append("**🤖 NadoCast Model Runs**")
    content_lines.append("━━━━━━━━━━━━━━━━━━━━━")
    
    for i, event in enumerate(nadocast_events):
        status_info = get_event_status(event['time_until_hours'], is_next=(i == 0 and event['time_until_hours'] > 0))
        local_time = format_datetime_local(event['time'])
        
        line = f"{status_info['color']} {event['run_hour']}z Run - {format_time_until(event['time_until_hours'])} ({local_time})"
        content_lines.append(line)
    
    if not nadocast_events:
        content_lines.append("❌ No runs scheduled in next 24 hours")
    
    content_lines.append("")  # Empty line
    
    # SPC Outlooks Section
    spc_events = [e for e in future_events if e['type'] == 'spc']
    content_lines.append("**🌪️ SPC Outlooks**")
    content_lines.append("━━━━━━━━━━━━━━━━━━━━━")
    
    # Group by day
    day_groups = {}
    for event in spc_events:
        day = event['day']
        if day not in day_groups:
            day_groups[day] = []
        day_groups[day].append(event)
    
    for day in ['Day 1', 'Day 2', 'Day 3']:
        if day in day_groups:
            content_lines.append(f"**{day}**")
            for event in day_groups[day]:
                status_info = get_event_status(event['time_until_hours'], 
                                          is_next=(len(nadocast_events) == 0 and len(day_groups[day]) == 1))
                local_time = format_datetime_local(event['time'])
                
                line = f"{status_info['color']} {event['time_str']} ({local_time}) - {format_time_until(event['time_until_hours'])}"
                content_lines.append(line)
    
    if not spc_events:
        content_lines.append("❌ No outlooks scheduled in next 24 hours")
    
    # Set embed description
    embed.description = "\n".join(content_lines)
    embed.set_footer(text="Updates every minute • Times show as relative in Discord • Use /whatsnext stop to halt updates")
    
    return embed
