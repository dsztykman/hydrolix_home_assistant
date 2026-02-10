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

### HACS (Recommended)

1. Open HACS in your Home Assistant UI.
2. Go to **Integrations** → click the **⋮** menu → **Custom repositories**.
3. Add `https://github.com/dsztykman/hydrolix_home_assistant` as an **Integration**.
4. Search for **Hydrolix History** and install it.
5. Restart Home Assistant.

### Manual

1. Copy the `custom_components/hydrolix_history/` directory to your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

## Configuration

### Add the Integration (auto-provisions everything)

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **Hydrolix History**.

The setup wizard walks you through three steps:

#### Step 1 — Connect

| Field | Description |
|---|---|
| **Host** | Your Hydrolix cluster hostname (e.g., `my-cluster.hydrolix.live`) |
| **API / Bearer Token** | Token with **config + ingest** permissions |
| **Use SSL** | Enable for production clusters (default `true`) |

The integration calls `GET /config/v1/orgs/` to verify the token and discover your org UUID.

#### Step 2 — Project

Choose **Use existing project** and pick from the dropdown, **or** choose **Create new project** and type a name. The project name becomes the database name in SQL queries (e.g., `SELECT ... FROM homeassistant.state_history`).

#### Step 3 — Table

Choose **Use existing table** or **Create new table**. When a table is created (or selected), the integration **automatically provisions the write transform** (`ha_state_history`) with the full Home Assistant schema — no manual API calls or JSON files needed.

The auto-created transform includes:

| Column | Type | Indexed | Description |
|---|---|---|---|
| `timestamp` | `datetime` (primary) | ✅ | When the state change occurred (Go fmt: `2006-01-02T15:04:05…`) |
| `entity_id` | `string` | ✅ | e.g., `sensor.living_room_temperature` |
| `domain` | `string` | ✅ | e.g., `sensor`, `light`, `climate` |
| `state` | `string` | ✅ | The new state value |
| `old_state` | `string` | ✅ | The previous state value |
| `state_float` | `double` | | Numeric parse of `state` (0 if non-numeric) |
| `last_changed` | `datetime` | ✅ | HA last_changed timestamp |
| `last_updated` | `datetime` | ✅ | HA last_updated timestamp |
| `friendly_name` | `string` | ✅ | Human-readable entity name |
| `device_class` | `string` | ✅ | e.g., `temperature`, `humidity` |
| `unit_of_measurement` | `string` | ✅ | e.g., `°C`, `%`, `W` |
| `icon` | `string` | ✅ | MDI icon name |
| `attributes` | `json` | | Full entity attributes as native JSON |

The transform is marked as the **default** transform for the table, so no `x-hdx-transform` header is needed at ingest time.

### Provisioning Flow (what happens behind the scenes)

```
Config Flow                        Hydrolix Config API
─────────────────                  ───────────────────
Step 1: host/token/ssl  ────────▶  GET  /config/v1/orgs/
                                   (verify token, get org_uuid)
                        ◀────────  org_uuid

Step 2: project         ────────▶  GET  /config/v1/orgs/{org}/projects/
                                   (list existing projects)
  [create new]          ────────▶  POST /config/v1/orgs/{org}/projects/
                        ◀────────  project_uuid

Step 3: table           ────────▶  GET  .../projects/{proj}/tables/
                                   (list existing tables)
  [create new]          ────────▶  POST .../projects/{proj}/tables/
                        ◀────────  table_uuid

  [auto-transform]      ────────▶  GET  .../tables/{tbl}/transforms/
                                   (check if ha_state_history exists)
  [create if missing]   ────────▶  POST .../tables/{tbl}/transforms/
                                   (full schema + settings)
                        ◀────────  transform_uuid

Done → streaming begins via POST https://$cluster/ingest/event?table=project.table&transform=ha_state_history
```

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
  avg(state_float) AS avg_temp
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
  max(state_float) - min(state_float) AS daily_kwh
FROM homeassistant.state_history
WHERE entity_id = 'sensor.energy_total'
  AND timestamp > now() - INTERVAL 30 DAYS
GROUP BY day
ORDER BY day;
```

## YAML Configuration (Advanced)

For users who prefer YAML over the UI config flow — note that the UI wizard handles project/table/transform creation automatically. YAML is intended for setups where resources were already provisioned externally.

```yaml
hydrolix_history:
  hydrolix_host: my-cluster.hydrolix.live
  hydrolix_token: !secret hydrolix_token
  hydrolix_project: homeassistant
  hydrolix_table: state_history
  hydrolix_use_ssl: true
  batch_size: 100
  batch_interval: 5
  exclude_domains:
    - automation
    - script
    - persistent_notification
  exclude_entities:
    - sensor.date
    - sensor.time
```

## Troubleshooting

### Events not arriving in Hydrolix

1. Check the `sensor.hydrolix_history_connection_status` sensor.
2. Look at `sensor.hydrolix_history_last_error` for details.
3. Verify the table exists in your Hydrolix cluster.
4. Ensure your bearer token has ingest permissions.

### High queue depth

If `events_queued` keeps growing, your Hydrolix cluster may be slow to ingest. Try:
- Increasing `batch_size` to send larger payloads.
- Increasing `batch_interval` to reduce request frequency.
- Excluding noisy domains like `automation` or `script`.

### SSL/TLS errors

If you're connecting to a development cluster without valid TLS, set **Use SSL** to `false`.

## Contributing

Contributions are welcome! Please open an issue or PR on the [GitHub repository](https://github.com/dsztykman/hydrolix_home_assistant).

## License

This project is licensed under the Apache 2.0 License.
