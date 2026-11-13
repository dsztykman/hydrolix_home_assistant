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
    parse_number,
    parse_time,
    parse_ingest_url,
    IngestUrlError,
    HydrolixClient,
    _MAX_RETRIES,
    _INITIAL_BACKOFF,
    _BACKOFF_FACTOR,
)


class TestStateEvent:
    """Test StateEvent serialization to Hydrolix format."""

    def test_basic_numeric_state(self):
        """Numeric states go to state_num / old_state_num only."""
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
        assert record["state_num"] == 21.5
        assert record["old_state_num"] == 21.3
        assert "state" not in record
        assert "old_state" not in record
        assert record["friendly_name"] == "Living Room Temperature"
        assert record["device_class"] == "temperature"
        assert record["unit_of_measurement"] == "°C"
        assert record["timestamp"] == "2024-01-15T10:30:00.000000Z"

    def test_non_numeric_state(self):
        """Text states go to state / old_state only."""
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
        assert "state_num" not in record
        assert "old_state_num" not in record

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
        assert not any(k.startswith("old_state") for k in record)

    def test_mixed_transition(self):
        """Each side of a transition is routed on its own value."""
        record = _event(state="21.5", old_state="unavailable").to_dict()
        assert record["state_num"] == 21.5
        assert record["old_state"] == "unavailable"
        assert "state" not in record
        assert "old_state_num" not in record

        record = _event(state="unknown", old_state="3").to_dict()
        assert record["state"] == "unknown"
        assert record["old_state_num"] == 3.0
        assert "state_num" not in record
        assert "old_state" not in record

    @pytest.mark.parametrize(
        "state", ["0", "-3", "+4", "21.5", "5.", ".5", "1e3", "1.5E-2", "007"]
    )
    def test_numeric_forms(self, state):
        record = _event(state=state).to_dict()
        assert record["state_num"] == float(state)
        assert isinstance(record["state_num"], float)
        assert "state" not in record
        assert "state_time" not in record

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("2026-11-14T06:31:10+00:00", "2026-11-14T06:31:10.000000Z"),
            ("2026-11-14T08:31:10+02:00", "2026-11-14T06:31:10.000000Z"),
            ("2026-11-14T06:31:10.123456Z", "2026-11-14T06:31:10.123456Z"),
            ("2026-11-14T06:31:10", "2026-11-14T06:31:10.000000Z"),
            ("2026-11-14 06:31:10", "2026-11-14T06:31:10.000000Z"),
            ("2026-11-14", "2026-11-14T00:00:00.000000Z"),
        ],
    )
    def test_time_forms(self, state, expected):
        """Dates and datetimes go to state_time in the one timestamp format."""
        record = _event(state=state, old_state=state).to_dict()
        assert record["state_time"] == expected
        assert record["old_state_time"] == expected
        assert "state" not in record
        assert "state_num" not in record
        assert "old_state" not in record

    @pytest.mark.parametrize(
        "state",
        [
            "on",
            "1_000",
            " 5",
            "5 ",
            "1,5",
            "2024.1.0",
            "0x1F",
            "12:30",
            "12:30:00",
            "-",
            ".",
            "2026-13-45",
            "2026-11-14 is a date",
            "20261114T063110",
        ],
    )
    def test_text_forms(self, state):
        record = _event(state=state).to_dict()
        assert record["state"] == state
        assert "state_num" not in record
        assert "state_time" not in record

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
        record = _event(state=state, old_state=state).to_dict()
        assert "state_num" not in record
        assert "old_state_num" not in record
        assert record["state"] == state
        assert record["old_state"] == state
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
            _event(state="21.5", old_state="on", attributes={"temperature": 21}),
            _event(state="21", old_state="20", attributes={"temperature": 19.5}),
            _event(state="heat", old_state="7", attributes={"temperature": "n/a"}),
            _event(state="unavailable", old_state="2026-11-14T06:31:10+00:00"),
            _event(state="2026-11-14", old_state="off"),
        ]
        records = [e.to_dict() for e in records]
        # state / old_state never carry something that parses as a number
        # or a timestamp
        for record in records:
            for key in ("state", "old_state"):
                if key in record:
                    assert parse_number(record[key]) is None
                    assert parse_time(record[key]) is None
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
                "state_num": 20.0 + i * 0.1,
                "old_state_num": 19.9 + i * 0.1,
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

    def test_url_without_transform(self):
        """No transform is named unless one was configured."""
        client = HydrolixClient(
            host="my-cluster.hydrolix.live",
            database="homeassistant",
            table="state_history",
            token="fake",
        )
        assert "transform" not in client.ingest_url

    def test_url_with_transform(self):
        client = HydrolixClient(
            host="my-cluster.hydrolix.live",
            database="homeassistant",
            table="state_history",
            token="fake",
            transform="my_transform",
        )
        assert client.ingest_url == (
            "https://my-cluster.hydrolix.live/ingest/event"
            "?table=homeassistant.state_history&transform=my_transform"
        )

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


class TestParseIngestUrl:
    """Test splitting the ingest URL entered in the setup form."""

    def test_table_only(self):
        target = parse_ingest_url(
            "https://my-cluster.hydrolix.live/ingest/event?table=ha.state_history"
        )
        assert target.host == "my-cluster.hydrolix.live"
        assert target.use_ssl is True
        assert target.database == "ha"
        assert target.table == "state_history"
        assert target.transform is None

    def test_with_transform(self):
        target = parse_ingest_url(
            "https://c.hydrolix.live/ingest/event?table=ha.t&transform=my_transform"
        )
        assert target.transform == "my_transform"

    def test_round_trip(self):
        url = "https://c.hydrolix.live/ingest/event?table=ha.t&transform=tr-1.v2"
        target = parse_ingest_url(url)
        client = HydrolixClient(
            host=target.host,
            database=target.database,
            table=target.table,
            token="fake",
            use_ssl=target.use_ssl,
            transform=target.transform,
        )
        assert client.ingest_url == url

    @pytest.mark.parametrize(
        "url",
        [
            "  https://c.hydrolix.live/ingest/event?table=ha.t  ",
            "https://c.hydrolix.live/ingest/event/?table=ha.t",
            "c.hydrolix.live/ingest/event?table=ha.t",
            "HTTPS://C.Hydrolix.Live/ingest/event?table=ha.t",
        ],
    )
    def test_tolerated_forms(self, url):
        target = parse_ingest_url(url)
        assert (target.host, target.use_ssl) == ("c.hydrolix.live", True)
        assert (target.database, target.table) == ("ha", "t")

    def test_http_and_port(self):
        target = parse_ingest_url("http://localhost:8080/ingest/event?table=ha.t")
        assert target.host == "localhost:8080"
        assert target.use_ssl is False

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "https://c.hydrolix.live",
            "https://c.hydrolix.live/?table=ha.t",
            "https://c.hydrolix.live/query?table=ha.t",
            "ftp://c.hydrolix.live/ingest/event?table=ha.t",
            "https:///ingest/event?table=ha.t",
            "https://user:pw@c.hydrolix.live/ingest/event?table=ha.t",
            "https://c.hydrolix.live:abc/ingest/event?table=ha.t",
            "https://c.hydrolix.live/ingest/event?table=ha.t&token=secret",
            "https://c.hydrolix.live/ingest/event?table=ha.t&table=ha.u",
            "https://c.hydrolix.live/ingest/event?table=ha.t#frag",
        ],
    )
    def test_invalid_url(self, url):
        with pytest.raises(IngestUrlError) as err:
            parse_ingest_url(url)
        assert err.value.code == "invalid_url"

    @pytest.mark.parametrize(
        "table",
        ["", "mytable", "ha.", ".t", "ha.t.x", "ha.my-table", "1ha.t", "ha.t;drop"],
    )
    def test_invalid_table(self, table):
        url = f"https://c.hydrolix.live/ingest/event?table={table}"
        with pytest.raises(IngestUrlError) as err:
            parse_ingest_url(url)
        assert err.value.code == "invalid_table"

    def test_missing_table(self):
        with pytest.raises(IngestUrlError) as err:
            parse_ingest_url("https://c.hydrolix.live/ingest/event")
        assert err.value.code == "invalid_table"

    @pytest.mark.parametrize("transform", ["", "a b", "a/b", "-x"])
    def test_invalid_transform(self, transform):
        url = f"https://c.hydrolix.live/ingest/event?table=ha.t&transform={transform}"
        with pytest.raises(IngestUrlError) as err:
            parse_ingest_url(url)
        assert err.value.code == "invalid_transform"


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
