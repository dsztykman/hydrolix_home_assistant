"""Sensor platform for Hydrolix History integration.

Provides diagnostic sensors for monitoring the health and throughput
of the Hydrolix history pipeline.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import HydrolixClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = 10  # seconds


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hydrolix History sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: HydrolixClient = data["client"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Hydrolix History",
        manufacturer="Hydrolix",
        model="Time-Series Database",
        entry_type="service",
    )

    sensors = [
        HydrolixEventsSentSensor(client, entry, device_info),
        HydrolixEventsDroppedSensor(client, entry, device_info),
        HydrolixEventsQueuedSensor(client, entry, device_info),
        HydrolixConnectionStatusSensor(client, entry, device_info),
        HydrolixLastErrorSensor(client, entry, device_info),
    ]

    async_add_entities(sensors, update_before_add=True)


class HydrolixBaseSensor(SensorEntity):
    """Base class for Hydrolix diagnostic sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        client: HydrolixClient,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info
        self._attr_name = name

    async def async_update(self) -> None:
        """Update sensor state from client stats."""
        # Subclasses implement specific update logic
        pass


class HydrolixEventsSentSensor(HydrolixBaseSensor):
    """Sensor tracking total events sent to Hydrolix."""

    _attr_icon = "mdi:database-arrow-up"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "events"

    def __init__(
        self, client: HydrolixClient, entry: ConfigEntry, device_info: DeviceInfo
    ) -> None:
        """Initialize."""
        super().__init__(client, entry, device_info, "events_sent", "Events Sent")

    async def async_update(self) -> None:
        """Update the sensor."""
        self._attr_native_value = self._client.stats.events_sent


class HydrolixEventsDroppedSensor(HydrolixBaseSensor):
    """Sensor tracking dropped events."""

    _attr_icon = "mdi:database-remove"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "events"

    def __init__(
        self, client: HydrolixClient, entry: ConfigEntry, device_info: DeviceInfo
    ) -> None:
        """Initialize."""
        super().__init__(
            client, entry, device_info, "events_dropped", "Events Dropped"
        )

    async def async_update(self) -> None:
        """Update the sensor."""
        self._attr_native_value = self._client.stats.events_dropped


class HydrolixEventsQueuedSensor(HydrolixBaseSensor):
    """Sensor tracking events currently in the queue."""

    _attr_icon = "mdi:database-clock"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "events"

    def __init__(
        self, client: HydrolixClient, entry: ConfigEntry, device_info: DeviceInfo
    ) -> None:
        """Initialize."""
        super().__init__(
            client, entry, device_info, "events_queued", "Events Queued"
        )

    async def async_update(self) -> None:
        """Update the sensor."""
        self._attr_native_value = self._client.stats.events_queued


class HydrolixConnectionStatusSensor(HydrolixBaseSensor):
    """Sensor tracking connection status."""

    _attr_icon = "mdi:connection"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["connected", "disconnected"]

    def __init__(
        self, client: HydrolixClient, entry: ConfigEntry, device_info: DeviceInfo
    ) -> None:
        """Initialize."""
        super().__init__(
            client, entry, device_info, "connection_status", "Connection Status"
        )

    async def async_update(self) -> None:
        """Update the sensor."""
        self._attr_native_value = (
            "connected" if self._client.stats.connected else "disconnected"
        )


class HydrolixLastErrorSensor(HydrolixBaseSensor):
    """Sensor tracking the last error message."""

    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self, client: HydrolixClient, entry: ConfigEntry, device_info: DeviceInfo
    ) -> None:
        """Initialize."""
        super().__init__(
            client, entry, device_info, "last_error", "Last Error"
        )

    async def async_update(self) -> None:
        """Update the sensor."""
        error = self._client.stats.last_error
        self._attr_native_value = error[:255] if error else "None"
        self._attr_extra_state_attributes = {
            "last_sent": (
                self._client.stats.last_sent.isoformat()
                if self._client.stats.last_sent
                else None
            ),
        }
