"""
Kumo Cloud API Client

A Python client for interacting with the Mitsubishi Kumo Cloud API v3.
Based on reverse-engineered API documentation.
"""

from dotenv import load_dotenv
load_dotenv()

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import os

# Optional Socket.IO support for real-time data
try:
    import socketio
    HAS_SOCKETIO = True
except ImportError:
    HAS_SOCKETIO = False
    socketio = None


BASE_URL = "https://app-prod.kumocloud.com"
SOCKET_URL = "https://socket-prod.kumocloud.com"
APP_VERSION = "3.2.4"

# User-Agent from Kumo Cloud iOS app (captured via mitmproxy)
USER_AGENT = "kumocloud/1122 CFNetwork/3860.200.71 Darwin/25.1.0"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "x-app-version": APP_VERSION,
    "app-env": "prd",
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
    # Disable caching to get fresh data from the server
    "Cache-Control": "no-cache, no-store",
    "x-allow-cache": "false",
}

TOKEN_FILE = Path.home() / ".kumo_tokens.json"

# Environment variable names for configuration
ENV_USERNAME = "KUMO_USERNAME"
ENV_PASSWORD = "KUMO_PASSWORD"
ENV_SITE_ID = "KUMO_SITE_ID"
ENV_SERIAL_PREFIX = "KUMO_SERIAL_"


# ========== Temperature Conversion ==========

def celsius_to_fahrenheit(c: float | None) -> int | None:
    """Convert Celsius to Fahrenheit using Mitsubishi thermostat rounding rules.

    The thermostat uses inverted rounding:
    - If fractional part < 0.5: round UP
    - If fractional part >= 0.5: round DOWN
    - If exact integer: no rounding needed
    """
    if c is None:
        return None

    fahrenheit = (c * 9 / 5) + 32
    integer_part = int(fahrenheit)
    fractional_part = fahrenheit - integer_part

    if fractional_part == 0:
        return integer_part
    elif fractional_part < 0.5:
        return integer_part + 1  # Round up
    else:
        return integer_part  # Round down


def fahrenheit_to_celsius(f: float | None) -> float | None:
    """Convert Fahrenheit to Celsius."""
    if f is None:
        return None
    return round((f - 32) * 5 / 9, 1)


@dataclass
class TokenInfo:
    """JWT token information with expiration tracking."""
    access: str
    refresh: str
    access_expires_at: datetime = field(default_factory=datetime.now)
    refresh_expires_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_response(cls, data: dict) -> "TokenInfo":
        """Create TokenInfo from API response."""
        # Access token expires in ~20 minutes, refresh in ~1 month
        now = datetime.now()
        return cls(
            access=data.get("access", ""),
            refresh=data.get("refresh", ""),
            access_expires_at=now + timedelta(minutes=18),  # Buffer before actual expiry
            refresh_expires_at=now + timedelta(days=25),  # Buffer before actual expiry
        )

    def is_access_expired(self) -> bool:
        return datetime.now() >= self.access_expires_at

    def is_refresh_expired(self) -> bool:
        return datetime.now() >= self.refresh_expires_at

    def to_dict(self) -> dict:
        return {
            "access": self.access,
            "refresh": self.refresh,
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenInfo":
        return cls(
            access=data["access"],
            refresh=data["refresh"],
            access_expires_at=datetime.fromisoformat(data["access_expires_at"]),
            refresh_expires_at=datetime.fromisoformat(data["refresh_expires_at"]),
        )


@dataclass
class DeviceStatus:
    """Represents the status of a Kumo device (indoor unit)."""
    serial: str
    name: str
    room_temp: int | None = None
    set_temp: int | None = None
    sp_cool: int | None = None  # Cooling setpoint (F)
    sp_heat: int | None = None  # Heating setpoint (F)
    mode: str | None = None  # off, cool, heat, dry, vent, auto
    fan_speed: str | None = None  # superQuiet, quiet, low, powerful, superPowerful, auto
    air_direction: str | None = None  # auto, horizontal, midhorizontal, midpoint, midvertical, vertical, swing
    is_on: bool = False
    humidity: int | None = None
    connected: bool = True
    rssi: int | None = None  # WiFi signal strength (dBm)
    has_sensor: bool = False
    has_mhk2: bool = False  # Has MHK2 wall controller
    is_headless: bool = False
    filter_dirty: bool = False
    defrost: bool = False
    standby: bool = False
    hot_adjust: bool = False
    schedule_owner: str | None = None  # adapter or cloud
    last_status_change: str | None = None  # ISO timestamp
    raw_data: dict = field(default_factory=dict)

    def temp_diff(self) -> float | None:
        """Return difference between room temp and set temp."""
        if self.room_temp is not None and self.set_temp is not None:
            return round(self.room_temp - self.set_temp, 1)
        return None

    def __str__(self) -> str:
        status = "ON" if self.is_on else "OFF"
        conn = "" if self.connected else " [OFFLINE]"
        temp_info = ""
        if self.room_temp is not None:
            temp_info = f" Room: {self.room_temp:.1f}F"
            if self.set_temp is not None:
                diff = self.temp_diff()
                if diff is not None:
                    if diff < 0:
                        diff_str = f"heat another: {abs(diff):.1f}F"
                    elif diff > 0:
                        diff_str = f"too hot by: {diff:.1f}F"
                    else:
                        diff_str = "at target"
                    temp_info += f" | Set: {self.set_temp:.1f}F ({diff_str})"
                else:
                    temp_info += f" | Set: {self.set_temp:.1f}F"
        mode_info = f" | Mode: {self.mode}" if self.mode else ""
        fan_info = f" | Fan: {self.fan_speed}" if self.fan_speed else ""
        vane_info = f" | Vane: {self.air_direction}" if self.air_direction else ""
        humidity_info = f" | Humidity: {self.humidity}%" if self.humidity is not None else ""
        return f"{self.name:<12} [{status}]{conn}{temp_info}{mode_info}{fan_info}{vane_info}{humidity_info}"


class KumoCloudError(Exception):
    """Base exception for Kumo Cloud API errors."""
    pass


class AuthenticationError(KumoCloudError):
    """Authentication failed."""
    pass


class KumoCloudClient:
    """
    Client for the Kumo Cloud API v3.

    Handles authentication, token refresh, and all API operations.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        site_id: str | None = None,
        device_serials: dict[str, str] | None = None,
        token_file: Path | None = None,
    ):
        """
        Initialize Kumo Cloud client.

        Args:
            username: Kumo Cloud email (or set KUMO_USERNAME env var)
            password: Kumo Cloud password (or set KUMO_PASSWORD env var)
            site_id: Default site ID (or set KUMO_SITE_ID env var)
            device_serials: Dict mapping friendly names to device serials,
                           e.g., {"bedroom": "ABC123", "office": "DEF456"}
                           (or set KUMO_SERIAL_* env vars)
            token_file: Path to token cache file (default: ~/.kumo_tokens.json)
        """
        self.username = username or os.environ.get(ENV_USERNAME)
        self.password = password or os.environ.get(ENV_PASSWORD)
        self.site_id = site_id or os.environ.get(ENV_SITE_ID)
        self.device_serials = device_serials or self._load_serials_from_env()
        self.token_file = token_file or TOKEN_FILE
        self.tokens: TokenInfo | None = None
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers=DEFAULT_HEADERS,
            http2=True,
            timeout=30.0,
        )
        self._load_tokens()

        # Socket.IO client for real-time updates (optional)
        self._sio: "socketio.Client | None" = None
        self._device_updates: dict[str, dict] = {}
        self._update_events: dict[str, threading.Event] = {}
        self._device_conn: dict[str, dict] = {}
        self._conn_events: dict[str, threading.Event] = {}

    def _load_serials_from_env(self) -> dict[str, str]:
        """Load device serials from environment variables (KUMO_SERIAL_*)."""
        serials = {}
        for key, value in os.environ.items():
            if key.startswith(ENV_SERIAL_PREFIX):
                device_name = key[len(ENV_SERIAL_PREFIX):].lower()
                serials[device_name] = value
        return serials

    def _load_tokens(self) -> None:
        """Load tokens from file if available."""
        if self.token_file.exists():
            try:
                data = json.loads(self.token_file.read_text())
                self.tokens = TokenInfo.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                self.tokens = None

    def _save_tokens(self) -> None:
        """Save tokens to file."""
        if self.tokens:
            self.token_file.write_text(json.dumps(self.tokens.to_dict(), indent=2))
            self.token_file.chmod(0o600)  # Restrict permissions

    def _get_auth_header(self) -> dict:
        """Get Authorization header with current access token."""
        if not self.tokens:
            raise AuthenticationError("Not authenticated. Call login() first.")
        return {"Authorization": f"Bearer {self.tokens.access}"}

    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | None = None,
        require_auth: bool = True,
        retry_on_auth_failure: bool = True,
    ) -> dict | list:
        """Make an API request with automatic token refresh."""
        headers = {}

        if require_auth:
            self._ensure_authenticated()
            headers.update(self._get_auth_header())

        response = self._client.request(
            method,
            endpoint,
            json=json_data,
            headers=headers,
        )

        if response.status_code == 401 and retry_on_auth_failure and require_auth:
            # Token might have expired, try refresh
            self._refresh_token()
            headers.update(self._get_auth_header())
            response = self._client.request(
                method,
                endpoint,
                json=json_data,
                headers=headers,
            )

        if response.status_code >= 400:
            raise KumoCloudError(
                f"API error {response.status_code}: {response.text}"
            )

        if response.content:
            return response.json()
        return {}

    def _ensure_authenticated(self) -> None:
        """Ensure we have valid tokens, refreshing or logging in as needed."""
        if not self.tokens:
            if self.username and self.password:
                self.login(self.username, self.password)
            else:
                raise AuthenticationError(
                    "Not authenticated. Provide credentials or call login()."
                )
        elif self.tokens.is_access_expired():
            if self.tokens.is_refresh_expired():
                if self.username and self.password:
                    self.login(self.username, self.password)
                else:
                    raise AuthenticationError("Tokens expired. Please login again.")
            else:
                self._refresh_token()

    # ========== Authentication ==========

    def login(self, username: str | None = None, password: str | None = None) -> dict:
        """
        Login to Kumo Cloud and obtain access/refresh tokens.

        Args:
            username: Kumo Cloud username (email)
            password: Kumo Cloud password

        Returns:
            User account information
        """
        username = username or self.username
        password = password or self.password

        if not username or not password:
            raise AuthenticationError("Username and password required for login.")

        response = self._client.post(
            "/v3/login",
            json={
                "username": username,
                "password": password,
                "appVersion": APP_VERSION,
            },
        )

        if response.status_code >= 400:
            raise AuthenticationError(f"Login failed: {response.text}")

        data = response.json()
        token_data = data.get("token", {})
        self.tokens = TokenInfo.from_response(token_data)
        self.username = username
        self.password = password
        self._save_tokens()

        return data

    def _refresh_token(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self.tokens or not self.tokens.refresh:
            raise AuthenticationError("No refresh token available.")

        response = self._client.post(
            "/v3/refresh",
            json={"refresh": self.tokens.refresh},
            headers={"Authorization": f"Bearer {self.tokens.refresh}"},
        )

        if response.status_code >= 400:
            raise AuthenticationError(f"Token refresh failed: {response.text}")

        data = response.json()
        self.tokens = TokenInfo.from_response(data)
        self._save_tokens()

    # ========== Socket.IO Real-Time Support ==========

    def _connect_socketio(self) -> bool:
        """
        Connect to the Socket.IO server for real-time updates.

        Returns:
            True if connected successfully, False otherwise.
        """
        if not HAS_SOCKETIO:
            return False

        if self._sio is not None and self._sio.connected:
            return True

        self._ensure_authenticated()

        try:
            self._sio = socketio.Client(logger=False, engineio_logger=False)

            # Set up event handlers
            @self._sio.on("device_update")
            def on_device_update(data):
                serial = data.get("deviceSerial")
                if serial:
                    self._device_updates[serial] = data
                    if serial in self._update_events:
                        self._update_events[serial].set()

            @self._sio.on("device_status_v2")
            def on_device_status(data):
                serial = data.get("deviceSerial")
                # The account-level emit ("") only acks; per-serial emits carry status.
                if serial and data.get("status"):
                    self._device_conn[serial] = data
                    if serial in self._conn_events:
                        self._conn_events[serial].set()

            @self._sio.on("connect")
            def on_connect():
                pass

            # Connect with auth token
            self._sio.connect(
                SOCKET_URL,
                auth={"token": self.tokens.access},
                headers={"Authorization": f"Bearer {self.tokens.access}"},
                transports=["websocket", "polling"],
            )

            return self._sio.connected
        except Exception:
            self._sio = None
            return False

    def _disconnect_socketio(self) -> None:
        """Disconnect from Socket.IO server."""
        if self._sio is not None:
            try:
                self._sio.disconnect()
            except Exception:
                pass
            self._sio = None

    def force_device_refresh(self, device_serial: str, timeout: float = 5.0) -> dict | None:
        """
        Force a device to report its current status via Socket.IO.

        This sends force_adapter_request events to get fresh data directly
        from the device, bypassing the server cache.

        Args:
            device_serial: Device serial number
            timeout: Max seconds to wait for response

        Returns:
            Fresh device data dict, or None if Socket.IO unavailable/timeout.
        """
        if not HAS_SOCKETIO:
            return None

        if not self._connect_socketio():
            return None

        try:
            # Clear any previous update for this device
            self._device_updates.pop(device_serial, None)
            event = threading.Event()
            self._update_events[device_serial] = event

            # Subscribe to device updates
            self._sio.emit("subscribe", device_serial)

            # Send force_adapter_request events (as the mobile app does)
            for request_type in ["iuStatus", "profile", "adapterStatus", "mhk2"]:
                self._sio.emit("force_adapter_request", (device_serial, request_type))

            # Wait for device_update response
            if event.wait(timeout=timeout):
                return self._device_updates.get(device_serial)
            return None
        except Exception:
            return None
        finally:
            self._update_events.pop(device_serial, None)

    def get_reachability(
        self,
        device_serials: list[str] | None = None,
        timeout: float = 6.0,
    ) -> dict[str, dict]:
        """
        Ask the cloud whether each adapter is actually online.

        The zones payload is not a freshness signal: when an adapter drops off
        the network the cloud keeps serving its last known state, with
        adapter.connected still True and adapter.updatedAt still moving
        (unrelated refreshes touch the row). Commands sent to such a unit return
        HTTP 200 and reach nothing. The only authoritative signal is the
        Socket.IO device_status_v2 event, requested per serial.

        Args:
            device_serials: Serials to check (defaults to configured KUMO_SERIAL_*).
            timeout: Max seconds to wait for all replies.

        Returns:
            {serial: {"status": "connected"|"disconnected",
                      "lastTimeConnected": ..., "lastTimeDisconnected": ...,
                      "lastDisconnectedReason": ...,
                      "hasIduCommunicationError": ...}}
            Empty dict if Socket.IO is unavailable.
        """
        if not HAS_SOCKETIO:
            return {}

        serials = device_serials or list(self.device_serials.values())
        if not serials:
            return {}

        if not self._connect_socketio():
            return {}

        events = {}
        try:
            for serial in serials:
                self._device_conn.pop(serial, None)
                event = threading.Event()
                self._conn_events[serial] = event
                events[serial] = event
                self._sio.emit("device_status_v2", serial)

            deadline = time.monotonic() + timeout
            for serial, event in events.items():
                event.wait(timeout=max(0.0, deadline - time.monotonic()))

            return {s: self._device_conn[s] for s in serials if s in self._device_conn}
        except Exception:
            return {}
        finally:
            for serial in events:
                self._conn_events.pop(serial, None)

    def get_fresh_device_status(self, device_serial: str) -> dict | None:
        """
        Get fresh device status, using Socket.IO if available.

        First attempts to get real-time data via Socket.IO force_adapter_request.
        Falls back to REST API if Socket.IO is unavailable.

        Args:
            device_serial: Device serial number

        Returns:
            Device status dict with current values.
        """
        # Try Socket.IO first for fresh data
        fresh_data = self.force_device_refresh(device_serial)
        if fresh_data:
            return fresh_data

        # Fall back to REST API (may have cached data)
        return self.get_device(device_serial)

    # ========== Service ==========

    def get_config(self) -> dict:
        """
        Get service-wide configuration (notification rate limits, archiving, etc.).

        Note the path is /v3/config; the unversioned /config does not exist.
        """
        return self._request("GET", "/v3/config")

    # ========== Account ==========

    def get_account(self) -> dict:
        """Get current user account information."""
        return self._request("GET", "/v3/accounts/me")

    # ========== Sites ==========

    def get_sites(self) -> list[dict]:
        """
        Get all sites (locations) associated with the account.

        Returns:
            List of site dictionaries with id, name, etc.
        """
        return self._request("GET", "/v3/sites/")

    def get_site(self, site_id: str) -> dict:
        """Get details for a specific site."""
        return self._request("GET", f"/v3/sites/{site_id}")

    def get_kumo_station(self, site_id: str) -> dict:
        """Get Kumo Station info for a site (if applicable)."""
        return self._request("GET", f"/v3/sites/{site_id}/kumo-station")

    def get_weather(self, site_id: str | None = None) -> dict:
        """
        Get current weather data for a site location.

        Args:
            site_id: Site ID. Uses KUMO_SITE_ID from env if not provided.

        Returns:
            Weather data including temperature, humidity, conditions, etc.
        """
        target_site_id = site_id or self.site_id
        if not target_site_id:
            raise KumoCloudError("Site ID required for weather endpoint")
        return self._request("GET", f"/v3/sites/{target_site_id}/weather")

    # ========== Zones ==========

    def get_zones(self, site_id: str) -> list[dict]:
        """
        Get all zones for a site.

        Zones contain the device information including serial numbers
        needed for device-specific API calls.
        """
        return self._request("GET", f"/v3/sites/{site_id}/zones")

    def get_zone(self, zone_id: str) -> dict:
        """Get details for a specific zone."""
        return self._request("GET", f"/v3/zones/{zone_id}")

    def get_groups(self, site_id: str) -> list[dict]:
        """Get device groups for a site."""
        return self._request("GET", f"/v3/sites/{site_id}/groups")

    # ========== Devices ==========

    def get_device(self, device_serial: str) -> dict:
        """Get device information."""
        return self._request("GET", f"/v3/devices/{device_serial}")

    def get_device_profile(self, device_serial: str) -> dict:
        """Get device profile/capabilities."""
        return self._request("GET", f"/v3/devices/{device_serial}/profile")

    def get_device_limits(self, device_serial: str) -> dict:
        """
        Get this unit's allowed setpoint range per mode, in Fahrenheit.

        The range is set on the unit (function code 181, reachable from an MHK2
        or by an installer) and is enforced server-side: a setpoint outside it
        comes back as HTTP 400 with commands: ["invalidSpHeatRange"]. It is
        per-unit, so two units on one site can differ.

        Returns:
            {"cool": {"min": F, "max": F}, "heat": {...}, "auto": {...}}
            Modes the profile does not report are omitted.
        """
        profile = self.get_device_profile(device_serial)
        # /devices/{serial}/profile returns a single-element list for some
        # accounts and a bare object for others.
        if isinstance(profile, list):
            profile = profile[0] if profile else {}

        minimums = profile.get("minimumSetPoints") or {}
        maximums = profile.get("maximumSetPoints") or {}

        limits = {}
        for mode in ("cool", "heat", "auto"):
            low = minimums.get(mode)
            high = maximums.get(mode)
            if low is None and high is None:
                continue
            limits[mode] = {
                "min": celsius_to_fahrenheit(low),
                "max": celsius_to_fahrenheit(high),
                "min_celsius": low,
                "max_celsius": high,
            }
        return limits

    def get_device_status(self, device_serial: str) -> dict:
        """
        Get current device status including temperatures.

        Returns operational data including current room temperature,
        set temperature, mode, fan speed, etc.
        """
        return self._request("GET", f"/v3/devices/{device_serial}/status")

    def get_device_initial_settings(self, device_serial: str) -> dict:
        """Get device initial/default settings."""
        return self._request("GET", f"/v3/devices/{device_serial}/initial-settings")

    def get_device_kumo_properties(self, device_serial: str) -> dict:
        """Get Kumo-specific device properties."""
        return self._request("GET", f"/v3/devices/{device_serial}/kumo-properties")

    def send_device_command(self, device_serial: str, commands: dict) -> dict:
        """
        Send command to device via the send-command endpoint.

        This is the actual endpoint used by the Kumo Cloud mobile app.

        Args:
            device_serial: Device serial number
            commands: Dict of commands, e.g., {"spHeat": 20.0} or {"operationMode": "heat"}

        Common commands:
            - spCool: Cooling setpoint temperature (Celsius)
            - spHeat: Heating setpoint temperature (Celsius)
            - operationMode: "off", "cool", "heat", "dry", "vent", "auto"
            - fanSpeed: "superQuiet", "quiet", "low", "powerful", "superPowerful", "auto"
            - airDirection: "auto", "horizontal", "midhorizontal", "midpoint", "midvertical", "vertical", "swing"
            - power: 0 (off) or 1 (on)

        Returns:
            API response (typically {"devices": ["serial"]})
        """
        payload = {
            "deviceSerial": device_serial,
            "commands": commands
        }
        return self._request("POST", "/v3/devices/send-command", json_data=payload)

    def set_device_settings(self, device_serial: str, settings: dict) -> dict:
        """
        Update device settings (alias for send_device_command).

        Deprecated: Use send_device_command() instead.
        """
        return self.send_device_command(device_serial, settings)

    def set_device_status(self, device_serial: str, settings: dict) -> dict:
        """
        Update device status/settings (alias for send_device_command).

        Deprecated: Use send_device_command() instead.
        """
        return self.send_device_command(device_serial, settings)

    # ========== High-Level Methods ==========

    def get_all_devices(
        self,
        site_id: str | None = None,
        full: bool = False,
        refresh: bool = False,
    ) -> list[DeviceStatus]:
        """
        Get status of all devices across all sites (or specific site).

        Args:
            site_id: Optional site ID. Uses KUMO_SITE_ID from env if not provided.
            full: If True, fetch full device data including fan speed and air direction.
                  This makes additional API calls per device but provides complete info.
            refresh: If True, use Socket.IO to force devices to report fresh status.
                     This bypasses server cache and gets actual current values from
                     the thermostats. Requires python-socketio package.

        Returns:
            List of DeviceStatus objects with current state.
        """
        devices = []
        target_site_id = site_id or self.site_id

        if target_site_id:
            # Use configured site
            sites = [{"id": target_site_id, "name": "Configured Site"}]
        else:
            # Fetch all sites
            sites = self.get_sites()

        for site in sites:
            sid = site["id"]
            zones = self.get_zones(sid)

            for zone in zones:
                # Extract device info from zone - adapter contains all status data
                adapter = zone.get("adapter", {})
                device_serial = adapter.get("deviceSerial")

                if not device_serial:
                    continue

                # Use Socket.IO refresh if requested (gets fresh data from device)
                if refresh:
                    fresh_data = self.force_device_refresh(device_serial)
                    if fresh_data:
                        merged_data = {**adapter, **fresh_data}
                    elif full:
                        device_data = self.get_device(device_serial)
                        merged_data = {**adapter, **device_data}
                    else:
                        merged_data = adapter
                # Optionally fetch full device data (includes fan/vane)
                elif full:
                    device_data = self.get_device(device_serial)
                    # Merge zone adapter data with device data (device has more fields)
                    merged_data = {**adapter, **device_data}
                else:
                    merged_data = adapter

                device = self._parse_device_status(
                    device_serial,
                    zone.get("name", "Unknown"),
                    merged_data,
                )
                devices.append(device)

        return devices

    def get_serial_by_name(self, name: str) -> str | None:
        """
        Get device serial by name (case-insensitive).

        Uses configured serials from env (KUMO_SERIAL_*) if available.

        Args:
            name: Device name like "upstairs" or "downstairs"

        Returns:
            Device serial or None if not found.
        """
        name_lower = name.lower()

        # Check configured serials first
        if name_lower in self.device_serials:
            return self.device_serials[name_lower]

        # Fall back to searching zones
        site_id = self.site_id
        if not site_id:
            sites = self.get_sites()
            if sites:
                site_id = sites[0]["id"]

        if site_id:
            zones = self.get_zones(site_id)
            for zone in zones:
                if zone.get("name", "").lower() == name_lower:
                    adapter = zone.get("adapter", {})
                    return adapter.get("deviceSerial")

        return None

    def get_device_by_name(self, name: str, refresh: bool = False) -> DeviceStatus | None:
        """
        Get device status by name (e.g., "upstairs", "downstairs").

        Uses KUMO_SERIAL_* env vars or searches zones by name.

        Args:
            name: Device/zone name like "upstairs" or "downstairs"
            refresh: If True, use Socket.IO to force device to report fresh status.
                     This bypasses server cache and gets actual current values.

        Returns:
            DeviceStatus or None if not found.
        """
        serial = self.get_serial_by_name(name)
        if not serial:
            return None

        # Get status from zones endpoint (more efficient, includes all data)
        site_id = self.site_id
        if not site_id:
            sites = self.get_sites()
            if sites:
                site_id = sites[0]["id"]

        if site_id:
            zones = self.get_zones(site_id)
            for zone in zones:
                adapter = zone.get("adapter", {})
                if adapter.get("deviceSerial") == serial:
                    # Use Socket.IO refresh if requested
                    if refresh:
                        fresh_data = self.force_device_refresh(serial)
                        if fresh_data:
                            merged_data = {**adapter, **fresh_data}
                        else:
                            merged_data = adapter
                    else:
                        merged_data = adapter

                    return self._parse_device_status(
                        serial,
                        zone.get("name", name),
                        merged_data,
                    )

        return None

    def _parse_device_status(
        self,
        serial: str,
        name: str,
        status_data: dict,
    ) -> DeviceStatus:
        """Parse raw status data into DeviceStatus object.

        Note: API returns temperatures in Celsius, we convert to Fahrenheit.
        """
        # Get raw temps (Celsius from API)
        raw_room_temp = status_data.get("roomTemp")
        raw_sp_cool = status_data.get("spCool")
        raw_sp_heat = status_data.get("spHeat")

        # Get the appropriate setpoint based on current mode
        mode = status_data.get("operationMode") or status_data.get("mode")
        # In auto the unit reports which half it is currently running as
        # (autoCool/autoHeat); dry runs off the cooling setpoint.
        if mode in ("cool", "autoCool", "dry"):
            raw_set_temp = raw_sp_cool
        elif mode in ("heat", "autoHeat"):
            raw_set_temp = raw_sp_heat
        else:
            # Default to cooling setpoint or whatever is available
            raw_set_temp = raw_sp_cool or raw_sp_heat

        # Convert to Fahrenheit for display
        room_temp_f = celsius_to_fahrenheit(raw_room_temp)
        set_temp_f = celsius_to_fahrenheit(raw_set_temp)
        sp_cool_f = celsius_to_fahrenheit(raw_sp_cool)
        sp_heat_f = celsius_to_fahrenheit(raw_sp_heat)

        # Get display config for filter/defrost/standby/hotAdjust
        display_config = status_data.get("displayConfig", {})

        return DeviceStatus(
            serial=serial,
            name=name,
            room_temp=room_temp_f,
            set_temp=set_temp_f,
            sp_cool=sp_cool_f,
            sp_heat=sp_heat_f,
            mode=mode,
            fan_speed=status_data.get("fanSpeed"),
            air_direction=status_data.get("airDirection"),
            is_on=status_data.get("power", 0) == 1,
            humidity=status_data.get("humidity"),
            connected=status_data.get("connected", True),
            rssi=status_data.get("rssi"),
            has_sensor=status_data.get("hasSensor", False),
            has_mhk2=status_data.get("hasMhk2", False),
            is_headless=status_data.get("isHeadless", False),
            filter_dirty=display_config.get("filter", False),
            defrost=display_config.get("defrost", False),
            standby=display_config.get("standby", False),
            hot_adjust=display_config.get("hotAdjust", False),
            schedule_owner=status_data.get("scheduleOwner"),
            last_status_change=status_data.get("lastStatusChangeAt"),
            raw_data=status_data,
        )

    def _check_setpoint(
        self,
        device_serial: str,
        temp: float,
        mode: str | None = None,
    ) -> None:
        """Raise KumoCloudError if temp is outside the unit's allowed range."""
        try:
            limits = self.get_device_limits(device_serial)
        except KumoCloudError:
            return  # profile unavailable; let the API decide

        # Without an explicit mode both setpoints are written, so the value has
        # to clear whichever range is tighter.
        modes = [mode] if mode in ("cool", "heat", "auto") else ["cool", "heat"]
        for m in modes:
            bounds = limits.get(m)
            if not bounds:
                continue
            low, high = bounds["min"], bounds["max"]
            if low is not None and temp < low:
                raise KumoCloudError(
                    f"{temp:.0f}F is below this unit's {m} minimum of {low}F "
                    f"({bounds['min_celsius']}C). The limit lives on the unit "
                    f"(function code 181), not in the API."
                )
            if high is not None and temp > high:
                raise KumoCloudError(
                    f"{temp:.0f}F is above this unit's {m} maximum of {high}F "
                    f"({bounds['max_celsius']}C)."
                )

    def set_temperature(
        self,
        device_serial: str,
        temp: float,
        mode: str | None = None,
        check_limits: bool = True,
    ) -> dict:
        """
        Set target temperature for a device.

        Args:
            device_serial: Device serial number
            temp: Target temperature in Fahrenheit (converted to Celsius for API)
            mode: Optional mode to set ("cool", "heat", "auto")
            check_limits: Validate against the unit's own setpoint range first, so
                          an out-of-range value fails with a readable message
                          instead of the API's invalidSpHeatRange/invalidSpCoolRange.

        Returns:
            API response
        """
        commands = {}

        # Convert Fahrenheit to Celsius for API
        temp_celsius = fahrenheit_to_celsius(temp)

        if check_limits:
            self._check_setpoint(device_serial, temp, mode)

        # Set appropriate temperature field based on mode
        if mode == "cool":
            commands["spCool"] = temp_celsius
            commands["operationMode"] = "cool"
        elif mode == "heat":
            commands["spHeat"] = temp_celsius
            commands["operationMode"] = "heat"
        elif mode == "auto":
            commands["spCool"] = temp_celsius
            commands["spHeat"] = temp_celsius
            commands["operationMode"] = "auto"
        else:
            # Just set both setpoints without changing mode
            commands["spCool"] = temp_celsius
            commands["spHeat"] = temp_celsius

        return self.send_device_command(device_serial, commands)

    def set_mode(self, device_serial: str, mode: str) -> dict:
        """
        Set operating mode for a device.

        Args:
            device_serial: Device serial number
            mode: Mode string - "off", "cool", "heat", "dry", "fan"/"vent", "auto"
                  Note: "fan" is translated to "vent" for the API.
        """
        # Translate user-friendly "fan" to API's "vent"
        api_mode = "vent" if mode == "fan" else mode
        return self.send_device_command(device_serial, {"operationMode": api_mode})

    def turn_on(self, device_serial: str) -> dict:
        """Turn on a device."""
        return self.send_device_command(device_serial, {"power": 1})

    def turn_off(self, device_serial: str) -> dict:
        """Turn off a device."""
        return self.send_device_command(device_serial, {"power": 0})

    def set_fan_speed(self, device_serial: str, speed: str) -> dict:
        """
        Set fan speed for a device.

        Args:
            device_serial: Device serial number
            speed: Fan speed - "superQuiet", "quiet", "low", "powerful", "superPowerful", "auto"
        """
        return self.send_device_command(device_serial, {"fanSpeed": speed})

    def set_air_direction(self, device_serial: str, direction: str) -> dict:
        """
        Set air direction (vane) for a device.

        Args:
            device_serial: Device serial number
            direction: Air direction - "auto", "horizontal", "midhorizontal",
                       "midpoint", "midvertical", "vertical", "swing"
        """
        return self.send_device_command(device_serial, {"airDirection": direction})

    # ========== Zone Methods ==========

    def get_zone_schedules(self, zone_id: str) -> list[dict]:
        """Get schedules configured for a zone."""
        return self._request("GET", f"/v3/zones/{zone_id}/schedules")

    def get_zone_notification_preferences(self, zone_id: str) -> dict:
        """Get notification preferences for a zone."""
        return self._request("GET", f"/v3/zones/{zone_id}/notification-preferences")

    def get_zone_connection_history(self, zone_id: str, page: int = 1) -> dict:
        """
        Get connection history for a zone.

        Args:
            zone_id: Zone ID
            page: Page number for pagination

        Returns:
            Dict with 'data' list of connection events, 'next', 'previous', 'count'
        """
        return self._request("GET", f"/v3/zones/{zone_id}/connection-history?page={page}")

    def get_zone_comfort_settings(self, zone_id: str) -> dict:
        """Get comfort settings for a zone."""
        return self._request("GET", f"/v3/zones/{zone_id}/comfort-settings?zoneId={zone_id}")

    # ========== Comfort Settings ==========

    def get_comfort_presets(self, season: str = "winter") -> list[dict]:
        """
        Get comfort setting presets for a season.

        Args:
            season: "winter" or "summer"

        Returns:
            List of comfort presets
        """
        return self._request("GET", f"/v3/comfort-settings/presets?season={season}")

    # ========== Account Methods ==========

    def update_preferences(self, preferences: dict) -> dict:
        """
        Update user account preferences.

        Args:
            preferences: Dict of preferences to update. Keys include:
                - celsius: bool - Use Celsius vs Fahrenheit
                - scheduleFeatureModalSeen: bool
                - scheduleDuplicationModalSeen: bool
                - hideDashboardWelcomeSteps: bool
                - isMinMaxSetpointsEnabled: bool
                - weatherVisibility: dict

        Returns:
            Updated preferences
        """
        return self._request("PUT", "/v3/accounts/preferences", json_data=preferences)

    # ========== Notifications ==========

    def get_unseen_notification_count(self) -> int:
        """Get count of unseen notifications."""
        result = self._request("GET", "/v3/notifications/unseen-count")
        return result.get("count", 0)

    # ========== Site Methods (Extended) ==========

    def get_sites_full(self) -> list[dict]:
        """Get all sites with additional details."""
        return self._request("GET", "/v3/sites/full")

    def get_pending_transfers(self) -> list[dict]:
        """Get pending site transfers."""
        return self._request("GET", "/v3/sites/transfers/pending")

    def get_preferable_contractor(self, site_id: str) -> dict:
        """Get contractor information for a site."""
        return self._request("GET", f"/v3/site/{site_id}/preferable-contractor")

    def print_status(self, verbose: bool = False, refresh: bool = False) -> None:
        """Print status of all devices to console.

        Args:
            verbose: If True, fetch full device data and show additional info (RSSI, MHK2, fan, vane, etc.)
            refresh: If True, use Socket.IO to force devices to report fresh status.
                     This bypasses server cache and gets actual current values.
        """
        print("\n" + "=" * 70)
        if refresh:
            print("KUMO CLOUD DEVICE STATUS (REFRESHED)")
        else:
            print("KUMO CLOUD DEVICE STATUS")
        print("=" * 70)

        # Use configured site_id or fetch all sites
        if self.site_id:
            sites = [{"id": self.site_id, "name": "My Home"}]
        else:
            sites = self.get_sites()

        for site in sites:
            print(f"\nSite: {site['name']}")
            print("-" * 50)

            zones = self.get_zones(site["id"])
            for zone in zones:
                adapter = zone.get("adapter", {})
                device_serial = adapter.get("deviceSerial")

                if not device_serial:
                    continue

                # Use Socket.IO refresh if requested (gets fresh data from device)
                if refresh:
                    fresh_data = self.force_device_refresh(device_serial)
                    if fresh_data:
                        merged_data = {**adapter, **fresh_data}
                    elif verbose:
                        device_data = self.get_device(device_serial)
                        merged_data = {**adapter, **device_data}
                    else:
                        merged_data = adapter
                # Fetch full device data if verbose (includes fan/vane)
                elif verbose:
                    device_data = self.get_device(device_serial)
                    merged_data = {**adapter, **device_data}
                else:
                    merged_data = adapter

                device = self._parse_device_status(
                    device_serial,
                    zone.get("name", "Unknown"),
                    merged_data,
                )
                print(f"  {device}")

                if verbose:
                    # Show additional info on second line
                    extras = []
                    if device.rssi is not None:
                        extras.append(f"RSSI: {device.rssi}dBm")
                    if device.has_mhk2:
                        extras.append("MHK2: Yes")
                    if device.has_sensor:
                        extras.append("Sensor: Yes")
                    if device.schedule_owner:
                        extras.append(f"Schedule: {device.schedule_owner}")
                    if device.sp_cool is not None and device.sp_heat is not None:
                        extras.append(f"Setpoints: Cool={device.sp_cool:.0f}F Heat={device.sp_heat:.0f}F")
                    if extras:
                        print(f"    [{', '.join(extras)}]")

        print("\n" + "=" * 70)

    def close(self) -> None:
        """Close the HTTP client and Socket.IO connection."""
        self._disconnect_socketio()
        self._client.close()

    def __enter__(self) -> "KumoCloudClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ========== CLI Interface ==========

def main():
    """Command-line interface for Kumo Cloud client."""
    import argparse
    import os
    import getpass

    parser = argparse.ArgumentParser(
        description="Kumo Cloud API Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                      Show status of all devices
  %(prog)s status -r                   Show status with fresh data from devices
  %(prog)s status -v -r                Verbose + fresh data (most accurate)
  %(prog)s status -d SERIAL            Show status of specific device
  %(prog)s set-temp upstairs 72        Set temperature to 72F
  %(prog)s set-temp upstairs 72 -m cool Set cooling to 72F
  %(prog)s set-mode downstairs heat    Set mode to heat
  %(prog)s set-fan upstairs quiet      Set fan to quiet
  %(prog)s set-vane upstairs swing     Set vane to swing
  %(prog)s turn-off upstairs           Turn off device
  %(prog)s check                       Verify each adapter is really online
  %(prog)s raw sites                   Show raw API response for sites
  %(prog)s raw zones                   Show raw zones for configured site
  %(prog)s raw device-status SERIAL    Show raw device status
  %(prog)s raw weather                 Show weather for configured site
  %(prog)s raw config                  Show service configuration
  %(prog)s raw device-limits upstairs   Show allowed setpoint range

Note: Use -r/--refresh to get accurate real-time data from devices.
      Without it, the API may return cached/stale values.
      Requires: pip install python-socketio[client]
        """,
    )

    parser.add_argument(
        "-u", "--username",
        help="Kumo Cloud username (or set KUMO_USERNAME env var)",
        default=os.environ.get("KUMO_USERNAME"),
    )
    parser.add_argument(
        "-p", "--password",
        help="Kumo Cloud password (or set KUMO_PASSWORD env var)",
        default=os.environ.get("KUMO_PASSWORD"),
    )
    parser.add_argument(
        "--token-file",
        help="Path to token cache file",
        type=Path,
        default=TOKEN_FILE,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Login command
    login_parser = subparsers.add_parser("login", help="Login and cache tokens")

    # Status command
    status_parser = subparsers.add_parser("status", help="Show device status")
    status_parser.add_argument(
        "-d", "--device",
        help="Specific device serial (optional)",
    )
    status_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show additional device info (RSSI, MHK2, etc.)",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    status_parser.add_argument(
        "-r", "--refresh",
        action="store_true",
        help="Force refresh from devices via Socket.IO (bypasses server cache, requires python-socketio)",
    )

    # Set temperature command
    set_temp_parser = subparsers.add_parser("set-temp", help="Set target temperature")
    set_temp_parser.add_argument("device", help="Device serial or name (e.g., 'upstairs', 'downstairs')")
    set_temp_parser.add_argument("temp", type=float, help="Target temperature (F)")
    set_temp_parser.add_argument(
        "-m", "--mode",
        choices=["cool", "heat", "auto"],
        help="Mode to use",
    )

    # Set mode command
    set_mode_parser = subparsers.add_parser("set-mode", help="Set operating mode")
    set_mode_parser.add_argument("device", help="Device serial or name (e.g., 'upstairs', 'downstairs')")
    set_mode_parser.add_argument(
        "mode",
        choices=["off", "cool", "heat", "dry", "fan", "auto"],
        help="Operating mode",
    )

    # Turn on/off commands
    on_parser = subparsers.add_parser("turn-on", help="Turn on device")
    on_parser.add_argument("device", help="Device serial or name (e.g., 'upstairs', 'downstairs')")

    off_parser = subparsers.add_parser("turn-off", help="Turn off device")
    off_parser.add_argument("device", help="Device serial or name (e.g., 'upstairs', 'downstairs')")

    # Set fan speed command
    fan_parser = subparsers.add_parser("set-fan", help="Set fan speed")
    fan_parser.add_argument("device", help="Device serial or name (e.g., 'upstairs', 'downstairs')")
    fan_parser.add_argument(
        "speed",
        choices=["superQuiet", "quiet", "low", "powerful", "superPowerful", "auto"],
        help="Fan speed",
    )

    # Set air direction command
    vane_parser = subparsers.add_parser("set-vane", help="Set air direction (vane)")
    vane_parser.add_argument("device", help="Device serial or name (e.g., 'upstairs', 'downstairs')")
    vane_parser.add_argument(
        "direction",
        choices=["auto", "horizontal", "midhorizontal", "midpoint", "midvertical", "vertical", "swing"],
        help="Air direction",
    )

    # Raw API command
    raw_parser = subparsers.add_parser("raw", help="Raw API calls")
    raw_parser.add_argument(
        "endpoint",
        choices=[
            "account", "config", "sites", "zones", "groups", "device",
            "device-status", "device-profile", "device-limits", "device-props", "weather",
        ],
        help="API endpoint to call",
    )
    raw_parser.add_argument(
        "id",
        nargs="?",
        help="Site ID or Device Serial (depending on endpoint)",
    )

    # Check command (reachability)
    check_parser = subparsers.add_parser(
        "check",
        help="Check whether each adapter is really online (Socket.IO device_status_v2)",
    )
    check_parser.add_argument(
        "-d", "--device",
        help="Specific device name or serial (default: all configured devices)",
    )
    check_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # List command (alias for status)
    list_parser = subparsers.add_parser("list", help="List all devices")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Get credentials
    username = args.username
    password = args.password

    if args.command == "login" or (not TOKEN_FILE.exists() and not (username and password)):
        if not username:
            username = input("Kumo Cloud Username: ")
        if not password:
            password = getpass.getpass("Kumo Cloud Password: ")

    try:
        with KumoCloudClient(
            username=username,
            password=password,
            token_file=args.token_file,
        ) as client:

            if args.command == "login":
                result = client.login()
                print(f"Logged in as: {result.get('email')}")
                print(f"Tokens cached to: {args.token_file}")

            elif args.command in ("status", "list"):
                refresh = getattr(args, 'refresh', False)
                if hasattr(args, 'device') and args.device:
                    # For specific device, use refresh if requested
                    if refresh:
                        status = client.get_fresh_device_status(args.device)
                    else:
                        status = client.get_device_status(args.device)
                    if getattr(args, 'json', False):
                        print(json.dumps(status, indent=2))
                    else:
                        print(json.dumps(status, indent=2))
                else:
                    if getattr(args, 'json', False):
                        devices = client.get_all_devices(refresh=refresh)
                        print(json.dumps([d.raw_data for d in devices], indent=2))
                    else:
                        verbose = getattr(args, 'verbose', False)
                        client.print_status(verbose=verbose, refresh=refresh)

            elif args.command == "check":
                if args.device:
                    serials = [client.get_serial_by_name(args.device) or args.device]
                else:
                    serials = list(client.device_serials.values())
                    if not serials:
                        serials = [
                            z.get("adapter", {}).get("deviceSerial")
                            for z in client.get_zones(client.site_id)
                        ]
                        serials = [s for s in serials if s]

                statuses = client.get_reachability(serials)
                if args.json:
                    print(json.dumps(statuses, indent=2))
                elif not statuses:
                    print(
                        "No reachability data. Socket.IO is required: "
                        "pip install python-socketio[client]"
                    )
                else:
                    names = {v: k for k, v in client.device_serials.items()}
                    for serial in serials:
                        info = statuses.get(serial)
                        label = names.get(serial, serial)
                        if not info:
                            print(f"  {label:<12} UNKNOWN (no reply from cloud)")
                            continue
                        state = info.get("status", "unknown").upper()
                        extra = ""
                        if state != "CONNECTED":
                            extra = (
                                f" since {info.get('lastTimeDisconnected')} "
                                f"(reason: {info.get('lastDisconnectedReason')})"
                            )
                        if info.get("hasIduCommunicationError") == "true":
                            extra += " [indoor unit communication error]"
                        print(f"  {label:<12} {state}{extra}")

            elif args.command == "set-temp":
                # Resolve device name to serial if needed
                device_serial = client.get_serial_by_name(args.device) or args.device
                result = client.set_temperature(device_serial, args.temp, args.mode)
                print(f"Temperature set to {args.temp}F for {args.device}")
                if result:
                    print(json.dumps(result, indent=2))

            elif args.command == "set-mode":
                device_serial = client.get_serial_by_name(args.device) or args.device
                result = client.set_mode(device_serial, args.mode)
                print(f"Mode set to {args.mode} for {args.device}")
                if result:
                    print(json.dumps(result, indent=2))

            elif args.command == "turn-on":
                device_serial = client.get_serial_by_name(args.device) or args.device
                result = client.turn_on(device_serial)
                print(f"Device {args.device} turned on")

            elif args.command == "turn-off":
                device_serial = client.get_serial_by_name(args.device) or args.device
                result = client.turn_off(device_serial)
                print(f"Device {args.device} turned off")

            elif args.command == "set-fan":
                device_serial = client.get_serial_by_name(args.device) or args.device
                result = client.set_fan_speed(device_serial, args.speed)
                print(f"Fan speed set to {args.speed} for {args.device}")
                if result:
                    print(json.dumps(result, indent=2))

            elif args.command == "set-vane":
                device_serial = client.get_serial_by_name(args.device) or args.device
                result = client.set_air_direction(device_serial, args.direction)
                print(f"Air direction set to {args.direction} for {args.device}")
                if result:
                    print(json.dumps(result, indent=2))

            elif args.command == "raw":
                if args.endpoint == "account":
                    result = client.get_account()
                elif args.endpoint == "config":
                    result = client.get_config()
                elif args.endpoint == "sites":
                    result = client.get_sites()
                elif args.endpoint == "zones":
                    site_id = args.id or client.site_id
                    if not site_id:
                        print("Error: Site ID required for zones endpoint (set KUMO_SITE_ID or provide as argument)")
                        return
                    result = client.get_zones(site_id)
                elif args.endpoint == "groups":
                    site_id = args.id or client.site_id
                    if not site_id:
                        print("Error: Site ID required for groups endpoint (set KUMO_SITE_ID or provide as argument)")
                        return
                    result = client.get_groups(site_id)
                elif args.endpoint == "device":
                    if not args.id:
                        print("Error: Device serial required")
                        return
                    result = client.get_device(args.id)
                elif args.endpoint == "device-status":
                    if not args.id:
                        print("Error: Device serial required")
                        return
                    result = client.get_device_status(args.id)
                elif args.endpoint == "device-profile":
                    if not args.id:
                        print("Error: Device serial required")
                        return
                    result = client.get_device_profile(args.id)
                elif args.endpoint == "device-limits":
                    if not args.id:
                        print("Error: Device serial required")
                        return
                    serial = client.get_serial_by_name(args.id) or args.id
                    result = client.get_device_limits(serial)
                elif args.endpoint == "device-props":
                    if not args.id:
                        print("Error: Device serial required")
                        return
                    result = client.get_device_kumo_properties(args.id)
                elif args.endpoint == "weather":
                    site_id = args.id or client.site_id
                    if not site_id:
                        print("Error: Site ID required for weather endpoint (set KUMO_SITE_ID or provide as argument)")
                        return
                    result = client.get_weather(site_id)

                print(json.dumps(result, indent=2))

    except AuthenticationError as e:
        print(f"Authentication error: {e}")
        print("Try running: python app.py login")
        exit(1)
    except KumoCloudError as e:
        print(f"API error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
