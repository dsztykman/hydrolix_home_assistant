"""Entity filtering for Hydrolix History integration."""

from __future__ import annotations

import fnmatch
import logging

_LOGGER = logging.getLogger(__name__)


class EntityFilter:
    """Filter entities based on domain, entity_id, glob patterns, and device class."""

    def __init__(
        self,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        include_entities: list[str] | None = None,
        exclude_entities: list[str] | None = None,
        include_entity_globs: list[str] | None = None,
        exclude_entity_globs: list[str] | None = None,
        include_device_classes: list[str] | None = None,
        exclude_device_classes: list[str] | None = None,
    ) -> None:
        """Initialize the entity filter."""
        self._include_domains = set(include_domains or [])
        self._exclude_domains = set(exclude_domains or [])
        self._include_entities = set(include_entities or [])
        self._exclude_entities = set(exclude_entities or [])
        self._include_entity_globs = list(include_entity_globs or [])
        self._exclude_entity_globs = list(exclude_entity_globs or [])
        self._include_device_classes = set(include_device_classes or [])
        self._exclude_device_classes = set(exclude_device_classes or [])

        self._has_include = bool(
            self._include_domains
            or self._include_entities
            or self._include_entity_globs
            or self._include_device_classes
        )

    def should_record(self, entity_id: str, device_class: str | None = None) -> bool:
        """Determine whether an entity should be recorded to Hydrolix.

        Filtering logic (same as InfluxDB/Recorder):
        1. If explicitly excluded by entity_id -> exclude
        2. If explicitly included by entity_id -> include
        3. If excluded by glob pattern -> exclude
        4. If included by glob pattern -> include
        5. If excluded by device_class -> exclude
        6. If included by device_class -> include
        7. If excluded by domain -> exclude
        8. If included by domain -> include
        9. If any include filter is set but entity didn't match -> exclude
        10. Otherwise -> include
        """
        domain = entity_id.split(".", 1)[0]

        # 1. Explicit entity exclusion takes priority
        if entity_id in self._exclude_entities:
            return False

        # 2. Explicit entity inclusion
        if entity_id in self._include_entities:
            return True

        # 3. Glob exclusion
        for pattern in self._exclude_entity_globs:
            if fnmatch.fnmatch(entity_id, pattern):
                return False

        # 4. Glob inclusion
        for pattern in self._include_entity_globs:
            if fnmatch.fnmatch(entity_id, pattern):
                return True

        # 5. Device class exclusion
        if device_class and device_class in self._exclude_device_classes:
            return False

        # 6. Device class inclusion
        if device_class and device_class in self._include_device_classes:
            return True

        # 7. Domain exclusion
        if domain in self._exclude_domains:
            return False

        # 8. Domain inclusion
        if domain in self._include_domains:
            return True

        # 9. If any include filter was set but we didn't match, exclude
        if self._has_include:
            return False

        # 10. Default: include
        return True
