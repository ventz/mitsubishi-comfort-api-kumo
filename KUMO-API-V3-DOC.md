# Kumo Cloud API v3 Documentation

Comprehensive API documentation for the Mitsubishi Kumo Cloud API v3.

**Base URL:** `https://app-prod.kumocloud.com`

**App Version:** `3.2.4`

**App Build:** `1122`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Request Headers](#request-headers)
3. [Service Endpoints](#service-endpoints)
4. [Account Endpoints](#account-endpoints)
5. [Site Endpoints](#site-endpoints)
6. [Zone Endpoints](#zone-endpoints)
7. [Device Endpoints](#device-endpoints)
8. [Device Control](#device-control)
9. [Notifications](#notifications)
10. [Comfort Settings](#comfort-settings)
11. [Real-Time Updates (Socket.IO)](#real-time-updates-socketio)
12. [Data Reference](#data-reference)
13. [Rate Limiting](#rate-limiting)

---

## Authentication

### Login

**POST** `/v3/login`

Authenticate and obtain JWT tokens.

**Request:**
```json
{
  "username": "user@example.com",
  "password": "yourpassword",
  "appVersion": "3.2.4"
}
```

**Response:**
```json
{
  "token": {
    "access": "<jwt_access_token>",
    "refresh": "<jwt_refresh_token>"
  },
  "email": "user@example.com",
  "userId": "<user_id>",
  ...
}
```

**Token Lifetimes:**
- Access token: ~20 minutes
- Refresh token: ~30 days

### Refresh Token

**POST** `/v3/refresh`

Refresh an expired access token.

**Headers:**
```
Authorization: Bearer <refresh_token>
```

**Request:**
```json
{
  "refresh": "<refresh_token>"
}
```

**Response:**
```json
{
  "access": "<new_access_token>",
  "refresh": "<new_refresh_token>"
}
```

---

## Request Headers

### Required Headers (All Requests)

```
Accept: application/json
Accept-Encoding: gzip, deflate, br
Accept-Language: en-US,en;q=0.9
Content-Type: application/json
User-Agent: kumocloud/1122 CFNetwork/3860.200.71 Darwin/25.1.0
```

### Required Headers (Authenticated Requests)

```
Authorization: Bearer <access_token>
x-app-version: 3.2.4
app-env: prd
```

### Optional Headers

```
x-allow-cache: true
priority: u=3, i
```

### Sentry Tracing Headers (Optional)

The mobile app includes Sentry error tracking headers:
```
baggage: sentry-environment=prd,sentry-public_key=...,sentry-trace_id=...
sentry-trace: <trace_id>-<span_id>
access-control-allow-headers: sentry-trace
```

---

## Service Endpoints

### Get Service Config

**GET** `/v3/config`

Service-wide settings (no parameters). The unversioned `/config` is a 404.

```json
{
  "timeBeforeDisable": 30,
  "notificationRateLimit": 86400000,
  "batteryNotificationRateLimit": 172800000,
  "temperatureNotificationRateLimit": 1800000,
  "notificationArchivingEnabled": true,
  "notificationArchivingCheckIntervalHours": 6,
  "notificationArchivingBatchSize": 500
}
```

---

## Account Endpoints

### Get Account Info

**GET** `/v3/accounts/me`

Returns current user account information including preferences.

**Response:**
```json
{
  "id": "<user_id>",
  "username": "user@example.com",
  "email": "user@example.com",
  "firstName": "...",
  "lastName": "...",
  "phone": "",
  "isPersonalAccount": true,
  "isEmailVerified": true,
  "preferences": {
    "celsius": false,
    "scheduleFeatureModalSeen": true,
    "scheduleDuplicationModalSeen": true,
    "scheduleForMultipleZonesModalHidden": false,
    "feedback": {
      "type": "email",
      "provided": true
    },
    "appWalkthroughs": {
      "CreateSite": { "seen": true, "actionCompleted": true },
      "CreateZone": { "seen": true, "actionCompleted": true },
      "Dashboard": { "seen": true, "actionCompleted": true },
      "Locations": { "seen": false, "actionCompleted": false }
    },
    "hideDashboardWelcomeSteps": true,
    "isMinMaxSetpointsEnabled": false,
    "weatherVisibility": {}
  },
  "company": null,
  "isSalesforceIntegrated": true
}
```

### Update Account Preferences

**PUT** `/v3/accounts/preferences`

Update user preferences (temperature units, UI settings, etc.).

**Request:**
```json
{
  "celsius": false,
  "scheduleFeatureModalSeen": true,
  "scheduleDuplicationModalSeen": true,
  "scheduleForMultipleZonesModalHidden": false,
  "feedback": { "type": "email", "provided": true },
  "appWalkthroughs": { ... },
  "hideDashboardWelcomeSteps": true,
  "isMinMaxSetpointsEnabled": false,
  "weatherVisibility": {}
}
```

---

## Site Endpoints

Sites represent physical locations (homes, buildings).

### List Sites

**GET** `/v3/sites`

Returns all sites associated with the account.

**Response:**
```json
[
  {
    "id": "<site_uuid>",
    "name": "My Home",
    "address": { ... },
    "timezone": "America/New_York",
    ...
  }
]
```

### List Sites (Full)

**GET** `/v3/sites/full`

Returns sites with additional details.

### Get Site Details

**GET** `/v3/sites/{site_id}`

### Get Site Weather

**GET** `/v3/sites/{site_id}/weather`

Returns current weather data for the site's location (OpenWeatherMap data).

**Response:**
```json
{
  "coord": { "lon": -XX.XXXX, "lat": XX.XXXX },
  "weather": [
    {
      "id": 800,
      "main": "Clear",
      "description": "clear sky",
      "icon": "01n"
    }
  ],
  "base": "stations",
  "main": {
    "temp": -1.43,
    "feels_like": -1.43,
    "temp_min": -3.3,
    "temp_max": -0.05,
    "pressure": 1017,
    "humidity": 81,
    "sea_level": 1017,
    "grnd_level": 1012
  },
  "visibility": 10000,
  "wind": { "speed": 0, "deg": 0 },
  "clouds": { "all": 0 },
  "dt": 1700000000,
  "sys": {
    "type": 2,
    "id": 1234567,
    "country": "US",
    "sunrise": 1700000000,
    "sunset": 1700000000
  },
  "timezone": -18000,
  "id": 1234567,
  "name": "City Name",
  "cod": 200
}
```

### Get Kumo Station

**GET** `/v3/sites/{site_id}/kumo-station?refresh=false`

Returns Kumo Station info if the site has one.

**Response (if not found):**
```json
{
  "error": "kumoStationNotFound"
}
```

### Get Site Groups

**GET** `/v3/sites/{site_id}/groups`

Returns device groups for a site.

### Get Pending Transfers

**GET** `/v3/sites/transfers/pending`

Returns pending site transfers.

### Get Preferable Contractor

**GET** `/v3/site/{site_id}/preferable-contractor`

Returns contractor information for the site.

---

## Zone Endpoints

Zones are logical groupings of devices (rooms, areas).

### List Zones

**GET** `/v3/sites/{site_id}/zones`

Returns all zones for a site with full device status.

**Response:**
```json
[
  {
    "id": "<zone_uuid>",
    "name": "Living Room",
    "isActive": true,
    "adapter": {
      "id": "<adapter_uuid>",
      "deviceSerial": "<device_serial>",
      "isSimulator": false,
      "roomTemp": 19,
      "spCool": 24.5,
      "spHeat": 18.5,
      "spAuto": null,
      "humidity": 37,
      "scheduleOwner": "adapter",
      "scheduleHoldEndTime": 0,
      "power": 1,
      "operationMode": "heat",
      "previousOperationMode": "heat",
      "connected": true,
      "hasSensor": false,
      "hasMhk2": true,
      "timeZone": "America/New_York",
      "isHeadless": false,
      "lastStatusChangeAt": "<iso_timestamp>",
      "createdAt": "<iso_timestamp>",
      "updatedAt": "<iso_timestamp>"
    },
    "createdAt": "<iso_timestamp>",
    "updatedAt": "<iso_timestamp>"
  }
]
```

### Get Zone Details

**GET** `/v3/zones/{zone_id}`

Returns details for a specific zone.

### Get Zone Schedules

**GET** `/v3/zones/{zone_id}/schedules`

Returns schedules configured for a zone.

### Get Zone Comfort Settings

**GET** `/v3/zones/{zone_id}/comfort-settings?zoneId={zone_id}`

Returns comfort settings for a zone.

### Get Zone Notification Preferences

**GET** `/v3/zones/{zone_id}/notification-preferences`

Returns notification preferences for a zone.

### Get Zone Connection History

**GET** `/v3/zones/{zone_id}/connection-history?page=1`

Returns paginated connection history for a zone.

**Response:**
```json
{
  "next": null,
  "previous": null,
  "count": 10,
  "data": [
    {
      "start": "<iso_timestamp>",
      "end": null,
      "isConnected": true,
      "uptime": "9h"
    },
    {
      "start": "<iso_timestamp>",
      "end": "<iso_timestamp>",
      "isConnected": false,
      "uptime": "5h"
    }
  ]
}
```

---

## Device Endpoints

### Get Device Info

**GET** `/v3/devices/{device_serial}`

Returns comprehensive device information.

**Response:**
```json
{
  "id": "<device_uuid>",
  "deviceSerial": "<device_serial>",
  "rssi": -43,
  "power": 1,
  "operationMode": "heat",
  "humidity": 37,
  "scheduleOwner": "adapter",
  "scheduleHoldEndTime": 0,
  "fanSpeed": "auto",
  "airDirection": "auto",
  "roomTemp": 20,
  "unusualFigures": 32768,
  "twoFiguresCode": "A0",
  "statusDisplay": 1,
  "spCool": 24.5,
  "spHeat": 18.5,
  "spAuto": null,
  "runTest": 0,
  "activeThermistor": null,
  "tempSource": null,
  "isSimulator": false,
  "serialNumber": "<unit_serial>",
  "modelNumber": "<model_number>",
  "ledDisabled": false,
  "connected": true,
  "isHeadless": false,
  "previousOperationMode": "heat",
  "lastStatusChangeAt": "<iso_timestamp>",
  "createdAt": "<iso_timestamp>",
  "updatedAt": "<iso_timestamp>",
  "model": {
    "id": "<model_uuid>",
    "brand": "Mitsubishi",
    "material": "<model_number>",
    "basicMaterial": "<base_model>",
    "replacementMaterial": "",
    "materialDescription": "...",
    "family": "MSZ",
    "subFamily": "MSZ-GL/GS",
    "materialGroupName": "RAC indoor",
    "serialProfile": "ZEA",
    "materialGroupSeries": "M-Series",
    "isIndoorUnit": true,
    "isDuctless": true,
    "isSwing": null,
    "isPowerfulMode": null,
    "modeDescription": "INDOOR UNIT",
    "isActive": true,
    "frontendAnimation": "fs",
    "gallery": {
      "id": "<gallery_uuid>",
      "name": "Wall mounted",
      "imageUrl": "https://...",
      "imageAlt": "Wall mounted"
    }
  },
  "displayConfig": {
    "filter": false,
    "defrost": false,
    "hotAdjust": false,
    "standby": false
  },
  "timeZone": "America/New_York",
  "collectMethod": "qr_code",
  "realValues": {}
}
```

### Get Device Status

**GET** `/v3/devices/{device_serial}/status`

Returns adapter (Wi-Fi module) hardware info, not live zone state. Field set
varies by unit: units without an MHK2 return the short form below.

**Response (observed 2026-09-20):**
```json
{
  "firmwareVersion": "02.06.26",
  "roomTempDisplayOffset": 0,
  "routerSsid": "<wifi_network>",
  "routerRssi": -53,
  "minSetPoint": 19.5,
  "maxSetPoint": 28,
  "lastUpdated": "2026-09-19T02:30:27.166Z",
  "mac": "xx:xx:xx:xx:xx:xx"
}
```

**`lastUpdated` is not a liveness signal.** It tracks when this adapter record
was last refreshed, which happens on the order of once a day: both of our
adapters reported a `lastUpdated` ~32 hours old while both units were online and
responding. Use the Socket.IO `device_status_v2` event for reachability.

`minSetPoint` / `maxSetPoint` here are a single pair and can disagree with the
per-mode ranges in `/profile` (one unit reported `minSetPoint: 19.5` against a
profile `minimumSetPoints.cool` of 19). Treat `/profile` as authoritative for
what a command will be allowed to set.

**Response (longer form, unit with an MHK2 receiver):**
```json
{
  "autoModeDisable": true,
  "firmwareVersion": "XX.XX.XX",
  "roomTempDisplayOffset": 0,
  "routerSsid": "<wifi_network>",
  "routerRssi": -42,
  "optimalStart": null,
  "modeHeat": true,
  "modeDry": true,
  "receiverRelay": "MHK2",
  "lastUpdated": "<iso_timestamp>",
  "cryptoSerial": "<crypto_serial>",
  "cryptoKeySet": "<key_set>"
}
```

### Get Device Profile

**GET** `/v3/devices/{device_serial}/profile`

Returns device capabilities and the setpoint range the unit will accept.

**Response shape varies:** some accounts get a bare object, ours returns a
single-element array. Unwrap before reading.

```json
[{
  "hasModeDry": true,
  "hasModeHeat": true,
  "hasModeVent": true,
  "hasVaneDir": false,
  "hasVaneSwing": false,
  "hasFanSpeedAuto": true,
  "numberOfFanSpeeds": 3,
  "hasInitialSettings": true,
  "hasModeTest": true,
  "extendedTemps": true,
  "usesSetPointInDryMode": true,
  "hasHotAdjust": true,
  "hasDefrost": true,
  "hasStandby": true,
  "minimumSetPoints": { "cool": 19, "heat": 10, "auto": 19 },
  "maximumSetPoints": { "cool": 30, "heat": 28, "auto": 28 }
}]
```

**The range is per-unit and set on the equipment, not in the cloud.** It comes
from function code 181 (reachable from an MHK2 wall controller or by an
installer), so two units on one site differ: ours report `heat` minimums of 10°C
and 9°C, and `cool` minimums of 19°C and 15°C. The API only enforces it —
a setpoint outside the range is rejected with HTTP 400 and
`{"commands": ["invalidSpHeatRange"]}` (likewise `invalidSpCoolRange`). PUT,
PATCH and POST to this path all 404: the limits cannot be changed over the API.

`GET /v3/devices/{device_serial}/sensor` exists but returns
`{"error": "sensorNotFound"}` unless a remote sensor is paired.

### Get Device Initial Settings

**GET** `/v3/devices/{device_serial}/initial-settings`

Returns device initial/default settings.

### Get Device Kumo Properties

**GET** `/v3/devices/{device_serial}/kumo-properties`

Returns Kumo-specific device properties.

---

## Device Control

### Send Command (Primary Control Endpoint)

**POST** `/v3/devices/send-command`

This is the primary endpoint for controlling devices. All setpoint and mode changes go through this endpoint.

**Request:**
```json
{
  "deviceSerial": "<device_serial>",
  "commands": {
    "operationMode": "heat",
    "spCool": 24.5,
    "spHeat": 18.5
  }
}
```

**Response:**
```json
{
  "devices": ["<device_serial>"]
}
```

### Available Commands

| Command | Type | Description | Values |
|---------|------|-------------|--------|
| `operationMode` | string | Operating mode | `off`, `cool`, `heat`, `dry`, `vent`, `auto` |
| `spCool` | float | Cooling setpoint | Temperature in Celsius |
| `spHeat` | float | Heating setpoint | Temperature in Celsius |
| `spAuto` | float | Auto mode setpoint | Temperature in Celsius |
| `power` | int | Power state | `0` (off), `1` (on) |
| `fanSpeed` | string | Fan speed | See [Fan Speeds](#fan-speeds) |
| `airDirection` | string | Air direction/vane | See [Air Directions](#air-directions) |

### Command Examples

**Change mode (with setpoints):**
```json
{
  "deviceSerial": "<device_serial>",
  "commands": {
    "operationMode": "cool",
    "spCool": 24.5,
    "spHeat": 18.5
  }
}
```

**Change fan speed only:**
```json
{
  "deviceSerial": "<device_serial>",
  "commands": {
    "fanSpeed": "powerful"
  }
}
```

**Change air direction only:**
```json
{
  "deviceSerial": "<device_serial>",
  "commands": {
    "airDirection": "swing"
  }
}
```

---

## Notifications

### Get Unseen Count

**GET** `/v3/notifications/unseen-count`

Returns count of unseen notifications.

**Response:**
```json
{
  "count": 0
}
```

---

## Comfort Settings

### Get Comfort Setting Presets

**GET** `/v3/comfort-settings/presets?season={season}`

Returns comfort setting presets for a season.

**Parameters:**
- `season`: `winter` or `summer`

---

## Real-Time Updates (Socket.IO)

The Kumo Cloud app uses Socket.IO for real-time device status updates.

### Connection Details

**URL:** `https://socket-prod.kumocloud.com`

**Protocol:** Engine.IO v4

### Handshake Flow

1. **Initial polling request:**
   ```
   GET /socket.io/?EIO=4&transport=polling&t={timestamp}
   Authorization: Bearer <access_token>
   ```

   **Response:**
   ```json
   {"sid":"<session_id>","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":20000,"maxPayload":1000000}
   ```

2. **Connect to namespace:**
   ```
   POST /socket.io/?EIO=4&transport=polling&t={timestamp}&sid={sid}
   Body: 40
   ```

3. **Upgrade to WebSocket** (optional):
   ```
   wss://socket-prod.kumocloud.com/socket.io/?EIO=4&transport=websocket&sid={sid}
   ```

### Subscribe to Device Status

This is the only trustworthy reachability signal. When an adapter drops off the
network the cloud keeps serving its last known zone state — `adapter.connected`
stays `true` and `adapter.updatedAt` keeps moving, because unrelated refreshes
touch the row — and commands sent to the dead unit return HTTP 200 and reach
nothing.

Emit it **per serial**. The account-level form `42["device_status_v2",""]` only
acks with `{"deviceSerial": "", "date": ...}`; it does not enumerate devices.

**Request:**
```
42["device_status_v2","<device_serial>"]
```

**Response:**
```json
["device_status_v2",{
  "deviceSerial": "<device_serial>",
  "status": "connected",
  "lastTimeConnected": "<iso_timestamp>",
  "serverId": "<server_id>",
  "lastDisconnectedReason": "WEBSOCKET_CLOSED",
  "lastTimeDisconnected": "<iso_timestamp>",
  "hasIduCommunicationError": "false",
  "date": "<iso_timestamp>"
}]
```

### Subscribe to Device Updates

**Request:**
```
42["subscribe","<device_serial>"]
```

**Response:**
```
42["subscribed","Successfully subscribed to: <device_serial>"]
```

After subscribing, you'll receive `device_update` events when the device status changes.

### Force Device Refresh (Important!)

The REST API may return **cached/stale data** from the server. To get accurate real-time
values directly from the device, use the `force_adapter_request` event.

**Important:** The mobile app uses this mechanism to ensure the UI shows current values.
Without it, temperature changes made on the MHK2 thermostat may not reflect in API responses.

**Request Types:**
- `iuStatus` - Indoor unit status (temperatures, setpoints, mode)
- `profile` - Device capabilities
- `adapterStatus` - Adapter/WiFi module status
- `mhk2` - MHK2 thermostat status (if applicable)

**Send Request:**
```
42["force_adapter_request","<device_serial>","iuStatus"]
42["force_adapter_request","<device_serial>","profile"]
42["force_adapter_request","<device_serial>","adapterStatus"]
42["force_adapter_request","<device_serial>","mhk2"]
```

**Response (via `device_update` event):**
```json
["device_update",{
  "deviceSerial": "<device_serial>",
  "rssi": -45,
  "roomTemp": 19,
  "operationMode": "heat",
  "power": 1,
  "spCool": 22,
  "spHeat": 21.5,
  "spAuto": null,
  "airDirection": "auto",
  "fanSpeed": "auto",
  "humidity": 35,
  "connected": true,
  "scheduleOwner": "adapter",
  "scheduleHoldEndTime": 0,
  "displayConfig": {
    "filter": false,
    "defrost": false,
    "hotAdjust": true,
    "standby": false
  },
  "date": "<iso_timestamp>"
}]
```

### Socket.IO Event Types

| Event | Direction | Description |
|-------|-----------|-------------|
| `subscribe` | Client → Server | Subscribe to updates for a device |
| `device_update` | Server → Client | Device status/settings changed |
| `device_status_v2` | Both | Connection status query/response |
| `force_adapter_request` | Client → Server | Force device to report current state |
| `profile_update` | Server → Client | Device capabilities update |
| `adapter_update` | Server → Client | Adapter/WiFi module update |

### Python Socket.IO Example

```python
import socketio

sio = socketio.Client()

@sio.on("device_update")
def on_device_update(data):
    print(f"Device {data['deviceSerial']}: {data['roomTemp']}°C, spHeat={data['spHeat']}")

# Connect with auth
sio.connect(
    "https://socket-prod.kumocloud.com",
    auth={"token": access_token},
    headers={"Authorization": f"Bearer {access_token}"},
)

# Subscribe and force refresh
device_serial = "YOUR_DEVICE_SERIAL"
sio.emit("subscribe", device_serial)
sio.emit("force_adapter_request", (device_serial, "iuStatus"))

# Wait for response, then disconnect
import time
time.sleep(3)
sio.disconnect()
```

---

## Data Reference

### Temperature Units

All API temperatures are in **Celsius**. Convert for display:

```python
def celsius_to_fahrenheit(c):
    return round((c * 9 / 5) + 32, 1)

def fahrenheit_to_celsius(f):
    return round((f - 32) * 5 / 9, 1)
```

### Operating Modes

| Mode | API Value | Description |
|------|-----------|-------------|
| Off | `off` | Unit powered off |
| Cool | `cool` | Cooling mode |
| Heat | `heat` | Heating mode |
| Dry | `dry` | Dehumidification mode |
| Fan | `vent` | Fan only, no heating/cooling |
| Auto | `auto` | Automatic mode switching |

### Fan Speeds

| Speed | API Value |
|-------|-----------|
| Super Quiet | `superQuiet` |
| Quiet | `quiet` |
| Low | `low` |
| Powerful | `powerful` |
| Super Powerful | `superPowerful` |
| Auto | `auto` |

### Air Directions

| Direction | API Value |
|-----------|-----------|
| Auto | `auto` |
| Horizontal | `horizontal` |
| Mid-Horizontal | `midhorizontal` |
| Mid-Point | `midpoint` |
| Mid-Vertical | `midvertical` |
| Vertical | `vertical` |
| Swing | `swing` |

### Device Status Fields

| Field | Type | Description |
|-------|------|-------------|
| `roomTemp` | float | Current room temperature (°C) |
| `spCool` | float | Cooling setpoint (°C) |
| `spHeat` | float | Heating setpoint (°C) |
| `spAuto` | float | Auto mode setpoint (°C) |
| `humidity` | int | Current humidity (%) |
| `operationMode` | string | Current operating mode |
| `previousOperationMode` | string | Previous operating mode |
| `fanSpeed` | string | Current fan speed |
| `airDirection` | string | Current air direction |
| `power` | int | Power state (0=off, 1=on) |
| `connected` | bool | Device online status |
| `rssi` | int | WiFi signal strength (dBm) |
| `hasSensor` | bool | Has external sensor |
| `hasMhk2` | bool | Has MHK2 wall controller |
| `isHeadless` | bool | Headless mode |
| `isSimulator` | bool | Simulator device |
| `scheduleOwner` | string | Schedule owner (adapter/cloud) |
| `scheduleHoldEndTime` | int | Schedule hold end timestamp |
| `lastStatusChangeAt` | string | ISO timestamp of last change |

### Model Information

| Field | Description |
|-------|-------------|
| `modelNumber` | Model number |
| `serialNumber` | Unit serial number |
| `family` | Product family (MSZ, SVZ, etc.) |
| `isDuctless` | Wall-mounted vs ducted |
| `frontendAnimation` | UI animation type ("fs", "ducted") |

---

## Rate Limiting

The API enforces rate limiting:

| Header | Description |
|--------|-------------|
| `x-ratelimit-limit` | Maximum requests allowed (50) |
| `x-ratelimit-remaining` | Remaining requests |
| `x-ratelimit-reset` | Unix timestamp when limit resets |

Typical limit: **50 requests per minute**

---

## Error Handling

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 304 | Not Modified (cached response valid) |
| 400 | Bad request - invalid parameters |
| 401 | Unauthorized - token expired or invalid |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Server error |

### Error Response Format

```json
{
  "error": "kumoStationNotFound"
}
```

Command validation failures nest the error per device and per command:

```json
{
  "error": { "<device_serial>": { "commands": ["invalidSpHeatRange"] } },
  "description": "Failed to validate commands"
}
```

Known command error codes: `invalidSpHeatRange`, `invalidSpCoolRange` (setpoint
outside the unit's `/profile` range).

### Token Refresh Flow

1. Make request with access token
2. If 401 response, refresh token using `/v3/refresh`
3. Retry original request with new access token
4. If refresh fails, re-authenticate with `/v3/login`

---

## Notes

- **Caching:** The API supports ETag/If-None-Match for caching
- **Local API:** Devices also support a local HTTP API (not documented here).
  Its per-adapter password reaches v3 clients only over the Socket.IO
  `adapter_update` push; the legacy v2 cloud API
  (`POST https://geo-c.kumocloud.com/login`, `appVersion` `2.2.0`) still returns
  every adapter's local password and `cryptoSerial` in its login response, which
  is what pykumo and the Home Assistant integrations use.
- **Protocol:** API supports HTTP/2 for improved performance

---

## Acknowledgments

Thanks to [pykumo](https://github.com/dlarrick/pykumo) and the community around it for getting started with the basics for the v3 API.
