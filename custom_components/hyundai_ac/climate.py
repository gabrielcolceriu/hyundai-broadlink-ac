"""Climate platform for Hyundai AC local control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.components.climate.const import FAN_AUTO, FAN_HIGH, FAN_LOW, FAN_MEDIUM
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, CONF_HOST, CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICES, CONF_KEY, CONF_MAC, DOMAIN
from .coordinator import HyundaiAcCoordinator, HyundaiAcRuntime, runtime_from_config

FAN_MID_LOW = "mid_low"
FAN_MID_HIGH = "mid_high"
SWING_OFF = "off"
SWING_VERTICAL = "vertical"
SWING_HORIZONTAL = "horizontal"
SWING_BOTH = "both"
VERTICAL_SWING_CODE = 7
HORIZONTAL_SWING_CODE = 1

MODE_TO_CODE = {
    HVACMode.HEAT: 1,
    HVACMode.DRY: 2,
    HVACMode.COOL: 3,
    HVACMode.FAN_ONLY: 4,
    HVACMode.AUTO: 5,
}
CODE_TO_MODE = {code: mode for mode, code in MODE_TO_CODE.items()}

FAN_TO_CODE = {
    FAN_AUTO: 0,
    FAN_LOW: 1,
    FAN_MEDIUM: 2,
    FAN_HIGH: 3,
    FAN_MID_LOW: 4,
    FAN_MID_HIGH: 5,
}
CODE_TO_FAN = {code: mode for mode, code in FAN_TO_CODE.items()}

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_MAC): cv.string,
        vol.Required(CONF_KEY): cv.string,
    }
)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({vol.Required(CONF_DEVICES): vol.All(cv.ensure_list, [DEVICE_SCHEMA])})


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Hyundai AC climate entities from YAML."""

    entities = [
        HyundaiIntelligentAcClimate(
            runtime=runtime_from_config(hass, device),
        )
        for device in config[CONF_DEVICES]
    ]
    async_add_entities(entities, update_before_add=True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai AC climate entities from a config entry."""

    async_add_entities(
        [
            HyundaiIntelligentAcClimate(
                runtime=runtime,
            )
            for runtime in hass.data[DOMAIN][entry.entry_id]
        ],
        update_before_add=True,
    )


class HyundaiIntelligentAcClimate(CoordinatorEntity[HyundaiAcCoordinator], ClimateEntity):
    """Hyundai AC climate entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "hyundai_ac"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _attr_min_temp = 16.0
    _attr_max_temp = 31.0
    _attr_swing_modes = [SWING_OFF, SWING_VERTICAL]
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    ]
    _attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MID_LOW, FAN_MEDIUM, FAN_MID_HIGH, FAN_HIGH]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, runtime: HyundaiAcRuntime) -> None:
        super().__init__(runtime.coordinator)
        self._attr_device_info = runtime.device_info
        self._attr_unique_id = runtime.unique_id

    @property
    def _state(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def current_temperature(self) -> float | None:
        """Return current room temperature."""

        value = self._state.get("envtemp")
        return float(value) if isinstance(value, int | float) else None

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""

        value = self._state.get("temp")
        return float(value) / 10 if isinstance(value, int | float) else None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""

        if self._state.get("pwr") != 1:
            return HVACMode.OFF
        return CODE_TO_MODE.get(self._state.get("tcl_mode"), HVACMode.COOL)

    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode."""

        return CODE_TO_FAN.get(self._state.get("tcl_mark"))

    @property
    def swing_mode(self) -> str | None:
        """Return current swing mode."""

        # This AC only has vertical louvers (no horizontal swing).
        if self._state.get("tcl_vdir") == VERTICAL_SWING_CODE:
            return SWING_VERTICAL
        return SWING_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""

        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_set_param("temp", int(float(temperature) * 10))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""

        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_param("pwr", 0)
            return

        code = MODE_TO_CODE[hvac_mode]
        await self.coordinator.async_set_params({"pwr": 1, "tcl_mode": code})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""

        await self.coordinator.async_set_param("tcl_mark", FAN_TO_CODE[fan_mode])

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set swing mode."""

        # Vertical-only swing for this AC.
        await self.coordinator.async_set_param(
            "tcl_vdir",
            VERTICAL_SWING_CODE if swing_mode == SWING_VERTICAL else 0,
        )

    async def async_turn_on(self) -> None:
        """Turn the AC on."""

        await self.coordinator.async_set_param("pwr", 1)

    async def async_turn_off(self) -> None:
        """Turn the AC off."""

        await self.coordinator.async_set_param("pwr", 0)
