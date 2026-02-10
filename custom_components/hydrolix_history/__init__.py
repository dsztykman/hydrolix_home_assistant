"""Hydrolix History integration for Home Assistant.

This integration streams Home Assistant state changes to a Hydrolix
time-series database, providing long-term history storage optimized
for high-volume time-series data.

Similar to the InfluxDB integration, this runs alongside the built-in
recorder and provides a scalable, cloud-native alternative for
historical data retention and analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State, callback

from .client import HydrolixClient, StateEvent
from .const import (
    CONF_BATCH_INTERVAL,
    CONF_BATCH_SIZE,
    CONF_EXCLUDE_DEVICE_CLASSES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_ENTITY_GLOBS,
    CONF_HYDROLIX_DATABASE,
    CONF_HYDROLIX_HOST,
    CONF_HYDROLIX_PROJECT,
    CONF_HYDROLIX_TABLE,
    CONF_HYDROLIX_TOKEN,
    CONF_HYDROLIX_USE_SSL,
    CONF_INCLUDE_DEVICE_CLASSES,
    CONF_INCLUDE_DOMAINS,
    CONF_INCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITY_GLOBS,
    CONF_TRANSFORM_NAME,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DATABASE,
    DEFAULT_TABLE,
    DEFAULT_USE_SSL,
    DOMAIN,
)
from .entity_filter import EntityFilter

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hydrolix History from a config entry."""
    _LOGGER.info("Setting up Hydrolix History integration")

    # Extract configuration
    config = entry.data
    options = entry.options

    host = config[CONF_HYDROLIX_HOST]
    # Project name doubles as the database name for queries
    database = config.get(
        CONF_HYDROLIX_PROJECT, config.get(CONF_HYDROLIX_DATABASE, DEFAULT_DATABASE)
    )
    table = config.get(CONF_HYDROLIX_TABLE, DEFAULT_TABLE)
    token = config[CONF_HYDROLIX_TOKEN]
    use_ssl = config.get(CONF_HYDROLIX_USE_SSL, DEFAULT_USE_SSL)
    transform_name = config.get(CONF_TRANSFORM_NAME, "")
    batch_size = options.get(
        CONF_BATCH_SIZE, config.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE)
    )
    batch_interval = options.get(
        CONF_BATCH_INTERVAL, config.get(CONF_BATCH_INTERVAL, DEFAULT_BATCH_INTERVAL)
    )

    # Build entity filter from options (or config fallback)
    entity_filter = EntityFilter(
        include_domains=options.get(
            CONF_INCLUDE_DOMAINS, config.get(CONF_INCLUDE_DOMAINS, [])
        ),
        exclude_domains=options.get(
            CONF_EXCLUDE_DOMAINS, config.get(CONF_EXCLUDE_DOMAINS, [])
        ),
        include_entities=options.get(
            CONF_INCLUDE_ENTITIES, config.get(CONF_INCLUDE_ENTITIES, [])
        ),
        exclude_entities=options.get(
            CONF_EXCLUDE_ENTITIES, config.get(CONF_EXCLUDE_ENTITIES, [])
        ),
        include_entity_globs=options.get(
            CONF_INCLUDE_ENTITY_GLOBS, config.get(CONF_INCLUDE_ENTITY_GLOBS, [])
        ),
        exclude_entity_globs=options.get(
            CONF_EXCLUDE_ENTITY_GLOBS, config.get(CONF_EXCLUDE_ENTITY_GLOBS, [])
        ),
        include_device_classes=options.get(
            CONF_INCLUDE_DEVICE_CLASSES, config.get(CONF_INCLUDE_DEVICE_CLASSES, [])
        ),
        exclude_device_classes=options.get(
            CONF_EXCLUDE_DEVICE_CLASSES, config.get(CONF_EXCLUDE_DEVICE_CLASSES, [])
        ),
    )

    # Create the Hydrolix client
    client = HydrolixClient(
        host=host,
        database=database,
        table=table,
        token=token,
        use_ssl=use_ssl,
        batch_size=batch_size,
        batch_interval=batch_interval,
        transform_name=transform_name,
    )

    # Test connectivity
    connected = await client.async_connect()
    if not connected:
        _LOGGER.warning(
            "Could not connect to Hydrolix at %s — will retry on flush",
            host,
        )

    # Start the background flush loop
    await client.async_start()

    # Store the client and filter in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "filter": entity_filter,
    }

    # Subscribe to state change events
    @callback
    def _handle_state_changed(event: Event) -> None:
        """Handle a state changed event."""
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return

        entity_id = new_state.entity_id

        # Apply entity filter
        device_class = new_state.attributes.get("device_class")
        if not entity_filter.should_record(entity_id, device_class=device_class):
            return

        old_state: State | None = event.data.get("old_state")
        old_state_str = old_state.state if old_state else None

        # Build the state event
        now = datetime.now(timezone.utc)
        state_event = StateEvent(
            entity_id=entity_id,
            domain=new_state.domain,
            state=new_state.state,
            old_state=old_state_str,
            attributes=dict(new_state.attributes),
            last_changed=new_state.last_changed.isoformat()
            if new_state.last_changed
            else now.isoformat(),
            last_updated=new_state.last_updated.isoformat()
            if new_state.last_updated
            else now.isoformat(),
            timestamp=now.isoformat(),
        )

        client.enqueue(state_event)

    # Register the event listener
    unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_state_changed)
    hass.data[DOMAIN][entry.entry_id]["unsub"] = unsub

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    _LOGGER.info(
        "Hydrolix History integration started — streaming to https://%s/ingest/event?table=%s.%s",
        host,
        database,
        table,
    )

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Hydrolix History integration")

    # Unsubscribe from state changes
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        unsub = data.get("unsub")
        if unsub:
            unsub()

        client: HydrolixClient = data.get("client")
        if client:
            await client.async_stop()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
