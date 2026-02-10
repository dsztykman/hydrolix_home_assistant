"""Config flow for Hydrolix History integration.

Multi-step flow:
  1. **user**     – Enter host, token, SSL
  2. **project**  – Choose an existing project or create a new one
  3. **table**    – Choose an existing table or create a new one
                    (transform is auto-created on new tables)
  4. Entry is created and streaming begins.

Options flow allows tuning batch params and entity filters at any time.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .config_api import HydrolixConfigAPI, HydrolixConfigError, HA_TRANSFORM_NAME
from .const import (
    CONF_BATCH_INTERVAL,
    CONF_BATCH_SIZE,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_HYDROLIX_HOST,
    CONF_HYDROLIX_PROJECT,
    CONF_HYDROLIX_TABLE,
    CONF_HYDROLIX_TOKEN,
    CONF_HYDROLIX_USE_SSL,
    CONF_INCLUDE_DOMAINS,
    CONF_INCLUDE_ENTITIES,
    CONF_ORG_UUID,
    CONF_PROJECT_MODE,
    CONF_PROJECT_NEW_NAME,
    CONF_PROJECT_SELECT,
    CONF_PROJECT_UUID,
    CONF_TABLE_MODE,
    CONF_TABLE_NEW_NAME,
    CONF_TABLE_SELECT,
    CONF_TABLE_UUID,
    CONF_TRANSFORM_NAME,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DATABASE,
    DEFAULT_TABLE,
    DEFAULT_USE_SSL,
    DOMAIN,
    MODE_CREATE,
    MODE_EXISTING,
)

_LOGGER = logging.getLogger(__name__)

# ── Step 1 schema ────────────────────────────────────────────────────────────
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HYDROLIX_HOST): str,
        vol.Required(CONF_HYDROLIX_TOKEN): str,
        vol.Optional(CONF_HYDROLIX_USE_SSL, default=DEFAULT_USE_SSL): bool,
    }
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Main config flow
# ═══════════════════════════════════════════════════════════════════════════════


class HydrolixHistoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hydrolix History."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow-scoped state."""
        self._data: dict[str, Any] = {}
        self._api: HydrolixConfigAPI | None = None
        self._org_uuid: str = ""
        self._projects: list[dict[str, Any]] = []
        self._tables: list[dict[str, Any]] = []

    async def _get_api(self) -> HydrolixConfigAPI:
        if self._api is None:
            self._api = HydrolixConfigAPI(
                host=self._data[CONF_HYDROLIX_HOST],
                token=self._data[CONF_HYDROLIX_TOKEN],
                use_ssl=self._data.get(CONF_HYDROLIX_USE_SSL, DEFAULT_USE_SSL),
            )
        return self._api

    async def _cleanup_api(self) -> None:
        if self._api:
            await self._api.close()
            self._api = None

    # ── Step 1: Connection ───────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect host / token / SSL and validate connectivity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            try:
                api = await self._get_api()
                self._org_uuid = await api.get_org_uuid()
                self._data[CONF_ORG_UUID] = self._org_uuid
                self._projects = await api.list_projects(self._org_uuid)
                return await self.async_step_project()
            except HydrolixConfigError as exc:
                _LOGGER.error("Config API error: %s", exc)
                errors["base"] = "cannot_connect"
                await self._cleanup_api()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "cannot_connect"
                await self._cleanup_api()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    # ── Step 2: Project selection / creation ──────────────────────────────

    async def async_step_project(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick an existing project or create a new one."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mode = user_input.get(CONF_PROJECT_MODE, MODE_CREATE)
            try:
                api = await self._get_api()

                if mode == MODE_EXISTING:
                    project_uuid = user_input[CONF_PROJECT_SELECT]
                    # Resolve name from cache
                    project_name = next(
                        (
                            p["name"]
                            for p in self._projects
                            if p["uuid"] == project_uuid
                        ),
                        "unknown",
                    )
                else:
                    new_name = user_input[CONF_PROJECT_NEW_NAME]
                    proj = await api.create_project(
                        self._org_uuid, new_name, "Home Assistant history data"
                    )
                    project_uuid = proj["uuid"]
                    project_name = new_name

                self._data[CONF_PROJECT_UUID] = project_uuid
                self._data[CONF_HYDROLIX_PROJECT] = project_name

                # Fetch tables for next step
                self._tables = await api.list_tables(self._org_uuid, project_uuid)
                return await self.async_step_table()

            except HydrolixConfigError as exc:
                _LOGGER.error("Project step error: %s", exc)
                errors["base"] = "project_error"

        # Build the form dynamically based on discovered projects
        project_choices = {p["uuid"]: p["name"] for p in self._projects}
        has_projects = bool(project_choices)

        mode_choices = [MODE_CREATE]
        if has_projects:
            mode_choices.insert(0, MODE_EXISTING)

        schema_fields: dict[Any, Any] = {
            vol.Required(
                CONF_PROJECT_MODE,
                default=MODE_EXISTING if has_projects else MODE_CREATE,
            ): vol.In(
                {
                    MODE_EXISTING: "Use existing project",
                    MODE_CREATE: "Create new project",
                }
            ),
        }
        if has_projects:
            schema_fields[vol.Optional(CONF_PROJECT_SELECT)] = vol.In(project_choices)

        schema_fields[vol.Optional(CONF_PROJECT_NEW_NAME, default=DEFAULT_DATABASE)] = (
            str
        )

        return self.async_show_form(
            step_id="project",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

    # ── Step 3: Table selection / creation + auto-transform ──────────────

    async def async_step_table(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick an existing table or create a new one.

        When a new table is created the HA state-history transform is
        automatically provisioned.  When an existing table is selected
        the transform is created if it doesn't already exist.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            mode = user_input.get(CONF_TABLE_MODE, MODE_CREATE)
            try:
                api = await self._get_api()
                project_uuid = self._data[CONF_PROJECT_UUID]

                if mode == MODE_EXISTING:
                    table_uuid = user_input[CONF_TABLE_SELECT]
                    table_name = next(
                        (t["name"] for t in self._tables if t["uuid"] == table_uuid),
                        "unknown",
                    )
                else:
                    new_name = user_input[CONF_TABLE_NEW_NAME]
                    tbl = await api.create_table(
                        self._org_uuid,
                        project_uuid,
                        new_name,
                        "Home Assistant state change history",
                    )
                    table_uuid = tbl["uuid"]
                    table_name = new_name

                self._data[CONF_TABLE_UUID] = table_uuid
                self._data[CONF_HYDROLIX_TABLE] = table_name

                # ── ensure transform exists ──────────────────────────
                transforms = await api.list_transforms(
                    self._org_uuid, project_uuid, table_uuid
                )
                has_transform = any(
                    t.get("name") == HA_TRANSFORM_NAME for t in transforms
                )
                if not has_transform:
                    await api.create_transform(self._org_uuid, project_uuid, table_uuid)
                    _LOGGER.info("Auto-created transform '%s'", HA_TRANSFORM_NAME)
                else:
                    _LOGGER.info(
                        "Transform '%s' already exists on table '%s'",
                        HA_TRANSFORM_NAME,
                        table_name,
                    )

                self._data[CONF_TRANSFORM_NAME] = HA_TRANSFORM_NAME
                # For backward compat, keep "database" = project name
                self._data["hydrolix_database"] = self._data[CONF_HYDROLIX_PROJECT]

                await self._cleanup_api()

                # ── create the config entry ──────────────────────────
                unique_id = (
                    f"{self._data[CONF_HYDROLIX_HOST]}"
                    f"_{self._data[CONF_HYDROLIX_PROJECT]}"
                    f"_{self._data[CONF_HYDROLIX_TABLE]}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = (
                    f"Hydrolix ({self._data[CONF_HYDROLIX_PROJECT]}"
                    f".{self._data[CONF_HYDROLIX_TABLE]})"
                )
                return self.async_create_entry(title=title, data=self._data)

            except HydrolixConfigError as exc:
                _LOGGER.error("Table step error: %s", exc)
                errors["base"] = "table_error"

        # Build form
        table_choices = {t["uuid"]: t["name"] for t in self._tables}
        has_tables = bool(table_choices)

        schema_fields: dict[Any, Any] = {
            vol.Required(
                CONF_TABLE_MODE, default=MODE_EXISTING if has_tables else MODE_CREATE
            ): vol.In(
                {MODE_EXISTING: "Use existing table", MODE_CREATE: "Create new table"}
            ),
        }
        if has_tables:
            schema_fields[vol.Optional(CONF_TABLE_SELECT)] = vol.In(table_choices)

        schema_fields[vol.Optional(CONF_TABLE_NEW_NAME, default=DEFAULT_TABLE)] = str

        return self.async_show_form(
            step_id="table",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={
                "project_name": self._data.get(CONF_HYDROLIX_PROJECT, ""),
            },
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
            ):
                val = user_input.get(key, "")
                if isinstance(val, str):
                    parsed[key] = [s.strip() for s in val.split(",") if s.strip()]
                else:
                    parsed[key] = val

            return self.async_create_entry(title="", data=parsed)

        current = self._config_entry.options
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
                        default=", ".join(current.get(CONF_INCLUDE_DOMAINS, [])),
                    ): str,
                    vol.Optional(
                        CONF_EXCLUDE_DOMAINS,
                        default=", ".join(current.get(CONF_EXCLUDE_DOMAINS, [])),
                    ): str,
                    vol.Optional(
                        CONF_INCLUDE_ENTITIES,
                        default=", ".join(current.get(CONF_INCLUDE_ENTITIES, [])),
                    ): str,
                    vol.Optional(
                        CONF_EXCLUDE_ENTITIES,
                        default=", ".join(current.get(CONF_EXCLUDE_ENTITIES, [])),
                    ): str,
                }
            ),
        )
