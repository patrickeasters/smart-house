"""
Switches on Zigbee Home Automation networks.

For more details on this platform, please refer to the documentation
at https://home-assistant.io/components/switch.zha/
"""
import asyncio
import logging

from homeassistant.components.switch import DOMAIN, SwitchDevice
from homeassistant.components import zha

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['zha']
DATA_ZHA_DICT = 'zha_devices'

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup Zigbee Home Automation switches."""
    if discovery_info is None:
        return

    """Restore original discovery items that were moved to make discovery info JSON serializable."""
    discovered_endpoint_info = hass.data[DATA_ZHA_DICT][discovery_info['endpoint']]

    add_devices([Switch(**discovered_endpoint_info)])


class Switch(zha.Entity, SwitchDevice):
    """ZHA switch."""

    _domain = DOMAIN

    @property
    def is_on(self) -> bool:
        """Return if the switch is on based on the statemachine."""
        if self._state == 'unknown':
            return False
        return bool(self._state)

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        yield from self._endpoint.on_off.on()
        self._state = 1

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        yield from self._endpoint.on_off.off()
        self._state = 0
