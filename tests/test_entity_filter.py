"""Tests for the Hydrolix History entity filter."""

import sys
import os

# Allow importing modules without homeassistant dependency
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "hydrolix_history"
    ),
)
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

    # ── Device class filtering tests ──────────────────────────────────────

    def test_exclude_device_class(self):
        """Entities with excluded device classes should be filtered out."""
        f = EntityFilter(exclude_device_classes=["motion", "battery"])
        assert f.should_record("sensor.temp", device_class="temperature") is True
        assert f.should_record("binary_sensor.pir", device_class="motion") is False
        assert f.should_record("sensor.batt", device_class="battery") is False

    def test_include_device_class(self):
        """Only entities with included device classes should pass."""
        f = EntityFilter(include_device_classes=["temperature", "humidity"])
        assert f.should_record("sensor.temp", device_class="temperature") is True
        assert f.should_record("sensor.hum", device_class="humidity") is True
        assert f.should_record("sensor.batt", device_class="battery") is False

    def test_include_device_class_no_device_class_attr(self):
        """Entities without a device_class attribute are excluded when include is set."""
        f = EntityFilter(include_device_classes=["temperature"])
        assert f.should_record("sensor.temp", device_class="temperature") is True
        assert f.should_record("sensor.unknown") is False
        assert f.should_record("sensor.unknown", device_class=None) is False

    def test_exclude_device_class_no_device_class_attr(self):
        """Entities without a device_class attribute are not affected by exclude."""
        f = EntityFilter(exclude_device_classes=["motion"])
        assert f.should_record("binary_sensor.pir", device_class="motion") is False
        assert f.should_record("sensor.unknown") is True
        assert f.should_record("sensor.unknown", device_class=None) is True

    def test_device_class_exclude_overrides_include_domain(self):
        """Device class exclusion takes priority over domain inclusion."""
        f = EntityFilter(
            include_domains=["sensor"],
            exclude_device_classes=["battery"],
        )
        assert f.should_record("sensor.temp", device_class="temperature") is True
        assert f.should_record("sensor.batt", device_class="battery") is False

    def test_device_class_include_overrides_exclude_domain(self):
        """Device class inclusion takes priority over domain exclusion."""
        f = EntityFilter(
            exclude_domains=["sensor"],
            include_device_classes=["temperature"],
        )
        assert f.should_record("sensor.temp", device_class="temperature") is True
        assert f.should_record("sensor.batt", device_class="battery") is False

    def test_entity_include_overrides_device_class_exclude(self):
        """Explicit entity inclusion overrides device class exclusion."""
        f = EntityFilter(
            include_entities=["sensor.important_battery"],
            exclude_device_classes=["battery"],
        )
        assert (
            f.should_record("sensor.important_battery", device_class="battery") is True
        )
        assert f.should_record("sensor.other_battery", device_class="battery") is False

    def test_entity_exclude_overrides_device_class_include(self):
        """Explicit entity exclusion overrides device class inclusion."""
        f = EntityFilter(
            exclude_entities=["sensor.noisy_temp"],
            include_device_classes=["temperature"],
        )
        assert f.should_record("sensor.noisy_temp", device_class="temperature") is False
        assert f.should_record("sensor.good_temp", device_class="temperature") is True

    def test_glob_overrides_device_class(self):
        """Glob patterns take priority over device class filters."""
        f = EntityFilter(
            include_device_classes=["temperature"],
            exclude_entity_globs=["sensor.debug_*"],
        )
        assert f.should_record("sensor.debug_temp", device_class="temperature") is False
        assert f.should_record("sensor.good_temp", device_class="temperature") is True

    def test_full_priority_with_device_class(self):
        """Verify the complete priority chain including device class."""
        f = EntityFilter(
            include_domains=["sensor"],
            exclude_domains=["light"],
            include_entities=["light.important"],
            exclude_entities=["sensor.noisy"],
            include_entity_globs=["binary_sensor.door_*"],
            exclude_entity_globs=["sensor.debug_*"],
            include_device_classes=["temperature"],
            exclude_device_classes=["battery"],
        )
        # Priority 1: Explicit entity exclusion
        assert f.should_record("sensor.noisy", device_class="temperature") is False
        # Priority 2: Explicit entity inclusion
        assert f.should_record("light.important", device_class="battery") is True
        # Priority 3: Glob exclusion
        assert f.should_record("sensor.debug_test", device_class="temperature") is False
        # Priority 4: Glob inclusion
        assert (
            f.should_record("binary_sensor.door_front", device_class="battery") is True
        )
        # Priority 5: Device class exclusion
        assert f.should_record("sensor.batt", device_class="battery") is False
        # Priority 6: Device class inclusion
        assert f.should_record("climate.temp", device_class="temperature") is True
        # Priority 7: Domain exclusion
        assert f.should_record("light.bedroom") is False
        # Priority 8: Domain inclusion
        assert f.should_record("sensor.pressure") is True
        # Priority 9: No match with include filters set -> exclude
        assert f.should_record("climate.hvac") is False
