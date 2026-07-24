"""Config flow for Hyundai AC."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .cloud import (
    CLOUD_REGIONS,
    CloudDevice,
    HyundaiCloudAuthError,
    HyundaiCloudError,
    HyundaiCloudRateLimitError,
    get_cloud_devices,
)
from .const import CONF_DEVICE_ID, CONF_DEVICES, CONF_DEVTYPE, CONF_KEY, CONF_MAC, DOMAIN
from .protocol import DEFAULT_DEVICE_TYPE
from .protocol import (
    HyundaiAcClient,
    HyundaiAcDevice,
    HyundaiAcDiscovery,
    HyundaiAcLockedError,
    authenticate_tcl_ac_device,
    discover_tcl_ac_devices,
)

CONF_REGION = "region"
CONF_SCAN_SUBNET = "scan_subnet"
CONF_SELECTION = "selection"
CONF_SETUP_METHOD = "setup_method"
CONF_SEED_HOSTS = "seed_hosts"
SETUP_METHOD_CLOUD = "cloud"
SETUP_METHOD_LOCAL_DISCOVERY = "local_discovery"
SETUP_METHOD_MANUAL = "manual"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalDiscoveryResult:
    """Devices found through LAN discovery, grouped by setup outcome."""

    devices: list[dict[str, Any]]
    locked_devices: list[HyundaiAcDiscovery]


def _mac_unique_id(mac: str) -> str:
    return mac.replace(":", "").replace("-", "").lower()


def _manual_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_MAC, default=defaults.get(CONF_MAC, "")): str,
            vol.Required(CONF_KEY, default=defaults.get(CONF_KEY, "")): str,
        }
    )


def _cloud_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_REGION, default=defaults.get(CONF_REGION, "us")): vol.In(
                {key: region.label for key, region in CLOUD_REGIONS.items()}
            ),
        }
    )


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SETUP_METHOD,
                default=defaults.get(CONF_SETUP_METHOD, SETUP_METHOD_LOCAL_DISCOVERY),
            ): vol.In(
                {
                    SETUP_METHOD_LOCAL_DISCOVERY: "Local discovery (recommended)",
                    SETUP_METHOD_CLOUD: "Cloud-assisted setup",
                    SETUP_METHOD_MANUAL: "Manual setup",
                }
            )
        }
    )


def _local_discovery_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(CONF_SEED_HOSTS, default=defaults.get(CONF_SEED_HOSTS, "")): str,
            vol.Required(CONF_SCAN_SUBNET, default=defaults.get(CONF_SCAN_SUBNET, True)): bool,
        }
    )


def _device_mac(device: CloudDevice | dict[str, Any]) -> str:
    if isinstance(device, dict):
        return str(device[CONF_MAC])
    return device.mac


def _device_name(device: CloudDevice | dict[str, Any]) -> str:
    if isinstance(device, dict):
        return str(device[CONF_NAME])
    return device.name


def _device_host(device: CloudDevice | dict[str, Any]) -> str:
    if isinstance(device, dict):
        return str(device.get(CONF_HOST) or "")
    return device.host


def _select_schema(devices: list[CloudDevice] | list[dict[str, Any]]) -> vol.Schema:
    options = {
        _device_mac(device): (
            f"{_device_name(device)} ({_device_mac(device)}"
            f"{', ' + _device_host(device) if _device_host(device) else ', host not found'})"
        )
        for device in devices
    }
    return vol.Schema({vol.Required(CONF_SELECTION, default=list(options)): cv.multi_select(options)})


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    client = HyundaiAcClient(
        HyundaiAcDevice(
            host=data[CONF_HOST],
            mac=data[CONF_MAC],
            key=data[CONF_KEY],
            devtype=int(data.get(CONF_DEVTYPE, DEFAULT_DEVICE_TYPE)),
            device_id=int(data.get(CONF_DEVICE_ID, 1)),
        )
    )
    await hass.async_add_executor_job(client.get_state)


async def _validate_devices(hass: HomeAssistant, devices: list[dict[str, Any]]) -> None:
    for device in devices:
        if not device.get(CONF_HOST):
            raise HyundaiCloudError("Could not find the device host on the LAN")
        await _validate_input(hass, device)


def _configured_macs(hass: HomeAssistant) -> set[str]:
    macs: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if CONF_DEVICES in entry.data:
            macs.update(_mac_unique_id(device[CONF_MAC]) for device in entry.data[CONF_DEVICES])
        elif entry.data.get(CONF_MAC):
            macs.add(_mac_unique_id(entry.data[CONF_MAC]))
    return macs


def _filter_unconfigured_devices(hass: HomeAssistant, devices: list[Any]) -> list[Any]:
    """Return only devices that are not already configured.

    If discovery finds an existing device at a new host, keep the stored entry
    current while hiding it from the "devices to add" selection screen.
    """

    configured_macs = _configured_macs(hass)
    filtered: list[Any] = []
    seen_macs: set[str] = set()

    for device in devices:
        mac = _device_mac(device)
        unique_mac = _mac_unique_id(mac)
        if unique_mac in seen_macs:
            continue
        seen_macs.add(unique_mac)

        if unique_mac in configured_macs:
            if host := _device_host(device):
                _update_configured_host(hass, mac, host)
            continue

        filtered.append(device)

    return filtered


def _update_configured_host(hass: HomeAssistant, mac: str, host: str) -> bool:
    """Update a configured device host if the device is already configured."""

    target_mac = _mac_unique_id(mac)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if CONF_DEVICES in entry.data:
            changed = False
            devices: list[dict[str, Any]] = []
            found = False
            for device in entry.data[CONF_DEVICES]:
                updated = dict(device)
                if _mac_unique_id(updated[CONF_MAC]) == target_mac:
                    found = True
                    if updated.get(CONF_HOST) != host:
                        updated[CONF_HOST] = host
                        changed = True
                devices.append(updated)

            if found:
                if changed:
                    data = dict(entry.data)
                    data[CONF_DEVICES] = devices
                    hass.config_entries.async_update_entry(entry, data=data)
                return True

        elif entry.data.get(CONF_MAC) and _mac_unique_id(entry.data[CONF_MAC]) == target_mac:
            if entry.data.get(CONF_HOST) != host:
                data = dict(entry.data)
                data[CONF_HOST] = host
                hass.config_entries.async_update_entry(entry, data=data)
            return True

    return False


def _devices_unique_id(devices: list[dict[str, Any]], prefix: str) -> str:
    macs = ",".join(sorted(_mac_unique_id(device[CONF_MAC]) for device in devices))
    return prefix + "_" + hashlib.sha1(macs.encode()).hexdigest()[:16]  # noqa: S324


def _parse_seed_hosts(raw_hosts: str) -> list[str]:
    return [host for host in re.split(r"[\s,;]+", raw_hosts.strip()) if host]


def _locked_device_summary(devices: list[HyundaiAcDiscovery]) -> str:
    return ", ".join(f"{device.name} ({device.mac}, {device.host})" for device in devices)


def _accountless_device_configs(seed_hosts: list[str], scan_subnet: bool) -> LocalDiscoveryResult:
    devices: list[dict[str, Any]] = []
    locked_devices: list[HyundaiAcDiscovery] = []

    for discovery in discover_tcl_ac_devices(
        seed_hosts=seed_hosts,
        scan_subnet=scan_subnet,
    ):
        try:
            auth = authenticate_tcl_ac_device(discovery)
            client = HyundaiAcClient(
                HyundaiAcDevice(
                    host=discovery.host,
                    mac=discovery.mac,
                    key=auth.key,
                    devtype=discovery.devtype,
                    device_id=auth.device_id,
                )
            )
            client.get_state()
        except HyundaiAcLockedError:
            locked_devices.append(discovery)
            continue
        except Exception:  # noqa: BLE001
            continue

        devices.append(
            {
                CONF_NAME: discovery.name,
                CONF_HOST: discovery.host,
                CONF_MAC: discovery.mac,
                CONF_KEY: auth.key,
                CONF_DEVTYPE: discovery.devtype,
                CONF_DEVICE_ID: auth.device_id,
            }
        )

    return LocalDiscoveryResult(devices=devices, locked_devices=locked_devices)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hyundai AC."""

    VERSION = 1

    def __init__(self) -> None:
        self._cloud_devices: list[CloudDevice] = []
        self._discovered_device: dict[str, Any] | None = None
        self._local_devices: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""

        if user_input is not None:
            if user_input[CONF_SETUP_METHOD] == SETUP_METHOD_MANUAL:
                return await self.async_step_manual()
            if user_input[CONF_SETUP_METHOD] == SETUP_METHOD_LOCAL_DISCOVERY:
                return await self.async_step_local_discovery()
            return await self.async_step_cloud()

        return self.async_show_form(step_id="user", data_schema=_user_schema(user_input), errors={})

    async def async_step_dhcp(self, discovery_info: Any) -> config_entries.ConfigFlowResult:
        """Handle DHCP discovery."""

        host = getattr(discovery_info, "ip", None)
        if not host:
            return self.async_abort(reason="not_supported")

        result = await self.hass.async_add_executor_job(
            _accountless_device_configs,
            [str(host)],
            False,
        )
        devices = result.devices
        if not devices:
            if result.locked_devices:
                for locked_device in result.locked_devices:
                    if _update_configured_host(self.hass, locked_device.mac, locked_device.host):
                        return self.async_abort(reason="already_configured")
                _LOGGER.warning(
                    "Hyundai AC DHCP discovery found locked devices: %s",
                    _locked_device_summary(result.locked_devices),
                )
                return self.async_abort(reason="locked_device")
            return self.async_abort(reason="not_supported")

        device = devices[0]
        if _update_configured_host(self.hass, device[CONF_MAC], device[CONF_HOST]):
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(_mac_unique_id(device[CONF_MAC]))
        self._abort_if_unique_id_configured(updates={CONF_HOST: device[CONF_HOST]})
        self._discovered_device = device
        self.context["title_placeholders"] = {
            CONF_NAME: device[CONF_NAME],
            CONF_HOST: device[CONF_HOST],
        }
        return await self.async_step_dhcp_confirm()

    async def async_step_dhcp_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm a DHCP-discovered device."""

        if self._discovered_device is None:
            return self.async_abort(reason="not_supported")

        errors: dict[str, str] = {}

        if user_input is not None:
            device = self._discovered_device
            await self.async_set_unique_id(_mac_unique_id(device[CONF_MAC]))
            self._abort_if_unique_id_configured(updates={CONF_HOST: device[CONF_HOST]})
            try:
                await _validate_devices(self.hass, [device])
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=device[CONF_NAME],
                    data={CONF_DEVICES: [device]},
                )

        return self.async_show_form(
            step_id="dhcp_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                CONF_NAME: self._discovered_device[CONF_NAME],
                CONF_HOST: self._discovered_device[CONF_HOST],
                CONF_MAC: self._discovered_device[CONF_MAC],
            },
        )

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle cloud-assisted device discovery."""

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                cloud_devices = await self.hass.async_add_executor_job(
                    get_cloud_devices,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_REGION],
                )
            except HyundaiCloudRateLimitError as exc:
                _LOGGER.warning("Hyundai AC cloud temporarily blocked login attempts: %s", exc)
                errors["base"] = "too_many_attempts"
            except HyundaiCloudAuthError as exc:
                _LOGGER.warning("Hyundai AC cloud rejected the credentials: %s", exc)
                errors["base"] = "invalid_auth"
            except HyundaiCloudError as exc:
                _LOGGER.warning("Hyundai AC cloud setup failed: %s", exc)
                errors["base"] = "cloud_error"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected Hyundai AC cloud setup error")
                errors["base"] = "cloud_error"
            else:
                if not cloud_devices:
                    errors["base"] = "no_devices"
                else:
                    self._cloud_devices = _filter_unconfigured_devices(self.hass, cloud_devices)
                    if not self._cloud_devices:
                        errors["base"] = "all_devices_configured"
                    else:
                        return await self.async_step_select()

        return self.async_show_form(step_id="cloud", data_schema=_cloud_schema(user_input), errors=errors)

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Let the user choose cloud-discovered devices."""

        errors: dict[str, str] = {}

        if user_input is not None:
            selected_macs = set(user_input.get(CONF_SELECTION) or [])
            selected = [device.as_config() for device in self._cloud_devices if device.mac in selected_macs]
            if not selected:
                errors["base"] = "no_devices_selected"
            elif _configured_macs(self.hass).intersection(_mac_unique_id(device[CONF_MAC]) for device in selected):
                errors["base"] = "already_configured"
            else:
                try:
                    await _validate_devices(self.hass, selected)
                except HyundaiCloudError:
                    errors["base"] = "host_not_found"
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"
                else:
                    title = selected[0][CONF_NAME] if len(selected) == 1 else f"Hyundai AC ({len(selected)} devices)"
                    await self.async_set_unique_id(_devices_unique_id(selected, "cloud"))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=title, data={CONF_DEVICES: selected})

        return self.async_show_form(step_id="select", data_schema=_select_schema(self._cloud_devices), errors=errors)

    async def async_step_local_discovery(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Discover and authenticate LAN devices without using an Intelligent AC account."""

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                result = await self.hass.async_add_executor_job(
                    _accountless_device_configs,
                    _parse_seed_hosts(user_input.get(CONF_SEED_HOSTS, "")),
                    bool(user_input.get(CONF_SCAN_SUBNET, True)),
                )
                local_devices = result.devices
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected Hyundai AC LAN discovery error")
                errors["base"] = "discovery_error"
            else:
                if not local_devices:
                    if result.locked_devices:
                        _LOGGER.warning(
                            "Hyundai AC LAN discovery found locked devices: %s",
                            _locked_device_summary(result.locked_devices),
                        )
                        errors["base"] = "locked_device"
                    else:
                        errors["base"] = "no_lan_devices"
                else:
                    self._local_devices = _filter_unconfigured_devices(self.hass, local_devices)
                    if not self._local_devices:
                        errors["base"] = "all_devices_configured"
                    else:
                        return await self.async_step_select_local()

        return self.async_show_form(
            step_id="local_discovery",
            data_schema=_local_discovery_schema(user_input),
            errors=errors,
        )

    async def async_step_select_local(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user choose LAN-discovered devices."""

        errors: dict[str, str] = {}

        if user_input is not None:
            selected_macs = set(user_input.get(CONF_SELECTION) or [])
            selected = [device for device in self._local_devices if device[CONF_MAC] in selected_macs]
            if not selected:
                errors["base"] = "no_devices_selected"
            elif _configured_macs(self.hass).intersection(_mac_unique_id(device[CONF_MAC]) for device in selected):
                errors["base"] = "already_configured"
            else:
                try:
                    await _validate_devices(self.hass, selected)
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(_devices_unique_id(selected, "local"))
                    self._abort_if_unique_id_configured()
                    title = selected[0][CONF_NAME] if len(selected) == 1 else f"Hyundai AC ({len(selected)} devices)"
                    return self.async_create_entry(title=title, data={CONF_DEVICES: selected})

        return self.async_show_form(
            step_id="select_local",
            data_schema=_select_schema(self._local_devices),
            errors=errors,
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle manual LAN setup."""

        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = _mac_unique_id(user_input[CONF_MAC])
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
            if unique_id in _configured_macs(self.hass):
                errors["base"] = "already_configured"
            else:
                try:
                    await _validate_input(self.hass, user_input)
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(step_id="manual", data_schema=_manual_schema(user_input), errors=errors)
