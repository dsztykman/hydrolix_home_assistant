"""Hydrolix async client for ingesting Home Assistant state data."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import math
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 50
_INITIAL_BACKOFF = 1.0  # seconds
_MAX_BACKOFF = 600.0  # seconds
_BACKOFF_FACTOR = 2.0


@dataclass
class HydrolixStats:
    """Statistics for the Hydrolix client."""

    events_sent: int = 0
    events_dropped: int = 0
    events_queued: int = 0
    last_error: str | None = None
    last_sent: datetime | None = None
    connected: bool = False


# Project, table and transform names end up in the ingest URL and in SQL.
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TRANSFORM_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_INGEST_PATH = "/ingest/event"


class IngestUrlError(ValueError):
    """An ingest URL could not be used. ``code`` names the reason."""

    def __init__(self, code: str) -> None:
        """Store the reason code, which doubles as a translation key."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IngestTarget:
    """The parts of an ingest URL."""

    host: str
    use_ssl: bool
    database: str
    table: str
    transform: str | None = None


def parse_ingest_url(value: str) -> IngestTarget:
    """Split ``https://host/ingest/event?table=project.table&transform=name``.

    ``transform`` is optional. The scheme defaults to ``https``. Raises
    ``IngestUrlError`` with one of ``invalid_url``, ``invalid_table`` or
    ``invalid_transform``.
    """
    url = value.strip()
    if "://" not in url:
        url = f"https://{url}"
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=False)
        host = parts.netloc
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as err:
        raise IngestUrlError("invalid_url") from err

    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or "@" in host
        or parts.path.rstrip("/") != _INGEST_PATH
        or parts.fragment
        or set(query) - {"table", "transform"}
        or any(len(values) != 1 for values in query.values())
    ):
        raise IngestUrlError("invalid_url")

    database, _, table = query.get("table", [""])[0].partition(".")
    if not _NAME_RE.fullmatch(database) or not _NAME_RE.fullmatch(table):
        raise IngestUrlError("invalid_table")

    transform = None
    if "transform" in query:
        transform = query["transform"][0]
        if not _TRANSFORM_RE.fullmatch(transform):
            raise IngestUrlError("invalid_transform")

    return IngestTarget(
        host=host.lower(),
        use_ssl=parts.scheme == "https",
        database=database,
        table=table,
        transform=transform,
    )


# Attributes sent as their own top-level field, so not repeated in ``attributes``.
_PROMOTED_ATTRIBUTES = ("friendly_name", "device_class", "unit_of_measurement", "icon")


def format_timestamp(value: datetime) -> str:
    """Format a datetime as UTC with a constant shape.

    Always ``YYYY-MM-DDTHH:MM:SS.ffffffZ``. ``datetime.isoformat()`` drops
    the fraction when microseconds are zero, which makes the format vary
    between events.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# Plain decimal or scientific notation only. ``float()`` alone would also
# accept "nan", "inf", "1_000" and surrounding whitespace.
_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def parse_number(value: str | None) -> float | None:
    """Return *value* as a finite float, or ``None`` if it is not a number."""
    if not isinstance(value, str) or not _NUMBER_RE.fullmatch(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


# ISO 8601 date, optionally followed by a time. Anchored on the date so
# bare times ("12:30") and compact forms ("20240115") are not matched.
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}.*)?")


def parse_time(value: str | None) -> str | None:
    """Return *value* as a formatted UTC timestamp, or ``None``.

    Accepts ISO 8601 datetimes and plain dates (midnight UTC). A datetime
    without an offset is taken as UTC.
    """
    if not isinstance(value, str) or not _DATETIME_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return format_timestamp(parsed)


def _put_state(record: dict[str, Any], key: str, value: str | None) -> None:
    """Store a state in the one field that matches its type.

    ``<key>_num`` for a number, ``<key>_time`` for a date or datetime,
    ``<key>`` for everything else.
    """
    if value is None or value == "":
        return
    number = parse_number(value)
    if number is not None:
        record[f"{key}_num"] = number
        return
    time = parse_time(value)
    if time is not None:
        record[f"{key}_time"] = time
        return
    record[key] = value


def _json_safe(value: Any) -> Any:
    """Convert a value into something that serialises as strict JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # NaN / Infinity are not valid JSON.
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return format_timestamp(value)
    return str(value)


@dataclass
class StateEvent:
    """Represents a Home Assistant state change event for Hydrolix ingestion."""

    entity_id: str
    domain: str
    state: str
    old_state: str | None
    attributes: dict[str, Any]
    last_changed: str  # see format_timestamp
    timestamp: str  # event time (HA last_updated), see format_timestamp

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dict suitable for Hydrolix JSON ingest.

        The record is shaped so the schema can be inferred without
        conflicts: every field keeps one type, numeric, time and text
        states go to separate fields, a field with no value is left out rather
        than sent empty, and ``attributes`` is a JSON string because its
        keys change type between entities.
        """
        record: dict[str, Any] = {
            "timestamp": self.timestamp,
            "last_changed": self.last_changed,
            "entity_id": self.entity_id,
            "domain": self.domain,
        }

        # A state goes to exactly one field: ``state_num`` when numeric,
        # ``state_time`` when a date or datetime, ``state`` otherwise.
        # ``state`` therefore never holds a value that looks like a number
        # or a timestamp, so no field can be inferred with a conflicting
        # type. Same split for the previous state.
        _put_state(record, "state", self.state)
        _put_state(record, "old_state", self.old_state)

        for key in _PROMOTED_ATTRIBUTES:
            value = self.attributes.get(key)
            if value is not None and value != "":
                record[key] = str(value)

        remaining = {
            str(k): _json_safe(v)
            for k, v in self.attributes.items()
            if k not in _PROMOTED_ATTRIBUTES
        }
        if remaining:
            record["attributes"] = json.dumps(
                remaining, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )

        return record


class HydrolixClient:
    """Async client for pushing state data to Hydrolix."""

    def __init__(
        self,
        host: str,
        database: str,
        table: str,
        token: str,
        use_ssl: bool = True,
        batch_size: int = 100,
        batch_interval: float = 5.0,
        transform: str | None = None,
    ) -> None:
        """Initialize the Hydrolix client."""
        self._host = host
        self._database = database
        self._table = table
        self._token = token
        self._use_ssl = use_ssl
        self._transform = transform or None
        self._batch_size = batch_size
        self._batch_interval = batch_interval

        self._queue: deque[StateEvent] = deque(maxlen=10000)
        self._session: aiohttp.ClientSession | None = None
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self.stats = HydrolixStats()

        scheme = "https" if use_ssl else "http"
        self._base_url = f"{scheme}://{host}"

    @property
    def ingest_url(self) -> str:
        """Build the Hydrolix ingest URL.

        Format: https://$cluster/ingest/event?table=project.table[&transform=name]

        Without a transform, the table's default applies: with Schema
        Intelligence (Autopilot) it accepts every event, and fields are
        promoted once enough data has built confidence in them. The
        project and table must already exist.
        """
        url = f"{self._base_url}{_INGEST_PATH}?table={self._database}.{self._table}"
        if self._transform:
            url += f"&transform={quote(self._transform, safe='')}"
        return url

    async def async_connect(self) -> bool:
        """Check that the Hydrolix cluster is reachable.

        Only reachability is tested. An ingest token cannot be verified
        without writing an event, so token or permission problems surface
        on the first flush (see ``stats.last_error``).
        """
        try:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=30)
                self._session = aiohttp.ClientSession(timeout=timeout)

            # No credentials are sent: this only proves the host answers.
            async with self._session.get(
                f"{self._base_url}/",
                ssl=self._use_ssl,
                allow_redirects=False,
            ) as response:
                # Any response (even 401/404) means the server is reachable
                self.stats.connected = True
                _LOGGER.info(
                    "Connected to Hydrolix at %s (status: %s)",
                    self._base_url,
                    response.status,
                )
                return True

        except aiohttp.ClientError as err:
            self.stats.connected = False
            self.stats.last_error = str(err)
            _LOGGER.error("Failed to connect to Hydrolix: %s", err)
            return False
        except Exception as err:  # noqa: BLE001
            self.stats.connected = False
            self.stats.last_error = str(err)
            _LOGGER.error("Unexpected error connecting to Hydrolix: %s", err)
            return False

    async def async_start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        _LOGGER.debug("Hydrolix flush loop started")

    async def async_stop(self) -> None:
        """Stop the flush loop and close the session."""
        self._running = False

        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Flush remaining events
        await self._flush()

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        _LOGGER.debug("Hydrolix client stopped")

    def enqueue(self, event: StateEvent) -> None:
        """Add a state event to the queue."""
        if len(self._queue) >= self._queue.maxlen:
            self.stats.events_dropped += 1
            _LOGGER.warning(
                "Hydrolix queue full (%d), dropping oldest event",
                self._queue.maxlen,
            )
        self._queue.append(event)
        self.stats.events_queued = len(self._queue)

    async def _flush_loop(self) -> None:
        """Periodically flush the event queue to Hydrolix."""
        while self._running:
            try:
                await asyncio.sleep(self._batch_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as err:  # noqa: BLE001
                self.stats.last_error = str(err)
                _LOGGER.error("Error in Hydrolix flush loop: %s", err)

    async def _flush(self) -> None:
        """Send queued events to Hydrolix."""
        if not self._queue:
            return

        if self._session is None or self._session.closed:
            await self.async_connect()
            if not self.stats.connected:
                return

        # Drain up to batch_size events
        batch: list[dict[str, Any]] = []
        while self._queue and len(batch) < self._batch_size:
            event = self._queue.popleft()
            batch.append(event.to_dict())

        if not batch:
            return

        self.stats.events_queued = len(self._queue)

        # Build the compressed payload once for all retry attempts
        ndjson_payload = "\n".join(json.dumps(record, default=str) for record in batch)
        raw_bytes = ndjson_payload.encode("utf-8")
        compressed = gzip.compress(raw_bytes)

        backoff = _INITIAL_BACKOFF

        for attempt in range(_MAX_RETRIES):
            try:
                headers = self._get_headers()
                headers["Content-Type"] = "application/json"
                headers["Content-Encoding"] = "gzip"

                async with self._session.post(
                    self.ingest_url,
                    data=compressed,
                    headers=headers,
                    ssl=self._use_ssl,
                ) as response:
                    if response.status in (200, 201, 204):
                        self.stats.events_sent += len(batch)
                        self.stats.last_sent = datetime.now(UTC)
                        self.stats.connected = True
                        self.stats.last_error = None
                        ratio = len(raw_bytes) / len(compressed) if compressed else 0
                        _LOGGER.debug(
                            "Sent %d events to Hydrolix (total: %d, "
                            "gzip: %d→%d bytes, %.1fx)",
                            len(batch),
                            self.stats.events_sent,
                            len(raw_bytes),
                            len(compressed),
                            ratio,
                        )
                        return

                    resp_body = await response.text()

                    if response.status in _RETRYABLE_STATUS_CODES:
                        # Honour Retry-After header if present
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except (ValueError, TypeError):
                                delay = backoff
                        else:
                            delay = backoff

                        delay = min(delay, _MAX_BACKOFF)
                        _LOGGER.warning(
                            "Hydrolix ingest returned %s, retrying in %.1fs "
                            "(attempt %d/%d): %s",
                            response.status,
                            delay,
                            attempt + 1,
                            _MAX_RETRIES,
                            resp_body[:200],
                        )
                        self.stats.last_error = (
                            f"HTTP {response.status}: {resp_body[:200]}"
                        )
                        await asyncio.sleep(delay)
                        backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)
                        continue

                    # Non-retryable error — drop the batch
                    self.stats.last_error = f"HTTP {response.status}: {resp_body[:200]}"
                    self.stats.events_dropped += len(batch)
                    _LOGGER.error(
                        "Hydrolix ingest failed (HTTP %s): %s",
                        response.status,
                        resp_body[:500],
                    )
                    return

            except aiohttp.ClientError as err:
                self.stats.connected = False
                self.stats.last_error = str(err)
                if attempt < _MAX_RETRIES - 1:
                    _LOGGER.warning(
                        "Hydrolix request failed, retrying in %.1fs "
                        "(attempt %d/%d): %s",
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                        err,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)
                    continue
                self.stats.events_dropped += len(batch)
                _LOGGER.error("Failed to send events to Hydrolix: %s", err)
                return

            except Exception as err:  # noqa: BLE001
                self.stats.last_error = str(err)
                self.stats.events_dropped += len(batch)
                _LOGGER.error("Unexpected error sending to Hydrolix: %s", err)
                return

        # All retries exhausted
        self.stats.events_dropped += len(batch)
        _LOGGER.error(
            "Hydrolix ingest failed after %d retries, dropping %d events",
            _MAX_RETRIES,
            len(batch),
        )

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers for Hydrolix API requests."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
