"""Hyundai AC local integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICES, DOMAIN
from .coordinator import runtime_from_config

PLATFORMS = [Platform.CLIMATE, Platform.SWITCH, Platform.SELECT, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hyundai AC from a config entry."""

    devices = entry.data.get(CONF_DEVICES)
    if devices is None:
        devices = [entry.data]

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = [
        runtime_from_config(hass, device)
        for device in devices
    ]
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Hyundai AC config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
