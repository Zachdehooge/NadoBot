# RSS Alert System Implementation Plan

## 📋 Overview
Transform the NadoBot RSS alert system from potentially resending all messages to a precise minute-by-minute system that only sends genuinely new alerts.

## 🔍 Current Issues Identified
1. **Line 149**: `for entry in reversed(feed.entries):` - Processing in reverse causes issues
2. **Line 160**: Only checks per-guild `posted_items`, no global duplicate prevention
3. **Memory leak**: `posted_items` grows indefinitely (capped at 100 per guild but no global tracking)
4. **No time validation**: Doesn't check if alerts are actually recent

## 🎯 Implementation Changes

### 1. Add New Imports and Global Variables
**Location**: After line 10 (imports section)
```python
from collections import deque
from urllib.parse import urlparse, parse_qs
```

**Location**: After line 31 (global variables section)
```python
# Global PID tracking system
global_seen_pids = deque(maxlen=300)  # Track last 300 PIDs globally
MAX_TRACKED_PIDS = 300
DEBUG_NEW_ALERTS = False
```

### 2. Add PID Extraction Function
**Location**: After line 104 (after parse_weather_alert function)
```python
def extract_pid_from_link(link):
    """Extract unique PID from RSS link URL"""
    try:
        if not link:
            return None
        
        # Parse URL and extract 'pid' parameter
        parsed = urlparse(link)
        params = parse_qs(parsed.query)
        pid = params.get('pid', [None])[0]
        
        return pid if pid else None
    except Exception as e:
        print(f"Error extracting PID from link {link}: {e}")
        return None
```

### 3. Refactor Core RSS Processing Logic
**Critical Changes to `check_rss_feed()` function:**

**Remove lines 148-175** and replace with:
```python
# Process entries in natural order (newest first from RSS)
new_alerts_count = 0

for entry in feed.entries:
    title = entry.get("title", "")
    
    # Filter: only post severe thunderstorm and tornado warnings
    if not is_severe_weather_warning(title):
        continue
    
    # Extract PID for reliable uniqueness check
    link = entry.get("link", "")
    pid = extract_pid_from_link(link)
    
    if not pid:
        continue
    
    # Check if we've already processed this PID globally
    if pid in global_seen_pids:
        continue
    
    # This is a new alert, process it
    print(f"NEW ALERT DETECTED: PID={pid}, Title={title[:50]}...")
    
    # Add to global tracking immediately to prevent race conditions
    global_seen_pids.append(pid)
    
    # Process for each configured guild
    for guild_id, channel_id in guild_channels.items():
        channel = client.get_channel(channel_id)
        if not channel:
            continue
            
        # Ensure this guild has a posted_items set
        if guild_id not in posted_items:
            posted_items[guild_id] = set()
        
        # Check if this guild has already posted this item
        if link not in posted_items[guild_id]:
            try:
                # Create and send embed
                embed = parse_weather_alert(entry)
                await channel.send(embed=embed)
                
                # Mark as posted for this guild
                posted_items[guild_id].add(link)
                new_alerts_count += 1
                
                if DEBUG_NEW_ALERTS:
                    print(f"Posted alert to guild {guild_id}: {title[:50]}...")
                
                # Avoid rate limiting
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error posting to guild {guild_id}: {e}")
```

### 4. Update Memory Management
**Location**: Replace lines 181-185 in check_rss_feed() function
```python
# Per-guild memory management (keep last 100 links per guild)
if guild_id in posted_items:
    if len(posted_items[guild_id]) > 100:
        posted_items_list = list(posted_items[guild_id])
        posted_items[guild_id].clear()
        posted_items[guild_id].update(posted_items_list[-100:])

# Global PID memory management (handled automatically by deque maxlen)
if DEBUG_NEW_ALERTS:
    print(f"Global PIDs tracked: {len(global_seen_pids)}/{MAX_TRACKED_PIDS}")

if new_alerts_count > 0:
    print(f"RSS Check: Posted {new_alerts_count} new alerts across all guilds")
```

### 5. Enhance Startup Logic
**Location**: Modify `mark_existing_alerts_as_posted()` function (lines 201-216)
```python
def mark_existing_alerts_as_posted():
    """Mark all current RSS entries as already posted to avoid spam on startup"""
    try:
        feed = feedparser.parse(RSS_URL)
        
        # Initialize global PIDs from current feed
        for entry in feed.entries:
            pid = extract_pid_from_link(entry.get("link", ""))
            if pid:
                global_seen_pids.append(pid)
        
        # Initialize per-guild tracking (keep existing logic)
        for guild_id in guild_channels.keys():
            if guild_id not in posted_items:
                posted_items[guild_id] = set()
            for entry in feed.entries:
                link = entry.get("link", "")
                if link:
                    posted_items[guild_id].add(link)
        
        print(f"Marked {len(feed.entries)} existing alerts as already posted")
        print(f"Global PIDs initialized: {len(global_seen_pids)}")
    except Exception as e:
        print(f"Error marking existing alerts: {e}")
```

### 6. Update Configuration Loading
**Location**: Modify `load_config()` function to handle global PIDs
```python
def load_config():
    """Load configuration from file"""
    global guild_channels, posted_items, global_seen_pids
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                # Load guild -> channel mapping
                guild_channels = {
                    int(k): v for k, v in config.get("guild_channels", {}).items()
                }
                print(f"Loaded {len(guild_channels)} guild configurations")
                for guild_id, channel_id in guild_channels.items():
                    print(f"  Guild {guild_id} -> Channel {channel_id}")
                    # Initialize posted_items set for each guild
                    if guild_id not in posted_items:
                        posted_items[guild_id] = set()
        except Exception as e:
            print(f"Error loading config: {e}")
    else:
        print("No config file found, starting fresh")
    
    # Initialize global PIDs tracking
    global_seen_pids = deque(maxlen=MAX_TRACKED_PIDS)
```

## 🧪 Testing Strategy

### 1. Memory Usage Test
- Monitor `global_seen_pids` size stays capped at 300
- Verify deque automatically removes oldest entries

### 2. Duplicate Prevention Test
- Run RSS check multiple times in quick succession
- Ensure no duplicate alerts are sent
- Verify global PID tracking prevents cross-guild duplicates

### 3. New Alert Detection Test
- Add new RSS item manually or wait for natural feed update
- Verify it's detected and sent to all guilds
- Check logging shows "NEW ALERT DETECTED" message

### 4. Cross-Guild Test
- Configure multiple guilds
- Ensure alerts go to all guilds without global duplicates
- Verify per-guild `posted_items` still works correctly

### 5. Startup Behavior Test
- Restart bot
- Verify existing alerts are marked as posted
- Confirm no spam on startup

## 🔧 Configuration Options

### New Global Variables
```python
MAX_TRACKED_PIDS = 300  # How many PIDs to track globally (~2-3 hours)
DEBUG_NEW_ALERTS = False  # Enable verbose logging for new alerts
```

### Existing Configuration
```python
CHECK_INTERVAL = 1  # Already set to 1 minute (perfect)
```

## ✅ Expected Benefits

1. **No More Resending**: Global PID tracking prevents all duplicates
2. **Memory Efficient**: Sliding window prevents unlimited growth
3. **Minute-by-Minute**: True new alert detection every check
4. **Reliable**: PID extraction more robust than link comparison
5. **Preserves Discord Messages**: No message deletion from channels
6. **Better Performance**: Natural RSS order processing

## 🚀 Implementation Steps

1. **Add imports and global variables**
2. **Implement PID extraction function**
3. **Refactor RSS processing logic**
4. **Update memory management**
5. **Enhance startup logic**
6. **Test thoroughly**

## 📝 Notes

- The `reversed(feed.entries)` call is removed - RSS naturally provides newest first
- Global PID tracking prevents duplicates across all guilds
- Per-guild `posted_items` maintained for individual guild tracking
- Memory automatically managed by deque with maxlen
- All Discord messages remain untouched in channels
- Debug logging available via `DEBUG_NEW_ALERTS` flag

This implementation transforms the bot into a precise, memory-efficient alert detection system.