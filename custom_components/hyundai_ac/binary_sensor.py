"""Binary sensor entities for Hyundai AC diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HyundaiAcCoordinator, HyundaiAcRuntime


@dataclass(frozen=True, kw_only=True)
class HyundaiAcBinarySensorDescription(BinarySensorEntityDescription):
    """Description for a Hyundai AC binary sensor."""

    param: str


BINARY_SENSOR_DESCRIPTIONS: tuple[HyundaiAcBinarySensorDescription, ...] = (
    HyundaiAcBinarySensorDescription(
        key="filter_dirty",
        name="Filter dirty",
        param="if_filterdirty",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HyundaiAcBinarySensorDescription(
        key="clean_check",
        name="Clean check",
        param="clean_check",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai AC binary sensors from a config entry."""

    async_add_entities(
        [
            HyundaiAcBinarySensor(runtime, description)
            for runtime in hass.data[DOMAIN][entry.entry_id]
            for description in BINARY_SENSOR_DESCRIPTIONS
        ],
        update_before_add=True,
    )


class HyundaiAcBinarySensor(CoordinatorEntity[HyundaiAcCoordinator], BinarySensorEntity):
    """Binary sensor for a Hyundai AC boolean state parameter."""

    _attr_has_entity_name = True

    entity_description: HyundaiAcBinarySensorDescription

    def __init__(self, runtime: HyundaiAcRuntime, description: HyundaiAcBinarySensorDescription) -> None:
        super().__init__(runtime.coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_device_info = runtime.device_info
        self._attr_unique_id = f"{runtime.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return whether this parameter is supported and the device is available."""

        return super().available and self._raw_value not in (None, -1)

    @property
    def is_on(self) -> bool | None:
        """Return whether the diagnostic condition is active."""

        value = self._raw_value
        if value in (None, -1):
            return None
        return value == 1

    @property
    def _raw_value(self) -> Any:
        return (self.coordinator.data or {}).get(self.entity_description.param)
