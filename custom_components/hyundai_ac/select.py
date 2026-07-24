"""Select entities for Hyundai AC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HyundaiAcCoordinator, HyundaiAcRuntime

SLEEP_OPTIONS = {
    0: "off",
    1: "normal",
    2: "senior",
    3: "child",
    4: "custom",
}


@dataclass(frozen=True, kw_only=True)
class HyundaiAcSelectDescription(SelectEntityDescription):
    """Description for a Hyundai AC select."""

    param: str
    options_by_code: dict[int, str]


SELECT_DESCRIPTIONS: tuple[HyundaiAcSelectDescription, ...] = (
    HyundaiAcSelectDescription(
        key="sleep",
        name="Sleep",
        icon="mdi:sleep",
        param="tcl_slp",
        options_by_code=SLEEP_OPTIONS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai AC selects from a config entry."""

    async_add_entities(
        [
            HyundaiAcSelect(runtime, description)
            for runtime in hass.data[DOMAIN][entry.entry_id]
            for description in SELECT_DESCRIPTIONS
        ],
        update_before_add=True,
    )


class HyundaiAcSelect(CoordinatorEntity[HyundaiAcCoordinator], SelectEntity):
    """Select for a Hyundai AC enum parameter."""

    _attr_has_entity_name = True

    entity_description: HyundaiAcSelectDescription

    def __init__(self, runtime: HyundaiAcRuntime, description: HyundaiAcSelectDescription) -> None:
        super().__init__(runtime.coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_device_info = runtime.device_info
        self._attr_unique_id = f"{runtime.unique_id}_{description.key}"
        self._attr_options = list(description.options_by_code.values())

    @property
    def available(self) -> bool:
        """Return whether this parameter is supported and the device is available."""

        return super().available and self._raw_value not in (None, -1)

    @property
    def current_option(self) -> str | None:
        """Return selected option."""

        value = self._raw_value
        if value in (None, -1):
            return None
        return self.entity_description.options_by_code.get(value)

    @property
    def _raw_value(self) -> Any:
        return (self.coordinator.data or {}).get(self.entity_description.param)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""

        code_by_option = {value: key for key, value in self.entity_description.options_by_code.items()}
        await self.coordinator.async_set_param(self.entity_description.param, code_by_option[option])
