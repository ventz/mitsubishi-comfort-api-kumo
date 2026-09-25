# Mitsubishi Comfort / Kumo Cloud API

A documented API reference and Python client for the Mitsubishi **Comfort** app (the rebranded
successor to the kumo cloud app) and its cloud backend. Control your minisplits and ducted units
from anywhere via the cloud API.

Covers both API generations against the same `app-prod.kumocloud.com` backend:

- **v3** — accounts, sites, zones, devices, device control, real-time Socket.IO
- **v4** — schedule seasons/schedules/events (documented from Comfort app `3.5.0`)

## Overview

This is a **cloud-only** client that communicates with Kumo Cloud servers. It does not require local network access to your units or knowledge of device IPs/passwords.

**Key Benefits:**
- Control units from anywhere (not just your local network)
- Simple setup - just your Kumo Cloud credentials
- No need to discover device IPs or configure local access
- Works with all Kumo Cloud connected devices

**Trade-offs vs Local API:**
- Requires internet connectivity
- Slightly higher latency than local control
- Subject to Kumo Cloud rate limits (50 req/min)

## Features

### Device Control
- **Temperature** - Set heating/cooling setpoints (Fahrenheit input, auto-converts to Celsius)
- **Mode** - Switch between off/cool/heat/dry/vent/auto
- **Fan Speed** - superQuiet, quiet, low, powerful, superPowerful, auto
- **Air Direction** - auto, horizontal, midhorizontal, midpoint, midvertical, vertical, swing
- **Power** - Turn devices on/off

### Monitoring
- Current room temperature vs setpoint
- Temperature difference (how far from target)
- Humidity levels
- Device online status
- WiFi signal strength (RSSI)
- MHK2 wall controller detection
- Real adapter reachability (`check`) - the cloud keeps serving a dead unit's last
  known state, so "connected" in the zone data doesn't mean the unit is there
- Per-unit setpoint limits, so an out-of-range temperature fails before it's sent

### Additional Data
- Zone schedules
- Connection history
- Weather data for site location
- Comfort setting presets

## Installation

### Requirements
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
# Clone and enter directory
cd mitsubishi-comfort-api-kumo

# Install with uv (recommended)
uv sync

# Or with pip
pip install httpx[http2] python-dotenv

# Optional: Install Socket.IO for real-time data refresh
pip install python-socketio[client]
```

## Configuration

### Quick Start

1. Copy the sample environment file:
```bash
cp .env.sample .env
```

2. Edit `.env` with your Kumo Cloud credentials:
```bash
KUMO_USERNAME=your@email.com
KUMO_PASSWORD=yourpassword
```

3. Get your site ID and device serials:
```bash
uv run python app.py raw sites    # Copy the site ID
uv run python app.py raw zones    # Copy device serials
```

4. Add them to `.env`:
```bash
KUMO_SITE_ID=your-site-guid-here

# Name your devices - the part after KUMO_SERIAL_ becomes the friendly name
KUMO_SERIAL_BEDROOM=device-serial-here
KUMO_SERIAL_OFFICE=device-serial-here
KUMO_SERIAL_LIVINGROOM=device-serial-here
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KUMO_USERNAME` | Yes | Kumo Cloud email |
| `KUMO_PASSWORD` | Yes | Kumo Cloud password |
| `KUMO_SITE_ID` | No | Default site ID (avoids extra API call) |
| `KUMO_SERIAL_<NAME>` | No | Map friendly names to device serials |

The `KUMO_SERIAL_<NAME>` pattern lets you use friendly names instead of serial numbers:
- `KUMO_SERIAL_BEDROOM=ABC123` → use "bedroom" in commands
- `KUMO_SERIAL_OFFICE=DEF456` → use "office" in commands

Names are case-insensitive.

## CLI Usage

### Authentication

```bash
# Login and cache tokens (valid ~1 month)
uv run python app.py login
```

Tokens are cached to `~/.kumo_tokens.json` and auto-refresh when expired.

### View Status

```bash
# Basic status
uv run python app.py status

# Verbose - includes fan, vane, RSSI, MHK2 info
uv run python app.py status -v

# Fresh data from devices (bypasses server cache - requires python-socketio)
uv run python app.py status -r

# Verbose + fresh data (most accurate)
uv run python app.py status -v -r

# JSON output
uv run python app.py status --json
```

> **Important: Stale vs Fresh Data**
>
> The Kumo Cloud REST API returns **cached server-side data** that may be minutes or hours old.
> When you adjust the MHK2 thermostat, the API may still show the old setpoint until the
> server cache updates. Use `-r/--refresh` to get **real-time data directly from devices**.

**Example - Without Refresh (may show stale data):**
```
% python app.py status

======================================================================
KUMO CLOUD DEVICE STATUS
======================================================================

Site: My Home
--------------------------------------------------
  Living Room  [ON] Room: 66.2F | Set: 70.7F (heat another: 4.5F) | Mode: heat | Humidity: 35%
  Bedroom      [ON] Room: 70.7F | Set: 68.0F (too hot by: 2.7F) | Mode: heat | Humidity: 34%
======================================================================
```
⚠️ **Problem:** Living Room shows `Set: 70.7F` but the thermostat was already changed to 68°F!

**Example - With Refresh (accurate real-time data):**
```
% python app.py status -r

======================================================================
KUMO CLOUD DEVICE STATUS (REFRESHED)
======================================================================

Site: My Home
--------------------------------------------------
  Living Room  [ON] Room: 68.0F | Set: 68.0F (at target) | Mode: heat | Fan: auto | Vane: auto | Humidity: 35%
  Bedroom      [ON] Room: 70.7F | Set: 68.0F (too hot by: 2.7F) | Mode: heat | Fan: auto | Vane: vertical | Humidity: 34%
======================================================================
```
✅ **Fixed:** Living Room now correctly shows `Set: 68.0F` - the actual thermostat value!

**Key Differences:**
| Aspect | Without `-r` | With `-r` |
|--------|--------------|-----------|
| Data source | Server cache | Direct from device |
| Accuracy | May be stale | Real-time |
| Fan/Vane info | Not included | Included |
| Speed | Faster | Slightly slower (~5s) |
| Requires | Nothing extra | `python-socketio[client]` |

**Example Output (Verbose):**
```
======================================================================
KUMO CLOUD DEVICE STATUS
======================================================================

Site: My Home
--------------------------------------------------
  Bedroom      [ON] Room: 68.0F | Set: 68.0F (at target) | Mode: heat | Fan: quiet | Vane: swing | Humidity: 37%
    [RSSI: -46dBm, MHK2: Yes, Schedule: adapter, Setpoints: Cool=72F Heat=68F]
  Office       [ON] Room: 70.7F | Set: 70.0F (too hot by: 0.7F) | Mode: heat | Fan: auto | Vane: auto | Humidity: 38%
    [RSSI: -22dBm, MHK2: Yes, Schedule: adapter, Setpoints: Cool=76F Heat=70F]

======================================================================
```

### Control Commands

```bash
# Set temperature (Fahrenheit)
uv run python app.py set-temp bedroom 72
uv run python app.py set-temp bedroom 68 -m heat    # with mode
uv run python app.py set-temp bedroom 72 -m cool    # cooling mode

# Change mode (off, cool, heat, dry, fan, auto)
uv run python app.py set-mode bedroom heat
uv run python app.py set-mode office cool
uv run python app.py set-mode bedroom off

# Set fan speed (superQuiet, quiet, low, powerful, superPowerful, auto)
uv run python app.py set-fan bedroom quiet
uv run python app.py set-fan office powerful

# Set air direction (auto, horizontal, midhorizontal, midpoint, midvertical, vertical, swing)
uv run python app.py set-vane bedroom swing
uv run python app.py set-vane office horizontal

# Power on/off
uv run python app.py turn-on bedroom
uv run python app.py turn-off office
```

### Reachability

```bash
uv run python app.py check                # All configured devices
uv run python app.py check -d bedroom     # One device
uv run python app.py check --json
```

An adapter that has dropped off the network still looks healthy in the zone data
(`connected: true`, a moving `updatedAt`), and commands sent to it return HTTP 200
and reach nothing. `check` asks the cloud directly over Socket.IO
(`device_status_v2`), which is the only signal that reports the truth:

```
  downstairs   CONNECTED
  upstairs     DISCONNECTED since 2026-09-17T03:02:01.025Z (reason: IoT Disconnected)
```

### Setpoint Limits

```bash
uv run python app.py raw device-limits bedroom
```

Each unit has its own allowed range, set on the equipment (function code 181, via
an MHK2 or an installer) and enforced by the API. `set-temp` checks it first, so
an out-of-range value fails with a readable message instead of an API 400:

```
API error: 45F is below this unit's heat minimum of 50F (10C).
The limit lives on the unit (function code 181), not in the API.
```

Pass `check_limits=False` to `set_temperature()` to skip the check (one fewer API call).

### Raw API Access

For debugging or accessing data not exposed through high-level commands:

```bash
uv run python app.py raw account         # Account info
uv run python app.py raw config          # Service-wide configuration
uv run python app.py raw sites           # List all sites
uv run python app.py raw zones           # Zones for configured site
uv run python app.py raw groups          # Device groups
uv run python app.py raw device SERIAL   # Full device info
uv run python app.py raw device-status SERIAL
uv run python app.py raw device-profile SERIAL
uv run python app.py raw device-limits SERIAL   # Allowed setpoint range, in F
uv run python app.py raw device-props SERIAL
uv run python app.py raw weather         # Weather for site location
```

## Python API

### Initialization

```python
from app import KumoCloudClient

# Option 1: Use environment variables (recommended)
# Reads from KUMO_USERNAME, KUMO_PASSWORD, KUMO_SITE_ID, KUMO_SERIAL_* in .env
with KumoCloudClient() as client:
    client.print_status()

# Option 2: Pass credentials directly
with KumoCloudClient(
    username="your@email.com",
    password="yourpassword",
    site_id="your-site-guid",
    device_serials={"bedroom": "ABC123", "office": "DEF456"}
) as client:
    client.print_status()
```

### Basic Usage

```python
from app import KumoCloudClient

with KumoCloudClient() as client:
    # Get all devices (basic info - fast, single API call)
    devices = client.get_all_devices()

    # Get all devices with full info (includes fan/vane, extra API calls per device)
    devices = client.get_all_devices(full=True)

    # Get all devices with fresh data from devices (requires python-socketio)
    # This bypasses server cache and gets actual current values
    devices = client.get_all_devices(refresh=True)

    for d in devices:
        print(f"{d.name}: {d.room_temp}F (set: {d.set_temp}F)")
        print(f"  Mode: {d.mode}, Fan: {d.fan_speed}, Vane: {d.air_direction}")
        print(f"  Humidity: {d.humidity}%, RSSI: {d.rssi}dBm, Connected: {d.connected}")

    # Get device by friendly name (from KUMO_SERIAL_* env vars)
    bedroom = client.get_device_by_name("bedroom")
    if bedroom:
        print(f"Bedroom is {'ON' if bedroom.is_on else 'OFF'} at {bedroom.room_temp}F")

    # Get device with fresh data (bypasses server cache)
    bedroom = client.get_device_by_name("bedroom", refresh=True)

    # Get serial from friendly name
    serial = client.get_serial_by_name("bedroom")

    # Control commands (temperatures in Fahrenheit - auto-converted to Celsius)
    client.set_temperature(serial, 72, mode="cool")  # Set to 72F cooling
    client.set_temperature(serial, 68, mode="heat")  # Set to 68F heating
    client.set_temperature(serial, 70)               # Set both setpoints to 70F

    # Change mode (off, cool, heat, dry, fan, auto)
    client.set_mode(serial, "heat")
    client.set_mode(serial, "fan")   # Fan only (translated to "vent" for API)

    # Fan speed (superQuiet, quiet, low, powerful, superPowerful, auto)
    client.set_fan_speed(serial, "quiet")

    # Air direction (auto, horizontal, midhorizontal, midpoint, midvertical, vertical, swing)
    client.set_air_direction(serial, "swing")

    # Power on/off
    client.turn_on(serial)
    client.turn_off(serial)

    # Raw command (for advanced use)
    client.send_device_command(serial, {"spHeat": 20.0, "operationMode": "heat"})
```

### Zone and Site Data

```python
with KumoCloudClient() as client:
    # Get zones for a site
    zones = client.get_zones(client.site_id)
    for zone in zones:
        print(f"Zone: {zone['name']} (ID: {zone['id']})")

    # Zone schedules
    zone_id = zones[0]["id"]
    schedules = client.get_zone_schedules(zone_id)

    # Connection history (paginated)
    history = client.get_zone_connection_history(zone_id, page=1)
    for event in history.get("data", []):
        print(f"  {event['start']}: {'Connected' if event['isConnected'] else 'Disconnected'}")

    # Comfort settings
    comfort = client.get_zone_comfort_settings(zone_id)
    presets = client.get_comfort_presets(season="winter")

    # Weather for site location
    weather = client.get_weather()
    temp_c = weather["main"]["temp"]
    print(f"Outside: {temp_c}°C ({temp_c * 9/5 + 32:.1f}°F)")

    # All sites
    sites = client.get_sites()
```

### Available Methods

#### Authentication
| Method | Description |
|--------|-------------|
| `login(username, password)` | Authenticate and cache tokens |

#### Sites & Zones
| Method | Description |
|--------|-------------|
| `get_sites()` | List all sites/locations |
| `get_sites_full()` | Sites with additional details |
| `get_zones(site_id)` | List zones for a site |
| `get_groups(site_id)` | Device groups for a site |
| `get_weather(site_id)` | Weather data for site |

#### Devices
| Method | Description |
|--------|-------------|
| `get_all_devices(site_id, full, refresh)` | All devices with status |
| `get_device(serial)` | Full device info |
| `get_device_status(serial)` | Device configuration |
| `get_device_profile(serial)` | Device capabilities |
| `get_device_limits(serial)` | Allowed setpoint range per mode, in F |
| `get_device_by_name(name, refresh)` | Device by friendly name |
| `get_serial_by_name(name)` | Resolve name to serial |
| `force_device_refresh(serial)` | Force fresh data via Socket.IO |
| `get_fresh_device_status(serial)` | Get fresh data (Socket.IO + fallback) |
| `get_reachability(serials)` | Whether each adapter is really online |

#### Control
| Method | Description |
|--------|-------------|
| `set_temperature(serial, temp, mode, check_limits)` | Set temperature (F) |
| `set_mode(serial, mode)` | Set operating mode |
| `set_fan_speed(serial, speed)` | Set fan speed |
| `set_air_direction(serial, direction)` | Set vane direction |
| `turn_on(serial)` | Power on |
| `turn_off(serial)` | Power off |
| `send_device_command(serial, commands)` | Send raw commands |

#### Zone Data
| Method | Description |
|--------|-------------|
| `get_zone_schedules(zone_id)` | Schedules for zone |
| `get_zone_connection_history(zone_id, page)` | Connection history |
| `get_zone_comfort_settings(zone_id)` | Comfort settings |
| `get_comfort_presets(season)` | Comfort presets |

#### Account
| Method | Description |
|--------|-------------|
| `get_account()` | Account info |
| `get_config()` | Service-wide configuration |
| `update_preferences(prefs)` | Update preferences |
| `get_unseen_notification_count()` | Notification count |

### DeviceStatus Fields

| Field | Type | Description |
|-------|------|-------------|
| `serial` | str | Device serial number |
| `name` | str | Zone/device name |
| `room_temp` | float | Current temperature (F) |
| `set_temp` | float | Active setpoint (F) |
| `sp_cool` | float | Cooling setpoint (F) |
| `sp_heat` | float | Heating setpoint (F) |
| `mode` | str | Operating mode |
| `fan_speed` | str | Fan speed setting |
| `air_direction` | str | Vane direction |
| `is_on` | bool | Power state |
| `humidity` | int | Humidity % |
| `connected` | bool | Online status |
| `rssi` | int | WiFi signal (dBm) |
| `has_mhk2` | bool | Has MHK2 controller |
| `has_sensor` | bool | Has external sensor |
| `schedule_owner` | str | Schedule owner |

## API Reference

### Operating Modes

| CLI Value | API Value | Description |
|-----------|-----------|-------------|
| `off` | `off` | Unit off |
| `cool` | `cool` | Cooling |
| `heat` | `heat` | Heating |
| `dry` | `dry` | Dehumidify |
| `fan` | `vent` | Fan only |
| `auto` | `auto` | Auto switching |

### Fan Speeds

| Value | Description |
|-------|-------------|
| `superQuiet` | Super quiet |
| `quiet` | Quiet |
| `low` | Low |
| `powerful` | Powerful |
| `superPowerful` | Super powerful |
| `auto` | Automatic |

### Air Directions

| Value | Description |
|-------|-------------|
| `auto` | Automatic |
| `horizontal` | Horizontal |
| `midhorizontal` | Mid-horizontal |
| `midpoint` | Mid-point |
| `midvertical` | Mid-vertical |
| `vertical` | Vertical |
| `swing` | Swing mode |

## Troubleshooting

### Authentication Errors

```bash
# Clear cached tokens and re-login
rm ~/.kumo_tokens.json
uv run python app.py login
```

### Rate Limiting

The API allows 50 requests per minute. If you hit limits, wait and retry. Headers show remaining quota:
- `x-ratelimit-limit`: 50
- `x-ratelimit-remaining`: requests left
- `x-ratelimit-reset`: reset timestamp

### Stale/Incorrect Temperature Data

The Kumo Cloud API may return cached values from the server. If you change the temperature
on the MHK2 thermostat and the API still shows the old value, use the refresh option:

```bash
# CLI - use -r/--refresh flag
uv run python app.py status -r

# Python - use refresh=True parameter
devices = client.get_all_devices(refresh=True)
bedroom = client.get_device_by_name("bedroom", refresh=True)
```

This uses Socket.IO to send `force_adapter_request` events that force devices to report
their actual current state, bypassing the server cache.

**Requirements:** `pip install python-socketio[client]`

### Commands Return Success but Nothing Happens

The unit's Wi-Fi adapter is probably off the network. The cloud answers from a
frozen copy of its last known state, so status still looks plausible and every
command returns HTTP 200. Confirm with:

```bash
uv run python app.py check
```

A `DISCONNECTED` unit has to come back on the network before it will accept
anything; power-cycling the adapter is usually what does it.

### Missing Fan/Vane Data

Basic status doesn't include fan/vane. Use verbose mode:
```bash
uv run python app.py status -v
```

### Device Not Found

1. Verify device is online in the Kumo Cloud app
2. Check `KUMO_SITE_ID` is correct
3. Verify serial number with `uv run python app.py raw zones`

## API Documentation

- **[KUMO-API-V3-DOC.md](KUMO-API-V3-DOC.md)** — the v3 API: accounts, sites, zones, devices,
  device control, request/response formats, and Socket.IO real-time updates.
- **[KUMO-API-V4-DOC.md](KUMO-API-V4-DOC.md)** — everything the Comfort app (`3.5.0`) hits,
  including the v4 scheduling endpoints, the confirmed `send-command` control forms
  (single + site-wide), per-zone notification preferences, the full WebSocket protocol, and the
  MITM capture methodology used to produce this reference.

## License

MIT License - Use at your own risk. Not affiliated with Mitsubishi Electric.

## Acknowledgments

Thanks to [pykumo](https://github.com/dlarrick/pykumo) and the community around it for getting started with the basics for the v3 API.
