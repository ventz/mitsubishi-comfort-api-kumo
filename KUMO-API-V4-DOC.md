# Kumo Cloud / Comfort App API — v3 + v4 Documentation

API documentation for the Mitsubishi **Comfort** app (the rebranded successor to the
kumo cloud app). Captured by MITM of the iOS app against the production backend.

**App identity (from request headers):**

- App version: `3.5.0` (build `2383`) — header `x-app-version: 3.5.0`, UA `kumocloud/2383`
- Bundle still identifies as `kumocloud` (backend unchanged from the v3 app)
- This doc supplements [`KUMO-API-V3-DOC.md`](KUMO-API-V3-DOC.md); it documents everything
  the Comfort app hits, and calls out what is **new vs the v3 doc**.

**Base URLs / hosts:**

| Host | Purpose |
|------|---------|
| `https://app-prod.kumocloud.com` | Core REST API (v3 + v4) |
| `wss://socket-prod.kumocloud.com` | Socket.IO real-time device state |
| `https://status-api.kumocloud.com` | Service status (returns `{}` when healthy) |
| `https://api.revopush.org` | CodePush (React Native OTA bundle updates) — not app API |

---

## Table of Contents

1. [What's New vs v3 Doc](#whats-new-vs-v3-doc)
2. [Authentication](#authentication)
3. [Request Headers](#request-headers)
4. [Account Endpoints](#account-endpoints)
5. [Site Endpoints](#site-endpoints)
6. [Zone Endpoints](#zone-endpoints)
7. [Device Endpoints](#device-endpoints)
8. [Device Control](#device-control)
9. [Schedules (v4)](#schedules-v4)
10. [Notifications](#notifications)
11. [Real-Time Updates (Socket.IO)](#real-time-updates-socketio)
12. [Data Reference](#data-reference)
13. [Non-API Hosts (Telemetry)](#non-api-hosts-telemetry)
14. [Capture Methodology](#capture-methodology)

---

## What's New vs v3 Doc

New or confirmed by this capture (not in `KUMO-API-V3-DOC.md`):

- **`POST /v3/devices/send-command`** — the control endpoint, confirmed, with **two forms**
  (single-device and site-wide "control all zones") and the full field vocabulary.
- **Schedules moved to v4** — `GET/POST /v4/...` season & schedule endpoints, plus
  `DELETE /v4/schedules/{scheduleId}/events`.
- **Per-zone notification preferences** — `GET/PATCH /v3/zones/{zoneId}/notification-preferences`.
- **Site notification toggle** — `PATCH /v3/sites/{siteId}/toggle-notifications`.
- **Account preferences** — `PUT /v3/accounts/preferences` (units °C/°F, away settings, UI state).
- **Device sub-resources** — `/mhk2`, `/initial-settings`.
- **WebSocket protocol** documented (event names + payloads).

---

## Authentication

JWT bearer tokens. The app stores an **access** token (short-lived, ~20 min) and a
**refresh** token (long-lived). Requests send `Authorization: Bearer <access>`.

### Login (from v3 doc — not re-triggered this session)

**POST** `/v3/login` — see [`KUMO-API-V3-DOC.md`](KUMO-API-V3-DOC.md). Returns
`{ "token": { "access": "...", "refresh": "..." }, ... }`.

> This capture never hit `/v3/login`: the app had a valid refresh token and used
> `/v3/refresh` instead. A cold login is only sent on first sign-in or after refresh expiry.

### Refresh access token

**POST** `/v3/refresh`

```json
// Request
{ "refresh": "<refresh_jwt>" }

// Response 200
{ "access": "<new_access_jwt>", "refresh": "<new_refresh_jwt>" }
```

The JWT payload decodes to `{ id, username (email), iat, exp }`. `id` is the numeric
account id, reused as the Socket.IO subscription key.

---

## Request Headers

Headers sent on authenticated REST calls:

```
authorization:  Bearer <access_jwt>
accept:         application/json
app-env:        prd
x-app-version:  3.5.0
x-allow-cache:  true
user-agent:     kumocloud/2383 CFNetwork/3896.100.1.2.1 Darwin/27.0.0
accept-language: en-US,en;q=0.9
accept-encoding: gzip, deflate, br
if-none-match:  W/"..."          # conditional GETs; server replies 304 when unchanged
sentry-trace:   <trace-id>       # Sentry tracing (safe to omit)
baggage:        sentry-...        # Sentry tracing (safe to omit)
```

**Caching:** the app relies heavily on ETag / `If-None-Match`; unchanged reads return
`304 Not Modified`. A third-party client can ignore this and always send fresh GETs.

---

## Account Endpoints

### Get current account

**GET** `/v3/accounts/me` → `200`

```jsonc
{
  "id": "2251799814604767",
  "username": "<email>",
  "email": "<email>",
  "firstName": "...", "lastName": "...", "phone": "",
  "isPersonalAccount": true,
  "isEmailVerified": true,
  "preferences": { /* see PUT /v3/accounts/preferences */ }
}
```

### Update account preferences

**PUT** `/v3/accounts/preferences` → `200` (returns the full merged preferences object)

Send only the fields you change (partial updates work). This is where the **°C/°F display
toggle** lives (`celsius`).

```jsonc
{
  "celsius": false,                    // false = display °F, true = °C
  "surveyOptOut": false,
  "scheduleFeatureModalSeen": true,
  "scheduleDuplicationModalSeen": true,
  "scheduleForMultipleZonesModalHidden": false,
  "hideDashboardWelcomeSteps": true,
  "isMinMaxSetpointsEnabled": false,
  "shouldHideOatSensor": false,
  "weatherVisibility": { "<siteId>": true },
  "zoneAndGroupTilesOrder": { "<zoneId>": 0, "<zoneId>": 1 },
  "appWalkthroughs": { "Dashboard": { "seen": true, "actionCompleted": true }, "...": {} },
  "configuredAwaySettings": {          // per-zone "Away" hold presets
    "<zoneId>": {
      "id": "<uuid>", "enabled": true, "type": "away", "holdType": "unset",
      "endTime": "2126-04-17T18:25:38.000Z",
      "spCool": 26, "spHeat": 15.5,
      "operationMode": "auto", "fanSpeed": "auto", "airDirection": "auto"
    }
  },
  "feedback": { "provided": true, "type": "email", "taskSurvey": { "controlAll": true } }
}
```

> **Note:** setpoints in `configuredAwaySettings` are always **°C**, regardless of the
> `celsius` display flag. This holds everywhere in the API — the wire is always Celsius.

### Register push token

**POST** `/v3/accounts/fcm` → `200 {"success":true}`

```json
{ "deviceToken": "<FCM_or_APNs_token>" }
```

### App config

**GET** `/v3/config/new-version-overlay` — app-update "new version" overlay check (returns
`304` when unchanged). UI-only; not needed by a third-party client.

---

## Site Endpoints

A **site** is a physical location (home). IDs are UUIDs.

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v3/sites` | Minimal list: `id, name, isActive, role, mak, schedulesEnabled, notificationsEnabled` |
| GET | `/v3/sites/full` | Same + address, city/state/zip, `requiresAddressUpdate` |
| GET | `/v3/sites/{siteId}` | Single site (same shape as `full` element) |
| GET | `/v3/sites/{siteId}/zones` | **Full zone + adapter + holdMode state** (primary dashboard read) |
| GET | `/v3/sites/{siteId}/weather` | OpenWeatherMap-style current conditions for site coords |
| GET | `/v3/sites/{siteId}/groups` | Zone groups (403/`notAuthorized` if none) |
| GET | `/v3/sites/{siteId}/kumo-station` | KumoStation (401/404 if none) |
| GET | `/v3/sites/{siteId}/dr-programs` | Demand-response programs |
| GET | `/v3/sites/{siteId}/program-enroll` | DR enrollment status |
| GET | `/v3/sites/transfers/pending` | Pending site ownership transfers |
| GET | `/v3/site/{siteId}/preferable-contractor` | ⚠️ singular `site` — returned 404 here |
| PATCH | `/v3/sites/{siteId}/toggle-notifications` | Enable/disable all site notifications |

### GET `/v3/sites/{siteId}/zones` (dashboard read)

```jsonc
[{
  "id": "<zoneId>", "name": "<zoneName>", "isActive": true,   // name is user-defined
  "adapter": {
    "id": "<uuid>", "deviceSerial": "<serial>", "isSimulator": false,
    "roomTemp": 20.5, "spCool": 24.5, "spHeat": 20, "spAuto": null, "humidity": 63,
    "power": 0, "operationMode": "off", "previousOperationMode": "cool",
    "scheduleOwner": "adapter", "scheduleHoldEndTime": 0,
    "connected": true, "hasSensor": false, "hasMhk2": true, "mhk2DisconnectedAt": null,
    "timeZone": "America/New_York", "isHeadless": false, "isIoT": false,
    "lastStatusChangeAt": "...", "createdAt": "...", "updatedAt": "..."
  },
  "holdMode": {
    "id": "<uuid>", "enabled": false, "type": "away", "holdType": null,
    "endTime": "...", "operationMode": "auto", "fanSpeed": "auto",
    "airDirection": "auto", "spCool": 26, "spHeat": 15.5
  },
  "hasActiveSchedule": false
}]
```

### PATCH `/v3/sites/{siteId}/toggle-notifications`

```json
// Request                                      // Response 200
{ "notificationsEnabled": false, "siteId": "<siteId>" }   // {}
```

---

## Zone Endpoints

A **zone** maps 1:1 to an indoor unit (adapter). IDs are UUIDs.

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v3/zones/{zoneId}` | Single zone (same shape as the site/zones element) |
| GET | `/v3/zones/{zoneId}/connection-history?page=N` | Paginated up/down history |
| GET | `/v3/zones/{zoneId}/notification-preferences` | Per-zone alert config |
| PATCH | `/v3/zones/{zoneId}/notification-preferences` | Toggle individual alert flags |

### GET `/v3/zones/{zoneId}/connection-history?page=1`

```jsonc
{
  "next": null, "previous": null, "count": 20,
  "data": [ { "start": "...", "end": null, "isConnected": true, "uptime": "2d" }, ... ]
}
```

### GET `/v3/zones/{zoneId}/notification-preferences`

```jsonc
{
  "id": "<uuid>", "zoneId": "<zoneId>", "accountId": "<accountId>",
  "enabled": true, "system": true, "zoneError": true,
  "filterDirty": true, "filterDirtyReminderInterval": 365, "filterDirtyReminderLastSent": "...",
  "lowTempEnabled": true, "lowTemp": 0, "highTempEnabled": true, "highTemp": 40,
  "sensorSignalLost": true, "sensorLowBattery": true, "mhk2LowBattery": true,
  "drEvent": false
}
```

### PATCH `/v3/zones/{zoneId}/notification-preferences`

Send `zoneId` plus any single flag to change. Response is the updated prefs object.

```json
{ "enabled": false, "zoneId": "<zoneId>" }
{ "lowTempEnabled": true, "zoneId": "<zoneId>" }
{ "highTempEnabled": false, "zoneId": "<zoneId>" }
{ "filterDirty": true, "zoneId": "<zoneId>" }
{ "mhk2LowBattery": true, "zoneId": "<zoneId>" }
```

---

## Device Endpoints

Devices are addressed by **serial** (a 16-char alphanumeric string, e.g. `AA00B000C000000D`).

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v3/devices/{serial}` | Device record |
| GET | `/v3/devices/{serial}/status` | Adapter/network status (firmware, WiFi, setpoint limits) |
| GET | `/v3/devices/{serial}/mhk2` | MHK2 wall thermostat state (if paired) |
| GET | `/v3/devices/{serial}/initial-settings` | Initial/commissioning settings |

### GET `/v3/devices/{serial}/status`

```jsonc
{
  "firmwareVersion": "02.06.26", "roomTempDisplayOffset": 0,
  "routerSsid": "<wifi>", "routerRssi": -48,
  "minSetPoint": 19.5, "maxSetPoint": 28,
  "mac": "<mac>", "lastUpdated": "..."
}
```

### GET `/v3/devices/{serial}/mhk2`

```jsonc
{
  "id": "<uuid>", "model": "MHK2", "serial": "...", "firmware": "2.0.0",
  "thermostat": true, "thermostatBattery": "ok",
  "outdoorAir": false, "outdoorTemp": null, "outdoorHumid": null, "humidity": 63,
  "scheduleOwner": "adapter", "scheduleEnabled": "disabled",
  "holdAdapterCancelMhk2": false, "holdMhk2CancelAdapter": false,
  "autoOwner": "none", "autoStatus": "inactive"
}
```

---

## Device Control

**POST** `/v3/devices/send-command` → `200` — the single most important write endpoint.
There are **two request forms**. Send only the fields you want to change (partial updates
apply). **All temperatures are °C on the wire.**

### Form A — single device (targets one adapter)

```json
{
  "deviceSerial": "<serial>",
  "deviceCommands": { "<serial>": { "operationMode": "cool", "spCool": 24.5, "spHeat": 20 } }
}
```

### Form B — site-wide "control all zones" (multiple adapters, one call)

```json
{
  "siteId": "<siteId>",
  "deviceCommands": {
    "<serial1>": { "operationMode": "cool", "power": 1, "spCool": 23.5, "spHeat": 21.5 },
    "<serial2>": { "operationMode": "cool", "power": 1, "spCool": 24,   "spHeat": 22.5 }
  }
}
```

**Response (both forms):** `{ "devices": ["<serial>", ...] }` (the serials accepted).

### Command fields

| Field | Type | Values / range |
|-------|------|----------------|
| `operationMode` | string | `off`, `cool`, `heat`, `dry`, `vent`, `auto` |
| `power` | int | `1` = on, `0` = off (sent in Form B; in Form A, `operationMode:"off"` powers off) |
| `spCool` | number (°C) | Cooling setpoint (see per-device `minSetPoint`/`maxSetPoint`) |
| `spHeat` | number (°C) | Heating setpoint |
| `fanSpeed` | string | `superQuiet`, `quiet`, `low`, `powerful`, `superPowerful`, `auto` |
| `airDirection` | string | `auto`, `horizontal`, `midhorizontal`, `midpoint`, `midvertical`, `vertical`, `swing` |

Notes:
- **On/off:** Form A powers off with `{"operationMode":"off"}` and on by setting any mode
  (it re-sends `spCool`/`spHeat`). Form B additionally sends explicit `power: 0|1`.
- **Mode changes** carry both `spCool` and `spHeat` so the unit has valid setpoints for the
  new mode. Fan/vane-only changes send just that one field.
- Setpoint limits are per device — see `profile_update` (WebSocket) `maximumSetPoints` /
  `minimumSetPoints`, or `/v3/devices/{serial}/status` `minSetPoint`/`maxSetPoint`.
- Invalid commands return `400`.

---

## Schedules (v4)

Scheduling is a **v4** feature built around **seasons** (named schedule sets, e.g. "Winter",
"Summer") that each contain per-zone schedules made of timed **events**.

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v4/sites/{siteId}/schedule-seasons` | List seasons |
| GET | `/v4/schedule-seasons/{seasonId}/schedules` | Schedules (per zone) in a season |
| POST | `/v4/schedule-seasons/{seasonId}/schedules` | Create/replace schedules for zones |
| POST | `/v4/schedule-seasons/{seasonId}/status` | Start/stop a season (`isRunning`) |
| DELETE | `/v4/schedules/{scheduleId}/events` | Delete specific events from a schedule |

### GET `/v4/sites/{siteId}/schedule-seasons`

```jsonc
[
  { "id": "<uuid>", "name": "Summer", "isRunning": false, "isDefault": false, "hasSchedules": false },
  { "id": "<uuid>", "name": "Winter", "isRunning": true,  "isDefault": true,  "hasSchedules": true }
]
```

### GET `/v4/schedule-seasons/{seasonId}/schedules`

```jsonc
[{
  "id": "<scheduleId>",
  "zone": { "id": "<zoneId>", "name": "<zoneName>" },
  "events": [{
    "id": "<eventId>", "eventId": 1,
    "days": ["Su","Mo","Tu","We","Th","Fr","Sa"],
    "startTime": "2100",                 // HHMM, 24h, string
    "operationMode": "auto", "fanSpeed": "auto", "airDirection": "auto",
    "spCool": 25, "spHeat": 20,
    "status": "pending"                  // pending | (active)
  }]
}]
```

### POST `/v4/schedule-seasons/{seasonId}/schedules` (create) → `201`

```json
{
  "seasonId": "<seasonId>",
  "schedules": [{
    "zone": "<zoneId>",
    "events": [{
      "startTime": "2100",
      "days": ["Su","Mo","Tu","We","Th","Fr","Sa"],
      "operationMode": "auto", "fanSpeed": "auto", "airDirection": "auto",
      "spCool": 25, "spHeat": 20
    }]
  }]
}
```

Response echoes the created schedules with generated `id`/`eventId` and `status:"pending"`.

### POST `/v4/schedule-seasons/{seasonId}/status`

```json
// Request                                          // Response 200 (season object)
{ "seasonId": "<seasonId>", "isRunning": true }     // { "id","name","isRunning","isDefault","hasSchedules" }
```

### DELETE `/v4/schedules/{scheduleId}/events` → `204`

```json
{ "events": ["<eventId>", ...] }
```

---

## Notifications

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v3/notifications/active?page=N` | Active (unresolved) notifications, paginated |
| GET | `/v3/notifications/active/unseen-count` | Badge count |
| GET | `/v3/notifications/resolved?page=N` | Resolved history, paginated |

Per-zone alert configuration and the site-wide toggle live under the Zone and Site
sections (`.../notification-preferences`, `.../toggle-notifications`).

---

## Real-Time Updates (Socket.IO)

Live device state streams over **Socket.IO v4** (engine.io 4) at
`wss://socket-prod.kumocloud.com/socket.io/?EIO=4&transport=websocket`. Control is **not**
sent here — commands go via REST `send-command`; the socket is for **receiving** state.

Frames are Socket.IO encoded: `42["<event>", <arg1>, <arg2>, ...]` (the `4`=message,
`2`=event; `2`/`3` alone are engine.io ping/pong; `2probe`/`3probe` are the upgrade probe).

### Client → server (subscriptions & requests)

| Event | Args | Purpose |
|-------|------|---------|
| `subscribe` | `["", "<accountId>"]` | Subscribe to account-level updates |
| `subscribe` | `["<serial>"]` | Subscribe to a device |
| `device_status_v2` | `["<serial>"]` | Request current connection status |
| `force_adapter_request` | `["<serial>", "<kind>"]` | Force a fresh pull; `kind` ∈ `iuStatus`, `profile`, `adapterStatus`, `mhk2` |

### Server → client (pushes)

| Event | Payload summary |
|-------|-----------------|
| `subscribed` | `"Successfully subscribed to: <id>"` |
| `device_update` | Full/partial live state: `power, operationMode, roomTemp, humidity, spCool, spHeat, fanSpeed, airDirection, rssi, twoFiguresCode, connected, modelNumber, ...` |
| `device_status_v2` | `{ deviceSerial, status:"connected", lastTimeConnected, lastTimeDisconnected, lastDisconnectedReason, hasIduCommunicationError }` |
| `profile_update` | Device **capabilities** + setpoint limits (see below) |
| `adapter_update` | `{ firmwareVersion, roomTempDisplayOffset, routerSsid, routerRssi, minSetPoint, maxSetPoint }` |

### `profile_update` (capabilities)

```jsonc
{
  "deviceSerial": "<serial>",
  "hasModeHeat": true, "hasModeDry": true, "hasModeVent": true, "hasModeTest": false,
  "hasVaneDir": true, "hasVaneSwing": true,
  "hasFanSpeedAuto": true, "numberOfFanSpeeds": 5,
  "usesSetPointInDryMode": true, "extendedTemps": true,
  "hasHotAdjust": true, "hasDefrost": true, "hasStandby": true,
  "hasInitialSettings": false,
  "maximumSetPoints": { "cool": 30, "heat": 30, "auto": 30 },
  "minimumSetPoints": { "cool": 15, "heat": 9,  "auto": 15 }
}
```

---

## Data Reference

**Operation modes:** `off`, `cool`, `heat`, `dry`, `vent`, `auto`
**Fan speeds:** `superQuiet`, `quiet`, `low`, `powerful`, `superPowerful`, `auto`
**Air directions:** `auto`, `horizontal`, `midhorizontal`, `midpoint`, `midvertical`, `vertical`, `swing`
**Schedule days:** `Su`, `Mo`, `Tu`, `We`, `Th`, `Fr`, `Sa`
**Schedule time:** `"HHMM"` 24-hour string (e.g. `"2100"` = 21:00)
**Roles:** `owner` (site role)
**Temperature units:** always **°C on the wire**; `preferences.celsius` only affects display.
**`twoFiguresCode`:** unit fault/status code (`"A0"` = normal).
**Identifiers:** sites/zones/adapters/seasons/schedules/events use UUIDs; devices use the
physical **serial**; the account `id` is a numeric string reused as the socket subscription key.

---

## Non-API Hosts (Telemetry)

Seen in traffic but **not** part of the control API — safe to ignore for a client:

| Host | Purpose |
|------|---------|
| `o4506860419612672.ingest.us.sentry.io`, `o2129.ingest.sentry.io` | Sentry crash/error reporting |
| `api.revopush.org` | CodePush (React Native OTA JS bundle updates) |
| `mobile.launchdarkly.com`, `clientstream.launchdarkly.com` | LaunchDarkly feature flags |
| `status-api.kumocloud.com` | Service health (`{}` = OK) |

---

## Capture Methodology

Reproducible MITM capture of the iOS app (own device, own account):

1. **Proxy:** `mitmdump --listen-host 0.0.0.0 -p 8080 -w capture.flow` on the Mac.
2. **Phone:** Wi-Fi → Configure Proxy → Manual → `<mac-ip>:8080`; install the mitmproxy CA
   via `http://mitm.it/cert/pem`, then **Settings → General → About → Certificate Trust
   Settings** → enable it (this second toggle is required for TLS to decrypt).
3. **No certificate pinning** — the app decrypts with a standard user-trusted CA; no Frida /
   jailbreak needed.
4. **WebSocket gotcha:** `mitmdump -w` only flushes a flow to disk when the connection
   closes; the app holds a long-lived socket, so a live addon (`websocket_message` hook)
   was used to log frame contents in real time.
5. Endpoints/bodies were extracted from the `.flow` with `mitmproxy.io.FlowReader`; all
   tokens, serials, MACs, MAKs, coordinates, email, and address were redacted for this doc.

> Capture artifacts (`*.flow`, `*.log`) contain live JWTs, the FCM token, and PII — they are
> git-ignored and must never be committed.
