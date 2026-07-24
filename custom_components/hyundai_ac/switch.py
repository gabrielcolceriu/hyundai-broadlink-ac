"""Switch entities for Hyundai AC extra features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HyundaiAcCoordinator, HyundaiAcRuntime


@dataclass(frozen=True, kw_only=True)
class HyundaiAcSwitchDescription(SwitchEntityDescription):
    """Description for a Hyundai AC switch."""

    param: str


SWITCH_DESCRIPTIONS: tuple[HyundaiAcSwitchDescription, ...] = (
    HyundaiAcSwitchDescription(key="clean", name="Evaporator clean", icon="mdi:air-filter", param="evaportor"),
    HyundaiAcSwitchDescription(key="turbo", name="Turbo", icon="mdi:fan-chevron-up", param="pwfmode"),
    HyundaiAcSwitchDescription(key="eco", name="Eco", icon="mdi:leaf", param="ecomode"),
    HyundaiAcSwitchDescription(key="quiet", name="Quiet", icon="mdi:volume-low", param="qtmode"),
    HyundaiAcSwitchDescription(key="display", name="Display", icon="mdi:television-ambient-light", param="bglight"),
    HyundaiAcSwitchDescription(key="buzzer", name="Buzzer", icon="mdi:volume-high", param="beep"),
    HyundaiAcSwitchDescription(key="anti_mildew", name="Anti-mildew", icon="mdi:shield-check-outline", param="smartdesic"),
    HyundaiAcSwitchDescription(key="health", name="Health", icon="mdi:heart-pulse", param="ac_health"),
    HyundaiAcSwitchDescription(key="eight_degree_heat", name="Frost protection", icon="mdi:snowflake-thermometer", param="8heat"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai AC switches from a config entry."""

    async_add_entities(
        [
            HyundaiAcSwitch(runtime, description)
            for runtime in hass.data[DOMAIN][entry.entry_id]
            for description in SWITCH_DESCRIPTIONS
        ],
        update_before_add=True,
    )


class HyundaiAcSwitch(CoordinatorEntity[HyundaiAcCoordinator], SwitchEntity):
    """Switch for a Hyundai AC boolean parameter."""

    _attr_has_entity_name = True

    entity_description: HyundaiAcSwitchDescription

    def __init__(self, runtime: HyundaiAcRuntime, description: HyundaiAcSwitchDescription) -> None:
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
        """Return whether the feature is enabled."""

        value = self._raw_value
        if value in (None, -1):
            return None
        return value == 1

    @property
    def _raw_value(self) -> Any:
        return (self.coordinator.data or {}).get(self.entity_description.param)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the feature on."""

        await self.coordinator.async_set_param(self.entity_description.param, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the feature off."""

        await self.coordinator.async_set_param(self.entity_description.param, 0)
