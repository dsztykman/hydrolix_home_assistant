"""Config flow for Hydrolix History integration.

Single-step flow: enter the cluster host, an ingest token, and the
project / table to stream into. Nothing is provisioned from Home
Assistant: the project and table must already exist, and Schema
Intelligence (Autopilot) provides a transform that accepts every event
and promotes fields once enough data has built confidence in them.

Options flow allows tuning batch params and entity filters at any time.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import HydrolixClient
from .const import (
    CONF_BATCH_INTERVAL,
    CONF_BATCH_SIZE,
    CONF_EXCLUDE_DEVICE_CLASSES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_HYDROLIX_HOST,
    CONF_HYDROLIX_PROJECT,
    CONF_HYDROLIX_TABLE,
    CONF_HYDROLIX_TOKEN,
    CONF_HYDROLIX_USE_SSL,
    CONF_INCLUDE_DEVICE_CLASSES,
    CONF_INCLUDE_DOMAINS,
    CONF_INCLUDE_ENTITIES,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_PROJECT,
    DEFAULT_TABLE,
    DEFAULT_USE_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Project and table names end up in the ingest URL and in SQL.
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HYDROLIX_HOST): str,
        vol.Required(CONF_HYDROLIX_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_HYDROLIX_PROJECT, default=DEFAULT_PROJECT): str,
        vol.Required(CONF_HYDROLIX_TABLE, default=DEFAULT_TABLE): str,
        vol.Optional(CONF_HYDROLIX_USE_SSL, default=DEFAULT_USE_SSL): bool,
    }
)


def _clean_host(value: str) -> str:
    """Reduce a pasted URL to a bare hostname."""
    host = value.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    return host.split("/", 1)[0]


# ═══════════════════════════════════════════════════════════════════════════════
#  Main config flow
# ═══════════════════════════════════════════════════════════════════════════════


class HydrolixHistoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hydrolix History."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect host, ingest token and target table."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {
                CONF_HYDROLIX_HOST: _clean_host(user_input[CONF_HYDROLIX_HOST]),
                CONF_HYDROLIX_TOKEN: user_input[CONF_HYDROLIX_TOKEN].strip(),
                CONF_HYDROLIX_PROJECT: user_input[CONF_HYDROLIX_PROJECT].strip(),
                CONF_HYDROLIX_TABLE: user_input[CONF_HYDROLIX_TABLE].strip(),
                CONF_HYDROLIX_USE_SSL: user_input.get(
                    CONF_HYDROLIX_USE_SSL, DEFAULT_USE_SSL
                ),
            }

            if not data[CONF_HYDROLIX_HOST]:
                errors[CONF_HYDROLIX_HOST] = "invalid_host"
            if not data[CONF_HYDROLIX_TOKEN]:
                errors[CONF_HYDROLIX_TOKEN] = "invalid_token"
            if not _NAME_RE.match(data[CONF_HYDROLIX_PROJECT]):
                errors[CONF_HYDROLIX_PROJECT] = "invalid_name"
            if not _NAME_RE.match(data[CONF_HYDROLIX_TABLE]):
                errors[CONF_HYDROLIX_TABLE] = "invalid_name"

            if not errors:
                await self.async_set_unique_id(
                    f"{data[CONF_HYDROLIX_HOST]}"
                    f"_{data[CONF_HYDROLIX_PROJECT]}"
                    f"_{data[CONF_HYDROLIX_TABLE]}"
                )
                self._abort_if_unique_id_configured()

                # Reachability only: a token cannot be verified without
                # writing an event, so auth errors show on the first flush.
                client = HydrolixClient(
                    host=data[CONF_HYDROLIX_HOST],
                    database=data[CONF_HYDROLIX_PROJECT],
                    table=data[CONF_HYDROLIX_TABLE],
                    token=data[CONF_HYDROLIX_TOKEN],
                    use_ssl=data[CONF_HYDROLIX_USE_SSL],
                )
                try:
                    reachable = await client.async_connect()
                finally:
                    await client.async_stop()

                if reachable:
                    title = (
                        f"Hydrolix ({data[CONF_HYDROLIX_PROJECT]}"
                        f".{data[CONF_HYDROLIX_TABLE]})"
                    )
                    return self.async_create_entry(title=title, data=data)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HydrolixHistoryOptionsFlow:
        """Get the options flow handler."""
        return HydrolixHistoryOptionsFlow(config_entry)


# ═══════════════════════════════════════════════════════════════════════════════
#  Options flow (batching + entity filters)
# ═══════════════════════════════════════════════════════════════════════════════


class HydrolixHistoryOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Hydrolix History."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            parsed: dict[str, Any] = {}
            for key in (CONF_BATCH_SIZE, CONF_BATCH_INTERVAL):
                if key in user_input:
                    parsed[key] = user_input[key]

            for key in (
                CONF_INCLUDE_DOMAINS,
                CONF_EXCLUDE_DOMAINS,
                CONF_INCLUDE_ENTITIES,
                CONF_EXCLUDE_ENTITIES,
                CONF_INCLUDE_DEVICE_CLASSES,
                CONF_EXCLUDE_DEVICE_CLASSES,
            ):
                parsed[key] = user_input.get(key, [])

            return self.async_create_entry(title="", data=parsed)

        current = self._config_entry.options

        # Discover all domains and device classes from the entity registry
        registry = er.async_get(self.hass)
        all_domains = sorted({e.domain for e in registry.entities.values()})
        all_device_classes = sorted(
            {e.device_class for e in registry.entities.values() if e.device_class}
        )

        domain_selector = SelectSelector(
            SelectSelectorConfig(
                options=all_domains,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

        device_class_selector = SelectSelector(
            SelectSelectorConfig(
                options=all_device_classes,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

        entity_selector = EntitySelector(EntitySelectorConfig(multiple=True))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BATCH_SIZE,
                        default=current.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE),
                    ): vol.All(int, vol.Range(min=1, max=10000)),
                    vol.Optional(
                        CONF_BATCH_INTERVAL,
                        default=current.get(
                            CONF_BATCH_INTERVAL, DEFAULT_BATCH_INTERVAL
                        ),
                    ): vol.All(int, vol.Range(min=1, max=300)),
                    vol.Optional(
                        CONF_INCLUDE_DOMAINS,
                        default=current.get(CONF_INCLUDE_DOMAINS, []),
                    ): domain_selector,
                    vol.Optional(
                        CONF_EXCLUDE_DOMAINS,
                        default=current.get(CONF_EXCLUDE_DOMAINS, []),
                    ): domain_selector,
                    vol.Optional(
                        CONF_INCLUDE_ENTITIES,
                        default=current.get(CONF_INCLUDE_ENTITIES, []),
                    ): entity_selector,
                    vol.Optional(
                        CONF_EXCLUDE_ENTITIES,
                        default=current.get(CONF_EXCLUDE_ENTITIES, []),
                    ): entity_selector,
                    vol.Optional(
                        CONF_INCLUDE_DEVICE_CLASSES,
                        default=current.get(CONF_INCLUDE_DEVICE_CLASSES, []),
                    ): device_class_selector,
                    vol.Optional(
                        CONF_EXCLUDE_DEVICE_CLASSES,
                        default=current.get(CONF_EXCLUDE_DEVICE_CLASSES, []),
                    ): device_class_selector,
                }
            ),
        )
