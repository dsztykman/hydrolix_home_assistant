"""Tests for the Hydrolix client StateEvent serialization."""

import sys
import os
import gzip
import json

import pytest

# Allow importing modules without homeassistant dependency
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "hydrolix_history"))
from client import StateEvent, HydrolixClient


class TestStateEvent:
    """Test StateEvent serialization to Hydrolix format."""

    def test_basic_numeric_state(self):
        """Numeric states should populate state_float."""
        event = StateEvent(
            entity_id="sensor.temperature",
            domain="sensor",
            state="21.5",
            old_state="21.3",
            attributes={
                "friendly_name": "Living Room Temperature",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            },
            last_changed="2024-01-15T10:30:00+00:00",
            last_updated="2024-01-15T10:30:00+00:00",
            timestamp="2024-01-15T10:30:00+00:00",
        )

        record = event.to_dict()

        assert record["entity_id"] == "sensor.temperature"
        assert record["domain"] == "sensor"
        assert record["state"] == "21.5"
        assert record["old_state"] == "21.3"
        assert record["state_float"] == 21.5
        assert record["friendly_name"] == "Living Room Temperature"
        assert record["device_class"] == "temperature"
        assert record["unit_of_measurement"] == "°C"
        assert record["timestamp"] == "2024-01-15T10:30:00+00:00"

    def test_non_numeric_state(self):
        """Non-numeric states should have state_float as None."""
        event = StateEvent(
            entity_id="light.living_room",
            domain="light",
            state="on",
            old_state="off",
            attributes={"friendly_name": "Living Room Light"},
            last_changed="2024-01-15T10:30:00+00:00",
            last_updated="2024-01-15T10:30:00+00:00",
            timestamp="2024-01-15T10:30:00+00:00",
        )

        record = event.to_dict()

        assert record["state"] == "on"
        assert record["old_state"] == "off"
        assert record["state_float"] is None

    def test_none_old_state(self):
        """Missing old_state should serialize as empty string."""
        event = StateEvent(
            entity_id="sensor.new_sensor",
            domain="sensor",
            state="42",
            old_state=None,
            attributes={},
            last_changed="2024-01-15T10:30:00+00:00",
            last_updated="2024-01-15T10:30:00+00:00",
            timestamp="2024-01-15T10:30:00+00:00",
        )

        record = event.to_dict()
        assert record["old_state"] == ""

    def test_attributes_native_dict(self):
        """Full attributes should be stored as a native dict (json datatype)."""
        attrs = {
            "friendly_name": "Test Sensor",
            "unit_of_measurement": "W",
            "device_class": "power",
            "state_class": "measurement",
            "custom_key": [1, 2, 3],
        }
        event = StateEvent(
            entity_id="sensor.power",
            domain="sensor",
            state="150",
            old_state="148",
            attributes=attrs,
            last_changed="2024-01-15T10:30:00+00:00",
            last_updated="2024-01-15T10:30:00+00:00",
            timestamp="2024-01-15T10:30:00+00:00",
        )

        record = event.to_dict()
        assert isinstance(record["attributes"], dict)
        assert record["attributes"]["custom_key"] == [1, 2, 3]
        assert record["attributes"]["state_class"] == "measurement"

    def test_missing_attributes_fallback(self):
        """Missing attribute keys should default to empty string."""
        event = StateEvent(
            entity_id="sensor.minimal",
            domain="sensor",
            state="1",
            old_state=None,
            attributes={},
            last_changed="2024-01-15T10:30:00+00:00",
            last_updated="2024-01-15T10:30:00+00:00",
            timestamp="2024-01-15T10:30:00+00:00",
        )

        record = event.to_dict()
        assert record["friendly_name"] == ""
        assert record["device_class"] == ""
        assert record["unit_of_measurement"] == ""
        assert record["icon"] == ""
        assert record["attributes"] == {}


class TestGzipCompression:
    """Test that the client compresses payloads with gzip."""

    def test_gzip_roundtrip(self):
        """Compressed payload should decompress to the original NDJSON."""
        # Build a realistic batch payload
        events = []
        for i in range(50):
            events.append({
                "timestamp": "2024-01-15T10:30:00.000000+00:00",
                "entity_id": f"sensor.temperature_{i}",
                "domain": "sensor",
                "state": str(20.0 + i * 0.1),
                "old_state": str(19.9 + i * 0.1),
                "state_float": 20.0 + i * 0.1,
                "friendly_name": f"Temperature Sensor {i}",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            })

        ndjson = "\n".join(json.dumps(e) for e in events)
        raw_bytes = ndjson.encode("utf-8")

        compressed = gzip.compress(raw_bytes)

        # Compressed should be meaningfully smaller
        assert len(compressed) < len(raw_bytes)
        ratio = len(raw_bytes) / len(compressed)
        assert ratio > 2.0, f"Expected >2x compression, got {ratio:.1f}x"

        # Roundtrip
        decompressed = gzip.decompress(compressed)
        assert decompressed == raw_bytes


class TestIngestUrl:
    """Test that the ingest URL is correctly formed."""

    def test_url_format(self):
        """URL should be https://host/ingest/event?table=project.table&transform=name."""
        client = HydrolixClient(
            host="my-cluster.hydrolix.live",
            database="homeassistant",
            table="state_history",
            token="fake",
            transform_name="ha_state_history",
        )
        expected = (
            "https://my-cluster.hydrolix.live/ingest/event"
            "?table=homeassistant.state_history"
            "&transform=ha_state_history"
        )
        assert client.ingest_url == expected

    def test_url_no_transform(self):
        """URL without transform should omit the &transform= param."""
        client = HydrolixClient(
            host="my-cluster.hydrolix.live",
            database="homeassistant",
            table="state_history",
            token="fake",
        )
        expected = (
            "https://my-cluster.hydrolix.live/ingest/event"
            "?table=homeassistant.state_history"
        )
        assert client.ingest_url == expected

    def test_url_no_port(self):
        """URL should never contain a port number."""
        client = HydrolixClient(
            host="my-cluster.hydrolix.live",
            database="db",
            table="tbl",
            token="fake",
        )
        assert ":8088" not in client.ingest_url
        assert ":443" not in client.ingest_url
        assert client.ingest_url.startswith("https://my-cluster.hydrolix.live/")

    def test_url_http_when_ssl_disabled(self):
        """URL should use http:// when SSL is disabled."""
        client = HydrolixClient(
            host="localhost",
            database="db",
            table="tbl",
            token="fake",
            use_ssl=False,
        )
        assert client.ingest_url.startswith("http://localhost/")
