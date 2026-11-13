# Hydrolix History — Home Assistant Integration

[![HACS Compatible](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

Stream your Home Assistant state history to [Hydrolix](https://hydrolix.io), a cloud-native, high-performance streaming analytics database. Keep years of sensor data with blazing-fast queries — no more purging your recorder database.

This integration runs **alongside** the built-in recorder — it doesn't replace it. The recorder handles the UI's short-term history panel, while Hydrolix stores long-term data for analytics, dashboards, and deep queries.

## Architecture

```
Home Assistant                          Hydrolix Cluster
──────────────                          ────────────────

State Change Event
       │
       ▼
 Entity Filter ──── include/exclude by domain, entity, glob
       │
       ▼
  Event Queue ───── batches events (configurable size/interval)
       │
       ▼                     HTTP POST
  Turbine Ingest ──────────────────────▶ state_history table
  (Hydrolix Ingest)                      (Hydrolix SQL)

 Diagnostic Sensors
  · events sent/dropped/queued
  · connection status
  · last error
```

## Installation

### Marketplace / HACS (Recommended)

Home Assistant 2026.11 and later ship HACS as the built-in **Marketplace**. Hydrolix History is not in the default catalogue, so add it as a custom repository:

1. Open **Settings** → **Marketplace** (or HACS on older versions).
2. Open **Custom repositories**.
3. Add `https://github.com/dsztykman/hydrolix_home_assistant` as an **Integration**.
4. Search for **Hydrolix History** and install it.
5. Restart Home Assistant.

### Manual

1. Copy the `custom_components/hydrolix_history/` directory to your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

## Configuration

### Before you start

In the Hydrolix console:

1. Create the project and table you want to stream into (**Data pipelines**). They must exist before any data is sent.
2. Create an **ingest token** for that table. This is a service-account token with ingest permission. It is shown once, so copy it.

The integration does not create projects, tables or transforms. It only sends events. With **Schema Intelligence** (formerly Autopilot), the table already has a transform that accepts every event by default. It then waits until it has seen enough data to be confident about a field before promoting it, and updates the transform automatically.

This means fields do not all appear straight away. A field that is rare in your data takes longer to be promoted than one present in every event.

If a field has conflicting values (for example, a number in some events and text in others), Schema Intelligence does not guess. It asks for a human review in the Hydrolix console.

### Add the Integration

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **Hydrolix History**.
3. Fill in the single setup form:

| Field | Description |
|---|---|
| **Ingest URL** | The ingest URL of your table (see below) |
| **Ingest Token** | Service-account token with ingest permission |

The ingest URL names the cluster, the project and the table:

```
https://my-cluster.hydrolix.live/ingest/event?table=myproject.mytable
```

- `table` is required and must be `project.table`.
- `transform` is optional. Add `&transform=mytransform` to use a specific transform. Without it, the table's default transform applies, which is the one managed by Schema Intelligence.
- Use `http://` only for a development cluster without TLS.

Setup only checks that the cluster is reachable. A wrong or expired token shows up in `sensor.hydrolix_history_last_error` after the first flush.

### What is sent

Events are posted as gzip-compressed NDJSON:

```
POST https://$cluster/ingest/event?table=project.table[&transform=name]
Authorization: Bearer <ingest token>
Content-Type: application/json
Content-Encoding: gzip
```

A transform is named only if the ingest URL you entered has one. Each event carries these fields:

| Field | Type | Always present | Description |
|---|---|---|---|
| `timestamp` | datetime | Yes | Event time (HA `last_updated`) |
| `last_changed` | datetime | Yes | When the state value itself last changed |
| `entity_id` | string | Yes | e.g., `sensor.living_room_temperature` |
| `domain` | string | Yes | e.g., `sensor`, `light`, `climate` |
| `state` | string | One of three | The new state, when it is text (`on`, `heat`, `unavailable`) |
| `state_num` | number | One of three | The new state, when it is a number |
| `state_time` | datetime | One of three | The new state, when it is a date or datetime |
| `old_state` | string | No | The previous state, when it is text |
| `old_state_num` | number | No | The previous state, when it is a number |
| `old_state_time` | datetime | No | The previous state, when it is a date or datetime |
| `friendly_name` | string | No | Human-readable entity name |
| `device_class` | string | No | e.g., `temperature`, `humidity` |
| `unit_of_measurement` | string | No | e.g., `°C`, `%`, `W` |
| `icon` | string | No | MDI icon name |
| `attributes` | string (JSON) | No | All other entity attributes, as a JSON string |

Example events:

```json
{"timestamp": "2026-11-13T12:45:03.481216Z", "last_changed": "2026-11-13T12:45:03.481216Z", "entity_id": "sensor.living_room_temperature", "domain": "sensor", "state_num": 21.5, "old_state_num": 21.3, "friendly_name": "Living Room Temperature", "device_class": "temperature", "unit_of_measurement": "°C", "attributes": "{\"state_class\":\"measurement\"}"}
{"timestamp": "2026-11-13T12:45:03.481216Z", "last_changed": "2026-11-13T12:44:10.002113Z", "entity_id": "climate.hallway", "domain": "climate", "state": "heat", "old_state": "unavailable", "friendly_name": "Hallway", "attributes": "{\"hvac_modes\":[\"off\",\"heat\"],\"current_temperature\":19.5,\"temperature\":21,\"hvac_action\":\"heating\"}"}
{"timestamp": "2026-11-13T12:45:03.481216Z", "last_changed": "2026-11-13T12:45:03.481216Z", "entity_id": "sensor.sun_next_dawn", "domain": "sensor", "state_time": "2026-11-14T06:31:10.000000Z", "old_state_time": "2026-11-13T06:29:48.000000Z", "friendly_name": "Sun Next dawn", "device_class": "timestamp"}
```

The payload is shaped so Schema Intelligence can infer it without conflicts:

- **One type per field.** Each state goes to exactly one of `state` (text), `state_num` (number) or `state_time` (date or datetime). `state` never holds a value that looks like a number or a timestamp. The previous state is split the same way.
- **No empty placeholders.** A field with no value is left out, not sent as `""` or `null`.
- **One timestamp format.** Always UTC, `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- **`attributes` is a JSON string.** Attribute keys change type between entities (a `temperature` can be `21`, `19.5` or missing), which would cause field conflicts if sent as an object. Query it with JSON functions, for example `JSONExtractFloat(attributes, 'current_temperature')`.

### Upgrading from 0.1.x

Earlier versions created the project, table and an `ha_state_history` transform through the Config API, and named that transform on every request. That transform was created as the table's default, so the cluster still applies it when no transform is named.

The payload has also changed, which affects tables that still use the old fixed transform:

- `last_updated` is no longer sent. `timestamp` now carries that value.
- `attributes` is now a JSON string, where the old transform declared a `json` column.
- Empty strings and `null` values are no longer sent.
- `state` and `old_state` now hold text only. Numbers go to `state_num` / `old_state_num` (0.2.0 used `state_float`), and dates or datetimes go to `state_time` / `old_state_time`.

Stream into a new table if you want Schema Intelligence to manage the schema from the start.

### Configure Filtering (Optional)

After setup, click **Configure** on the integration card to tune:

- **Batch Size**: Events per flush (default 100)
- **Batch Interval**: Seconds between flushes (default 5)
- **Include/Exclude Domains**: e.g., `sensor, climate` or `automation, script`
- **Include/Exclude Entities**: Specific entity IDs

#### Filtering Logic

The filter follows the same precedence as InfluxDB and the recorder:

1. Explicitly excluded entity → **exclude**
2. Explicitly included entity → **include**
3. Glob pattern exclusion → **exclude**
4. Glob pattern inclusion → **include**
5. Domain exclusion → **exclude**
6. Domain inclusion → **include**
7. If any include filter is set but no match → **exclude**
8. Default → **include**

## Diagnostic Sensors

The integration creates diagnostic sensors to monitor pipeline health:

| Sensor | Description |
|---|---|
| `sensor.hydrolix_history_events_sent` | Total events successfully sent |
| `sensor.hydrolix_history_events_dropped` | Events lost due to errors |
| `sensor.hydrolix_history_events_queued` | Events waiting in the buffer |
| `sensor.hydrolix_history_connection_status` | `connected` or `disconnected` |
| `sensor.hydrolix_history_last_error` | Last error message |

## Example Queries

Once data is flowing, query it from any Hydrolix SQL-compatible client:

```sql
-- Average temperature over the last 24 hours, per hour
SELECT
  toStartOfHour(timestamp) AS hour,
  avg(state_num) AS avg_temp
FROM homeassistant.state_history
WHERE entity_id = 'sensor.living_room_temperature'
  AND timestamp > now() - INTERVAL 24 HOURS
GROUP BY hour
ORDER BY hour;
```

```sql
-- Most active entities in the last hour
SELECT entity_id, count(*) AS changes
FROM homeassistant.state_history
WHERE timestamp > now() - INTERVAL 1 HOUR
GROUP BY entity_id
ORDER BY changes DESC
LIMIT 20;
```

```sql
-- Daily energy consumption trend
SELECT
  toDate(timestamp) AS day,
  max(state_num) - min(state_num) AS daily_kwh
FROM homeassistant.state_history
WHERE entity_id = 'sensor.energy_total'
  AND timestamp > now() - INTERVAL 30 DAYS
GROUP BY day
ORDER BY day;
```

## Troubleshooting

### Events not arriving in Hydrolix

1. Check the `sensor.hydrolix_history_connection_status` sensor.
2. Look at `sensor.hydrolix_history_last_error` for details.
3. Check that the ingest token is valid, not expired, and has ingest permission on the project or table.
4. Check in the Hydrolix console that the table exists.

### A field is missing from the table

Schema Intelligence promotes a field only once it has seen enough data to be confident about it. Events are accepted from the first request, so wait for more data to arrive and check the field's status in the Hydrolix console.

If the field is waiting for review, it has conflicting values across events. Resolve the review in the console. The integration keeps one type per field to avoid this, so a review request usually means other data is being sent to the same table.

### High queue depth

If `events_queued` keeps growing, your Hydrolix cluster may be slow to ingest. Try:
- Increasing `batch_size` to send larger payloads.
- Increasing `batch_interval` to reduce request frequency.
- Excluding noisy domains like `automation` or `script`.

### SSL/TLS errors

If you're connecting to a development cluster without valid TLS, use `http://` in the ingest URL.

## Contributing

Contributions are welcome! Please open an issue or PR on the [GitHub repository](https://github.com/dsztykman/hydrolix_home_assistant).

## License

This project is licensed under the Apache 2.0 License.
