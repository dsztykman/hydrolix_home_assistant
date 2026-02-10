"""Hydrolix Config API client for managing projects, tables, and transforms.

Uses the Hydrolix REST Config API at /config/v1/ to:
- Login and discover org UUID
- List / create projects
- List / create tables
- Create the Home Assistant state history transform
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# ── Home Assistant transform schema ──────────────────────────────────────────
# This is the default write transform that tells Hydrolix how to parse
# the NDJSON state-change events pushed by the ingest client.

HA_TRANSFORM_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "timestamp",
        "datatype": {
            "type": "datetime",
            "primary": True,
            "format": "2006-01-02T15:04:05.000000Z07:00",
            "resolution": "ms",
        },
    },
    {
        "name": "entity_id",
        "datatype": {"type": "string", "index": True},
    },
    {
        "name": "domain",
        "datatype": {"type": "string", "index": True},
    },
    {
        "name": "state",
        "datatype": {"type": "string", "index": True},
    },
    {
        "name": "old_state",
        "datatype": {"type": "string", "index": True, "default": ""},
    },
    {
        "name": "state_float",
        "datatype": {"type": "double", "index": False, "default": "0"},
    },
    {
        "name": "last_changed",
        "datatype": {
            "type": "datetime",
            "format": "2006-01-02T15:04:05.000000Z07:00",
            "resolution": "ms",
            "index": True,
        },
    },
    {
        "name": "last_updated",
        "datatype": {
            "type": "datetime",
            "format": "2006-01-02T15:04:05.000000Z07:00",
            "resolution": "ms",
            "index": True,
        },
    },
    {
        "name": "friendly_name",
        "datatype": {"type": "string", "index": True, "default": ""},
    },
    {
        "name": "device_class",
        "datatype": {"type": "string", "index": True, "default": ""},
    },
    {
        "name": "unit_of_measurement",
        "datatype": {"type": "string", "index": True, "default": ""},
    },
    {
        "name": "icon",
        "datatype": {"type": "string", "index": True, "default": ""},
    },
    {
        "name": "attributes",
        "datatype": {"type": "json"},
    },
]

HA_TRANSFORM_NAME = "ha_state_history"

HA_TRANSFORM_BODY: dict[str, Any] = {
    "name": HA_TRANSFORM_NAME,
    "description": "Home Assistant state change events — auto-created by the Hydrolix History integration",
    "type": "json",
    "settings": {
        "is_default": True,
        "output_columns": HA_TRANSFORM_SCHEMA,
        "format_details": {
            "flattening": {"active": False, "map_flattening_strategy": None}
        },
    },
}


class HydrolixConfigError(Exception):
    """Raised when a Hydrolix Config API call fails."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


class HydrolixConfigAPI:
    """Async wrapper around the Hydrolix Config REST API (/config/v1/)."""

    def __init__(
        self,
        host: str,
        token: str,
        use_ssl: bool = True,
    ) -> None:
        """Initialise with the cluster hostname and a bearer token."""
        scheme = "https" if use_ssl else "http"
        self._base = f"{scheme}://{host}/config/v1"
        self._token = token
        self._session: aiohttp.ClientSession | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── generic helpers ──────────────────────────────────────────────────

    async def _get(self, path: str) -> Any:
        session = await self._ensure_session()
        async with session.get(
            f"{self._base}{path}", headers=self._headers()
        ) as resp:
            body = await resp.json()
            if resp.status >= 400:
                raise HydrolixConfigError(resp.status, str(body)[:500])
            return body

    async def _post(self, path: str, payload: dict) -> Any:
        session = await self._ensure_session()
        async with session.post(
            f"{self._base}{path}", headers=self._headers(), json=payload
        ) as resp:
            body = await resp.json()
            if resp.status >= 400:
                raise HydrolixConfigError(resp.status, str(body)[:500])
            return body

    @staticmethod
    def _unwrap_list(body: Any) -> list[dict[str, Any]]:
        """Extract a list of items from a Hydrolix Config API response.

        The API can return:
          - Paginated: {"count": N, "results": [...], "next": ..., "previous": ...}
          - Bare list:  [...]
          - Single obj: {...}
        This normalises all three into a plain list.
        """
        if isinstance(body, dict):
            # Paginated response
            if "results" in body:
                return body["results"]
            # Single object — wrap it
            return [body]
        if isinstance(body, list):
            return body
        return []

    @staticmethod
    def _unwrap_single(body: Any) -> dict[str, Any]:
        """Extract a single item from a create/get response.

        POST responses may return a bare object, a list with one item,
        or a paginated wrapper.
        """
        if isinstance(body, list) and body:
            return body[0]
        if isinstance(body, dict):
            if "results" in body and body["results"]:
                return body["results"][0]
            return body
        return {}

    # ── org discovery ────────────────────────────────────────────────────

    async def get_org_uuid(self) -> str:
        """Return the first org UUID visible to the authenticated user.

        Uses GET /config/v1/orgs/ which returns the orgs the
        current token has access to (paginated in v5.4+).
        """
        body = await self._get("/orgs/")
        orgs = self._unwrap_list(body)
        _LOGGER.debug("GET /orgs/ returned %d org(s): %s", len(orgs), orgs)

        if orgs and "uuid" in orgs[0]:
            return orgs[0]["uuid"]

        raise HydrolixConfigError(
            0,
            f"Could not determine org UUID from /orgs/ response: {str(body)[:300]}",
        )

    # ── projects ─────────────────────────────────────────────────────────

    async def list_projects(self, org_uuid: str) -> list[dict[str, Any]]:
        """List all projects in the org."""
        body = await self._get(f"/orgs/{org_uuid}/projects/")
        return self._unwrap_list(body)

    async def create_project(
        self, org_uuid: str, name: str, description: str = ""
    ) -> dict[str, Any]:
        """Create a new project and return its metadata (incl. uuid)."""
        payload = {"name": name, "description": description or f"{name} project"}
        result = await self._post(f"/orgs/{org_uuid}/projects/", payload)
        project = self._unwrap_single(result)
        _LOGGER.info("Created Hydrolix project '%s' (uuid=%s)", name, project.get("uuid"))
        return project

    # ── tables ───────────────────────────────────────────────────────────

    async def list_tables(
        self, org_uuid: str, project_uuid: str
    ) -> list[dict[str, Any]]:
        """List all tables in a project."""
        body = await self._get(
            f"/orgs/{org_uuid}/projects/{project_uuid}/tables/"
        )
        return self._unwrap_list(body)

    async def create_table(
        self,
        org_uuid: str,
        project_uuid: str,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new table and return its metadata (incl. uuid)."""
        payload = {
            "name": name,
            "description": description or f"{name} table",
            "settings": {
                "stream": {
                    "hot_data_max_age_minutes": 5,
                    "hot_data_max_active_partitions": 3,
                    "hot_data_max_rows_per_partition": 12288000,
                    "hot_data_max_minutes_per_partition": 5,
                    "hot_data_max_open_seconds": 60,
                    "hot_data_max_idle_seconds": 30,
                    "cold_data_max_age_days": 3650,
                    "cold_data_max_active_partitions": 50,
                    "cold_data_max_rows_per_partition": 12288000,
                    "cold_data_max_minutes_per_partition": 60,
                    "cold_data_max_open_seconds": 30,
                    "cold_data_max_idle_seconds": 60,
                },
                "age": {"max_age_days": 0},
                "merge": {"enabled": True},
                "sort_keys": ["entity_id"],
                "max_future_days": 0,
            },
        }
        result = await self._post(
            f"/orgs/{org_uuid}/projects/{project_uuid}/tables/", payload
        )
        table = self._unwrap_single(result)
        _LOGGER.info("Created Hydrolix table '%s' (uuid=%s)", name, table.get("uuid"))
        return table

    # ── transforms ───────────────────────────────────────────────────────

    async def list_transforms(
        self, org_uuid: str, project_uuid: str, table_uuid: str
    ) -> list[dict[str, Any]]:
        """List transforms on a table."""
        body = await self._get(
            f"/orgs/{org_uuid}/projects/{project_uuid}"
            f"/tables/{table_uuid}/transforms/"
        )
        return self._unwrap_list(body)

    async def create_transform(
        self,
        org_uuid: str,
        project_uuid: str,
        table_uuid: str,
        transform_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the HA state-history transform on a table.

        If *transform_body* is ``None`` the built-in
        ``HA_TRANSFORM_BODY`` definition is used.
        """
        body = transform_body or HA_TRANSFORM_BODY
        result = await self._post(
            f"/orgs/{org_uuid}/projects/{project_uuid}"
            f"/tables/{table_uuid}/transforms/",
            body,
        )
        transform = self._unwrap_single(result)
        _LOGGER.info(
            "Created Hydrolix transform '%s' on table %s (uuid=%s)",
            body.get("name"),
            table_uuid,
            transform.get("uuid"),
        )
        return transform

    # ── convenience: full provisioning in one call ───────────────────────

    async def ensure_project_table_transform(
        self,
        project_name: str,
        table_name: str,
    ) -> dict[str, str]:
        """Create (or find) a project + table + transform.

        Returns a dict with ``org_uuid``, ``project_uuid``,
        ``project_name``, ``table_uuid``, ``table_name``, and
        ``transform_name``.
        """
        org_uuid = await self.get_org_uuid()

        # ── project ──────────────────────────────────────────────────
        project_uuid: str | None = None
        for p in await self.list_projects(org_uuid):
            if p.get("name") == project_name:
                project_uuid = p["uuid"]
                _LOGGER.debug("Found existing project '%s'", project_name)
                break

        if project_uuid is None:
            proj = await self.create_project(
                org_uuid,
                project_name,
                description="Home Assistant history data",
            )
            project_uuid = proj["uuid"]

        # ── table ────────────────────────────────────────────────────
        table_uuid: str | None = None
        for t in await self.list_tables(org_uuid, project_uuid):
            if t.get("name") == table_name:
                table_uuid = t["uuid"]
                _LOGGER.debug("Found existing table '%s'", table_name)
                break

        if table_uuid is None:
            tbl = await self.create_table(
                org_uuid,
                project_uuid,
                table_name,
                description="Home Assistant state change history",
            )
            table_uuid = tbl["uuid"]

        # ── transform ────────────────────────────────────────────────
        existing_transforms = await self.list_transforms(
            org_uuid, project_uuid, table_uuid
        )
        has_ha_transform = any(
            t.get("name") == HA_TRANSFORM_NAME for t in existing_transforms
        )
        if not has_ha_transform:
            await self.create_transform(org_uuid, project_uuid, table_uuid)
        else:
            _LOGGER.debug("Transform '%s' already exists", HA_TRANSFORM_NAME)

        return {
            "org_uuid": org_uuid,
            "project_uuid": project_uuid,
            "project_name": project_name,
            "table_uuid": table_uuid,
            "table_name": table_name,
            "transform_name": HA_TRANSFORM_NAME,
        }
