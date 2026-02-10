"""Tests for the Hydrolix History entity filter."""

import sys
import os

import pytest

# Allow importing modules without homeassistant dependency
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "hydrolix_history"))
from entity_filter import EntityFilter


class TestEntityFilter:
    """Test entity filtering logic."""

    def test_default_includes_all(self):
        """All entities should be included with no filters."""
        f = EntityFilter()
        assert f.should_record("sensor.temperature") is True
        assert f.should_record("light.living_room") is True
        assert f.should_record("automation.test") is True

    def test_exclude_domain(self):
        """Excluded domains should be filtered out."""
        f = EntityFilter(exclude_domains=["automation", "script"])
        assert f.should_record("sensor.temperature") is True
        assert f.should_record("automation.test") is False
        assert f.should_record("script.my_script") is False

    def test_include_domain_excludes_others(self):
        """When include domains are set, non-matching domains are excluded."""
        f = EntityFilter(include_domains=["sensor", "climate"])
        assert f.should_record("sensor.temperature") is True
        assert f.should_record("climate.hvac") is True
        assert f.should_record("light.living_room") is False

    def test_exclude_entity(self):
        """Specific entities can be excluded."""
        f = EntityFilter(exclude_entities=["sensor.date", "sensor.time"])
        assert f.should_record("sensor.date") is False
        assert f.should_record("sensor.time") is False
        assert f.should_record("sensor.temperature") is True

    def test_include_entity(self):
        """Specific entities can be included."""
        f = EntityFilter(include_entities=["sensor.temperature"])
        assert f.should_record("sensor.temperature") is True
        assert f.should_record("sensor.humidity") is False

    def test_exclude_entity_overrides_include_domain(self):
        """Entity exclusion takes priority over domain inclusion."""
        f = EntityFilter(
            include_domains=["sensor"],
            exclude_entities=["sensor.date"],
        )
        assert f.should_record("sensor.temperature") is True
        assert f.should_record("sensor.date") is False

    def test_include_entity_overrides_exclude_domain(self):
        """Entity inclusion takes priority over domain exclusion."""
        f = EntityFilter(
            exclude_domains=["automation"],
            include_entities=["automation.important"],
        )
        assert f.should_record("automation.important") is True
        assert f.should_record("automation.test") is False

    def test_exclude_glob(self):
        """Glob patterns can exclude entities."""
        f = EntityFilter(exclude_entity_globs=["sensor.weather_*"])
        assert f.should_record("sensor.weather_temperature") is False
        assert f.should_record("sensor.weather_humidity") is False
        assert f.should_record("sensor.living_room_temp") is True

    def test_include_glob(self):
        """Glob patterns can include entities."""
        f = EntityFilter(include_entity_globs=["sensor.*_temperature"])
        assert f.should_record("sensor.living_room_temperature") is True
        assert f.should_record("sensor.bedroom_temperature") is True
        assert f.should_record("sensor.humidity") is False

    def test_priority_order(self):
        """Verify the full priority chain."""
        f = EntityFilter(
            include_domains=["sensor"],
            exclude_domains=["light"],
            include_entities=["light.important"],
            exclude_entities=["sensor.noisy"],
            include_entity_globs=["binary_sensor.door_*"],
            exclude_entity_globs=["sensor.debug_*"],
        )
        # Explicit entity exclusion (priority 1)
        assert f.should_record("sensor.noisy") is False
        # Explicit entity inclusion (priority 2)
        assert f.should_record("light.important") is True
        # Glob exclusion (priority 3)
        assert f.should_record("sensor.debug_test") is False
        # Glob inclusion (priority 4)
        assert f.should_record("binary_sensor.door_front") is True
        # Domain exclusion (priority 5)
        assert f.should_record("light.bedroom") is False
        # Domain inclusion (priority 6)
        assert f.should_record("sensor.temperature") is True
        # No match with include filters set -> exclude (priority 7)
        assert f.should_record("climate.hvac") is False
