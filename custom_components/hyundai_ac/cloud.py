"""Hyundai AC cloud bootstrap client.

The cloud API is only used during setup to fetch the LAN MAC and AES key.
Runtime control stays local over UDP.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .protocol import find_device_host, normalize_mac

ACCOUNT_BODY_SALT = "xgx3d*fe3478$ukx"
ACCOUNT_TOKEN_SALT = "kdixkdqp54545^#*"
ACCOUNT_PASSWORD_SALT = "4969fj#k23#"
FAMILY_TOKEN_SALT = "xgx3d*fe3478$ukx"
REQUEST_IV = bytes.fromhex("eaaaaa3abb5862a21918b5771d1615aa")
TIMEOUT = 30
APP_VERSION = "1.0.12"

KNOWN_AC_PIDS = {
    "0000000000000000000000007c500000",
    "0000000000000000000000007a500000",
    "0000000000000000000000007b500000",
    "00000000000000000000000008510000",
    "000000000000000000000000d9500000",
    "000000000000000000000000da500000",
    "000000000000000000000000db500000",
    "00000000000000000000000009510000",
    "000000000000000000000000d3500000",
    "000000000000000000000000d4500000",
    "000000000000000000000000d5500000",
    "0000000000000000000000000b510000",
    "0000000000000000000000002e4e0000",
}


@dataclass(frozen=True)
class CloudRegion:
    """BroadLink app-service region metadata decoded from the APK licenses."""

    label: str
    license_id: str
    company_id: str
    app_host: str | None = None

    @property
    def base_url(self) -> str:
        return f"https://{self.license_id}appservice.ibroadlink.com"

    @property
    def base_urls(self) -> tuple[str, ...]:
        urls = [self.base_url]
        if self.app_host:
            urls.append(f"https://{self.app_host}")
        return tuple(dict.fromkeys(urls))


CLOUD_REGIONS = {
    "us": CloudRegion(
        label="United States / Other",
        license_id="f6e9e21566e109a28797aba5a1d8ed7e",
        company_id="8503b08fa57729df9faa45e4c978852c",
        app_host="app-service-usa-c5784334.ibroadlink.com",
    ),
    "eu": CloudRegion(
        label="Europe",
        license_id="aae72184369e2fc3e6ded53a90612586",
        company_id="57c9e5adbc9e118372539cd8f26e1239",
        app_host="app-service-deu-a00df8b5.ibroadlink.com",
    ),
    "cn": CloudRegion(
        label="China",
        license_id="bffd4d702ec53938c31eb10cc0194b4a",
        company_id="b8671d5c011bababdb6b0689c70ab656",
        app_host="app-service-chn-31a93883.ibroadlink.com",
    ),
    "ru": CloudRegion(
        label="Russia",
        license_id="e60de87565166c447a90cee96da955f7",
        company_id="5647794ded8bbc67df65ff2bd7d0fb03",
    ),
}


@dataclass(frozen=True)
class CloudDevice:
    """Device details needed for local setup."""

    name: str
    host: str
    mac: str
    key: str
    did: str | None = None
    pid: str | None = None

    def as_config(self) -> dict[str, str]:
        data = {
            "name": self.name,
            "host": self.host,
            "mac": self.mac,
            "key": self.key,
        }
        if self.did:
            data["did"] = self.did
        if self.pid:
            data["pid"] = self.pid
        return data


class HyundaiCloudError(Exception):
    """Raised when the Hyundai/BroadLink cloud bootstrap fails."""


class HyundaiCloudAuthError(HyundaiCloudError):
    """Raised when the cloud rejects the account credentials."""


class HyundaiCloudRateLimitError(HyundaiCloudError):
    """Raised when the cloud temporarily blocks login attempts."""


class HyundaiCloudClient:
    """Small synchronous client for the Intelligent AC setup API."""

    def __init__(self, region_key: str = "us") -> None:
        try:
            self.region = CLOUD_REGIONS[region_key]
        except KeyError as exc:
            raise HyundaiCloudError(f"Unsupported region: {region_key}") from exc
        self.userid: str | None = None
        self.loginsession: str | None = None
        self._family_timestamp: int | None = None
        self._family_key: str | None = None
        self._base_url = self.region.base_url

    def login(self, username: str, password: str) -> None:
        """Authenticate with a Hyundai AC account."""

        last_error: HyundaiCloudError | None = None
        for base_url in self.region.base_urls:
            self._base_url = base_url
            try:
                self._login(username, password)
            except HyundaiCloudAuthError:
                raise
            except HyundaiCloudError as exc:
                last_error = exc
            else:
                return

        if last_error:
            raise last_error
        raise HyundaiCloudError("No cloud API host was configured for this region")

    def _login(self, username: str, password: str) -> None:
        """Authenticate with one region API host."""

        username = username.strip()
        password = password.strip()
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", username):
            identity_key = "email"
        elif username.isdigit():
            identity_key = "phone"
        else:
            raise HyundaiCloudError("Username must be an email address or phone number")

        body = {
            identity_key: username,
            "password": _sha1(password + ACCOUNT_PASSWORD_SALT),
            "companyid": self.region.company_id,
            "lid": self.region.license_id,
        }
        body_json = _json_dumps(body)
        timestamp = str(int(time.time()))
        key = bytes.fromhex(_md5(timestamp + ACCOUNT_TOKEN_SALT))
        headers = {
            "timestamp": timestamp,
            "token": _md5(body_json + ACCOUNT_BODY_SALT),
            "lid": self.region.license_id,
            "licenseId": self.region.license_id,
            identity_key: username,
        }

        response = self._post("/account/login", headers, _encrypt(body_json.encode(), key))
        _ensure_ok(response, "login")

        self.userid = response.get("userid")
        self.loginsession = response.get("loginsession")
        if not self.userid or not self.loginsession:
            raise HyundaiCloudError("Login response did not include a user session")

    def get_devices(self) -> list[CloudDevice]:
        """Fetch cloud devices and resolve their current LAN hosts."""

        if not self.userid or not self.loginsession:
            raise HyundaiCloudError("Not logged in")

        family_ids = self._get_family_ids()
        if not family_ids:
            return []

        all_info = self._family_post(
            "/ec4/v1/family/getallinfo",
            {"userid": self.userid, "familyid": family_ids},
        )
        devices = _parse_devices(all_info)

        resolved: list[CloudDevice] = []
        for device in devices:
            host = find_device_host(device.mac, device.key, seed_hosts=[device.host] if device.host else None)
            resolved.append(
                CloudDevice(
                    name=device.name,
                    host=host or device.host,
                    mac=device.mac,
                    key=device.key,
                    did=device.did,
                    pid=device.pid,
                )
            )
        return resolved

    def _get_family_ids(self) -> list[str]:
        response = self._family_post("/ec4/v1/user/getfamilyid", {"userid": self.userid})
        family_info = response.get("familyinfo") or []
        return [str(item["id"]) for item in family_info if item.get("id")]

    def _family_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.userid or not self.loginsession:
            raise HyundaiCloudError("Not logged in")
        if not self._family_key or not self._family_timestamp:
            self._refresh_family_key()

        body_json = _json_dumps(body)
        timestamp = str(self._family_timestamp)
        headers = {
            "timestamp": timestamp,
            "token": _md5(body_json + FAMILY_TOKEN_SALT + timestamp + self.userid),
            "userid": self.userid,
            "loginsession": self.loginsession,
            "licenseid": self.region.license_id,
            "lid": self.region.license_id,
        }
        response = self._post(path, headers, _encrypt(body_json.encode(), bytes.fromhex(self._family_key)))
        _ensure_ok(response, path)
        return response

    def _refresh_family_key(self) -> None:
        response = self._get("/ec4/v1/common/api")
        _ensure_ok(response, "family key")
        key = response.get("key")
        timestamp = response.get("timestamp")
        if not key or not timestamp:
            raise HyundaiCloudError("Family API key response was incomplete")
        self._family_key = str(key)
        self._family_timestamp = int(timestamp)

    def _get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self._base_url + path, headers=_common_headers())
        return _open_json(request)

    def _post(self, path: str, headers: dict[str, str], data: bytes) -> dict[str, Any]:
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers=_common_headers(headers),
            method="POST",
        )
        return _open_json(request)


def get_cloud_devices(username: str, password: str, region: str) -> list[CloudDevice]:
    """Log in once and return devices ready for local control."""

    client = HyundaiCloudClient(region)
    client.login(username, password)
    return client.get_devices()


def _parse_devices(response: dict[str, Any]) -> list[CloudDevice]:
    devices: list[CloudDevice] = []
    seen: set[str] = set()

    for family in response.get("familyallinfo") or []:
        module_names = _module_names_by_did(family)
        for field in ("devinfo", "subdevinfo"):
            for raw in family.get(field) or []:
                pid = str(raw.get("pid") or "").lower()
                if pid and pid not in KNOWN_AC_PIDS:
                    continue

                mac = raw.get("mac") or raw.get("wifimac")
                key = str(raw.get("aeskey") or "").lower()
                if not mac or not re.match(r"^[0-9a-f]{32}$", key):
                    continue

                try:
                    normalized_mac = normalize_mac(str(mac))
                except ValueError:
                    continue
                if normalized_mac in seen:
                    continue
                seen.add(normalized_mac)

                devices.append(
                    CloudDevice(
                        name=_device_name(raw, module_names, normalized_mac),
                        host=str(raw.get("lanaddr") or raw.get("host") or ""),
                        mac=normalized_mac,
                        key=key,
                        did=raw.get("did"),
                        pid=pid or None,
                    )
                )

    return devices


def _module_names_by_did(family: dict[str, Any]) -> dict[str, str]:
    """Return app-visible module names keyed by device IDs.

    Intelligent AC displays devices through BroadLink family modules. The
    physical device record can keep the Wi-Fi module name (for example
    ``OEM_TCLISO_...``), while the user-facing name is stored on moduleinfo.
    """

    names: dict[str, str] = {}
    for module in family.get("moduleinfo") or []:
        name = _clean_name(module.get("name"))
        if not name:
            continue

        for module_device in module.get("moduledev") or []:
            did = _clean_name(module_device.get("did"))
            if did:
                names.setdefault(did, name)
    return names


def _device_name(raw: dict[str, Any], module_names: dict[str, str], fallback: str) -> str:
    did = _clean_name(raw.get("did"))
    if did and did in module_names:
        return module_names[did]
    return _clean_name(raw.get("name")) or fallback


def _clean_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _common_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    now_ms = int(time.time() * 1000)
    headers = {
        "system": "android",
        "appPlatform": "android",
        "language": "en-us",
        "timestamp": str(now_ms // 1000),
        "appVersion": APP_VERSION,
        "messageId": str(now_ms),
        "Content-type": "application/x-java-serialized-object",
    }
    if extra:
        headers.update(extra)
    return headers


def _open_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        raise HyundaiCloudError(f"Cloud HTTP {exc.code} from {request.full_url}: {raw[:200]}") from exc
    except urllib.error.URLError as exc:
        raise HyundaiCloudError(f"Cloud request failed for {request.full_url}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HyundaiCloudError(f"Cloud returned invalid JSON: {raw[:120]}") from exc
    if not isinstance(data, dict):
        raise HyundaiCloudError("Cloud returned an unexpected response")
    return data


def _ensure_ok(response: dict[str, Any], action: str) -> None:
    error = response.get("error", response.get("status", 0))
    if error not in (0, "0", None):
        message = response.get("msg") or response.get("message") or "unknown error"
        if action == "login" and str(error) == "-1036":
            raise HyundaiCloudRateLimitError(f"{action} failed: too many attempts ({error})")
        if action == "login" and str(error) == "-1008":
            raise HyundaiCloudAuthError(f"{action} failed: invalid username or password ({error})")
        raise HyundaiCloudError(f"{action} failed: {message} ({error})")


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _encrypt(data: bytes, key: bytes) -> bytes:
    pad_len = (16 - (len(data) % 16)) % 16
    padded = data + (b"\x00" * pad_len)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(REQUEST_IV)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()  # noqa: S324


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()  # noqa: S324
