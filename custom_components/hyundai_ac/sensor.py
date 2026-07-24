"""Sensor entities for Hyundai AC diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HyundaiAcCoordinator, HyundaiAcRuntime


@dataclass(frozen=True, kw_only=True)
class HyundaiAcSensorDescription(SensorEntityDescription):
    """Description for a Hyundai AC sensor."""

    param: str


SENSOR_DESCRIPTIONS: tuple[HyundaiAcSensorDescription, ...] = (
    HyundaiAcSensorDescription(
        key="outdoor_temperature",
        name="Outdoor temperature",
        param="envtempoutdoor",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    HyundaiAcSensorDescription(
        key="coil_temperature",
        name="Coil temperature",
        param="in_coil_temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HyundaiAcSensorDescription(
        key="vent_temperature",
        name="Vent temperature",
        param="in_vent_temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HyundaiAcSensorDescription(
        key="error_code_1",
        name="Error code 1",
        icon="mdi:alert-circle-outline",
        param="ac_errcode1",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HyundaiAcSensorDescription(
        key="error_code_2",
        name="Error code 2",
        icon="mdi:alert-circle-outline",
        param="ac_errcode2",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai AC sensors from a config entry."""

    async_add_entities(
        [
            HyundaiAcSensor(runtime, description)
            for runtime in hass.data[DOMAIN][entry.entry_id]
            for description in SENSOR_DESCRIPTIONS
        ],
        update_before_add=True,
    )


class HyundaiAcSensor(CoordinatorEntity[HyundaiAcCoordinator], SensorEntity):
    """Sensor for a Hyundai AC state parameter."""

    _attr_has_entity_name = True

    entity_description: HyundaiAcSensorDescription

    def __init__(self, runtime: HyundaiAcRuntime, description: HyundaiAcSensorDescription) -> None:
        super().__init__(runtime.coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_device_info = runtime.device_info
        self._attr_unique_id = f"{runtime.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return whether this parameter is supported and the device is available."""

        return super().available and self.native_value not in (None, -1)

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""

        return (self.coordinator.data or {}).get(self.entity_description.param)
