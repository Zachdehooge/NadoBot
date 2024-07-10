import aiohttp
import os
from datetime import datetime, timedelta, timezone
  
async def getUTCTime() -> datetime:
    dt = datetime.now(timezone.utc) 
  
    utc_time = dt.replace(tzinfo=timezone.utc) 

    return utc_time
