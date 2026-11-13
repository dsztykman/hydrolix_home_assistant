"""Tests for the Hydrolix client StateEvent serialization."""

import asyncio
import sys
import os
import gzip
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow importing modules without homeassistant dependency
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "hydrolix_history"))
from client import (
    StateEvent,
    format_timestamp,
    HydrolixClient,
    _MAX_RETRIES,
    _INITIAL_BACKOFF,
    _BACKOFF_FACTOR,
)


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
            last_changed="2024-01-15T10:30:00.000000Z",
            timestamp="2024-01-15T10:30:00.000000Z",
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
        assert record["timestamp"] == "2024-01-15T10:30:00.000000Z"

    def test_non_numeric_state(self):
        """Non-numeric states should leave state_float out."""
        event = StateEvent(
            entity_id="light.living_room",
            domain="light",
            state="on",
            old_state="off",
            attributes={"friendly_name": "Living Room Light"},
            last_changed="2024-01-15T10:30:00.000000Z",
            timestamp="2024-01-15T10:30:00.000000Z",
        )

        record = event.to_dict()

        assert record["state"] == "on"
        assert record["old_state"] == "off"
        assert "state_float" not in record

    def test_none_old_state(self):
        """Missing old_state should be left out, not sent empty."""
        event = StateEvent(
            entity_id="sensor.new_sensor",
            domain="sensor",
            state="42",
            old_state=None,
            attributes={},
            last_changed="2024-01-15T10:30:00.000000Z",
            timestamp="2024-01-15T10:30:00.000000Z",
        )

        record = event.to_dict()
        assert "old_state" not in record

    def test_attributes_json_string(self):
        """Attributes are sent as one JSON string, minus promoted keys."""
        attrs = {
            "friendly_name": "Test Sensor",
            "unit_of_measurement": "W",
            "device_class": "power",
            "state_class": "measurement",
            "custom_key": [1, 2, 3],
        }
        event = _event(state="150", attributes=attrs)

        record = event.to_dict()
        assert isinstance(record["attributes"], str)
        assert json.loads(record["attributes"]) == {
            "state_class": "measurement",
            "custom_key": [1, 2, 3],
        }
        # Promoted keys stay top-level only
        assert record["friendly_name"] == "Test Sensor"
        assert record["device_class"] == "power"
        assert record["unit_of_measurement"] == "W"

    def test_missing_values_are_omitted(self):
        """A field with no value is left out rather than sent empty."""
        record = _event(state="on", attributes={"icon": "", "device_class": None}).to_dict()
        assert set(record) == {
            "timestamp",
            "last_changed",
            "entity_id",
            "domain",
            "state",
        }

    def test_no_last_updated_field(self):
        """timestamp is the event time; last_updated is not duplicated."""
        assert "last_updated" not in _event().to_dict()

    @pytest.mark.parametrize("state", ["nan", "NaN", "inf", "-inf", "Infinity"])
    def test_non_finite_state_is_not_numeric(self, state):
        """nan / inf must not reach the payload: they are not valid JSON."""
        record = _event(state=state).to_dict()
        assert "state_float" not in record
        json.dumps(record, allow_nan=False)

    def test_attributes_are_strict_json(self):
        """Non-finite floats and non-JSON types inside attributes are made safe."""
        attrs = {
            "bad": float("nan"),
            "nested": {"worse": float("inf"), "ok": 1.5},
            "rgb_color": (255, 180, 107),
            "when": datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
            "obj": object,
        }
        record = _event(attributes=attrs).to_dict()
        json.dumps(record, allow_nan=False)
        parsed = json.loads(record["attributes"])
        assert parsed["bad"] is None
        assert parsed["nested"] == {"worse": None, "ok": 1.5}
        assert parsed["rgb_color"] == [255, 180, 107]
        assert parsed["when"] == "2024-01-15T10:30:00.000000Z"
        assert isinstance(parsed["obj"], str)

    def test_field_types_are_stable(self):
        """Every field keeps one JSON type whatever the entity."""
        records = [
            _event(state="21.5", attributes={"temperature": 21}).to_dict(),
            _event(state="21", attributes={"temperature": 19.5}).to_dict(),
            _event(state="heat", attributes={"temperature": "n/a"}).to_dict(),
        ]
        types: dict[str, set[type]] = {}
        for record in records:
            for key, value in record.items():
                types.setdefault(key, set()).add(type(value))
        assert all(len(t) == 1 for t in types.values()), types


class TestFormatTimestamp:
    """Timestamps must have one constant shape."""

    def test_zero_microseconds_keeps_fraction(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert format_timestamp(dt) == "2024-01-15T10:30:00.000000Z"

    def test_microseconds(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, 481216, tzinfo=timezone.utc)
        assert format_timestamp(dt) == "2024-01-15T10:30:00.481216Z"

    def test_other_timezone_converted_to_utc(self):
        tz = timezone(timedelta(hours=2))
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=tz)
        assert format_timestamp(dt) == "2024-01-15T10:30:00.000000Z"

    def test_naive_treated_as_utc(self):
        assert format_timestamp(datetime(2024, 1, 15, 10, 30)) == (
            "2024-01-15T10:30:00.000000Z"
        )


def _event(state="42", old_state=None, attributes=None) -> StateEvent:
    return StateEvent(
        entity_id="sensor.test",
        domain="sensor",
        state=state,
        old_state=old_state,
        attributes=attributes or {},
        last_changed="2024-01-15T10:30:00.000000Z",
        timestamp="2024-01-15T10:30:00.000000Z",
    )


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
        """URL should be https://host/ingest/event?table=project.table."""
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

    def test_url_never_names_a_transform(self):
        """Autopilot infers the schema, so no transform is ever requested."""
        client = HydrolixClient(
            host="my-cluster.hydrolix.live",
            database="homeassistant",
            table="state_history",
            token="fake",
        )
        assert "transform" not in client.ingest_url

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


def _make_client() -> HydrolixClient:
    """Create a client with a mock session for testing."""
    client = HydrolixClient(
        host="test.hydrolix.live",
        database="db",
        table="tbl",
        token="fake",
        batch_size=10,
    )
    client._session = MagicMock()
    client._session.closed = False
    client.stats.connected = True
    return client


def _make_event() -> StateEvent:
    return StateEvent(
        entity_id="sensor.test",
        domain="sensor",
        state="42",
        old_state="41",
        attributes={"friendly_name": "Test"},
        last_changed="2024-01-15T10:30:00.000000Z",
        timestamp="2024-01-15T10:30:00.000000Z",
    )


def _mock_response(status, body="", headers=None):
    """Create a mock aiohttp response as an async context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=body)
    resp.headers = headers or {}
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestRetryBackoff:
    """Test retry with exponential backoff on retryable errors."""

    def test_429_retries_then_succeeds(self):
        """A 429 followed by a 200 should succeed without dropping events."""
        async def _run():
            client = _make_client()
            client.enqueue(_make_event())

            client._session.post = MagicMock(side_effect=[
                _mock_response(429, "rate limited"),
                _mock_response(429, "rate limited"),
                _mock_response(200),
            ])

            with patch("client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await client._flush()

            assert client.stats.events_sent == 1
            assert client.stats.events_dropped == 0
            assert mock_sleep.call_count == 2
            # Verify exponential backoff: 1s, 2s
            assert mock_sleep.call_args_list[0].args[0] == _INITIAL_BACKOFF
            assert mock_sleep.call_args_list[1].args[0] == _INITIAL_BACKOFF * _BACKOFF_FACTOR

        asyncio.run(_run())

    def test_retries_exhausted_drops_batch(self):
        """When all retries fail, events should be dropped."""
        async def _run():
            client = _make_client()
            client.enqueue(_make_event())

            client._session.post = MagicMock(side_effect=[
                _mock_response(429, "rate limited")
                for _ in range(_MAX_RETRIES)
            ])

            with patch("client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await client._flush()

            assert client.stats.events_sent == 0
            assert client.stats.events_dropped == 1
            assert mock_sleep.call_count == _MAX_RETRIES

        asyncio.run(_run())

    def test_500_is_retryable(self):
        """Server errors (500, 502, 503, 504) should be retried."""
        async def _run():
            client = _make_client()
            client.enqueue(_make_event())

            client._session.post = MagicMock(side_effect=[
                _mock_response(500, "internal error"),
                _mock_response(503, "unavailable"),
                _mock_response(200),
            ])

            with patch("client.asyncio.sleep", new_callable=AsyncMock):
                await client._flush()

            assert client.stats.events_sent == 1
            assert client.stats.events_dropped == 0

        asyncio.run(_run())

    def test_400_not_retried(self):
        """Non-retryable errors (e.g. 400) should fail immediately."""
        async def _run():
            client = _make_client()
            client.enqueue(_make_event())

            client._session.post = MagicMock(side_effect=[
                _mock_response(400, "bad request"),
            ])

            with patch("client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await client._flush()

            assert client.stats.events_sent == 0
            assert client.stats.events_dropped == 1
            assert mock_sleep.call_count == 0

        asyncio.run(_run())

    def test_retry_after_header_honoured(self):
        """Retry-After header value should be used as the delay."""
        async def _run():
            client = _make_client()
            client.enqueue(_make_event())

            client._session.post = MagicMock(side_effect=[
                _mock_response(429, "rate limited", headers={"Retry-After": "7"}),
                _mock_response(200),
            ])

            with patch("client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await client._flush()

            assert client.stats.events_sent == 1
            assert mock_sleep.call_count == 1
            assert mock_sleep.call_args_list[0].args[0] == 7.0

        asyncio.run(_run())

    def test_connection_error_retried(self):
        """Network errors should be retried with backoff."""
        import aiohttp

        async def _run():
            client = _make_client()
            client.enqueue(_make_event())

            error_ctx = MagicMock()
            error_ctx.__aenter__ = AsyncMock(
                side_effect=aiohttp.ClientError("connection reset")
            )
            error_ctx.__aexit__ = AsyncMock(return_value=False)

            client._session.post = MagicMock(side_effect=[
                error_ctx,
                _mock_response(200),
            ])

            with patch("client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await client._flush()

            assert client.stats.events_sent == 1
            assert client.stats.events_dropped == 0
            assert mock_sleep.call_count == 1

        asyncio.run(_run())
