-- ============================================================================
-- Hydrolix Table Schema for Home Assistant State History
-- ============================================================================
-- This schema defines the Hydrolix table structure for ingesting
-- Home Assistant state change events. Create this table in your
-- Hydrolix cluster before configuring the integration.
--
-- Usage:
--   1. Create the database (if it doesn't exist):
--      CREATE DATABASE IF NOT EXISTS homeassistant;
--
--   2. Create this table using Hydrolix's table management API or UI.
--      The schema below is provided as a reference for the transform
--      configuration.
-- ============================================================================

-- Hydrolix Transform Configuration (JSON)
-- Use this as the transform settings when creating the table via
-- the Hydrolix API or admin UI.

/*
{
  "name": "ha_state_history",
  "description": "Home Assistant state change events — auto-created by the Hydrolix History integration",
  "type": "json",
  "table": "homeassistant.state_history",
  "settings": {
    "is_default": true,
    "sql_transform": null,
    "format_details": {
      "flattening": {
        "active": false
      }
    }
  },
  "schema": [
    {
      "name": "timestamp",
      "datatype": {
        "type": "datetime",
        "primary": true,
        "format": "2006-01-02T15:04:05.000000Z07:00",
        "resolution": "ms"
      }
    },
    {
      "name": "entity_id",
      "datatype": {
        "type": "string",
        "index": true
      }
    },
    {
      "name": "domain",
      "datatype": {
        "type": "string",
        "index": true
      }
    },
    {
      "name": "state",
      "datatype": {
        "type": "string",
        "index": true
      }
    },
    {
      "name": "old_state",
      "datatype": {
        "type": "string",
        "index": true,
        "default": ""
      }
    },
    {
      "name": "state_float",
      "datatype": {
        "type": "double",
        "index": false,
        "default": "0"
      }
    },
    {
      "name": "last_changed",
      "datatype": {
        "type": "datetime",
        "format": "2006-01-02T15:04:05.000000Z07:00",
        "resolution": "ms",
        "index": true
      }
    },
    {
      "name": "last_updated",
      "datatype": {
        "type": "datetime",
        "format": "2006-01-02T15:04:05.000000Z07:00",
        "resolution": "ms",
        "index": true
      }
    },
    {
      "name": "friendly_name",
      "datatype": {
        "type": "string",
        "index": true,
        "default": ""
      }
    },
    {
      "name": "device_class",
      "datatype": {
        "type": "string",
        "index": true,
        "default": ""
      }
    },
    {
      "name": "unit_of_measurement",
      "datatype": {
        "type": "string",
        "index": true,
        "default": ""
      }
    },
    {
      "name": "icon",
      "datatype": {
        "type": "string",
        "index": true,
        "default": ""
      }
    },
    {
      "name": "attributes",
      "datatype": {
        "type": "json"
      }
    }
  ]
}
*/

-- ============================================================================
-- Example Queries (run against your Hydrolix cluster)
-- ============================================================================

-- Get the last 100 state changes across all entities
-- SELECT entity_id, domain, state, old_state, timestamp
-- FROM homeassistant.state_history
-- WHERE timestamp > now() - INTERVAL 1 HOUR
-- ORDER BY timestamp DESC
-- LIMIT 100;

-- Get temperature history for a specific sensor
-- SELECT timestamp, state_float as temperature, entity_id
-- FROM homeassistant.state_history
-- WHERE entity_id = 'sensor.living_room_temperature'
--   AND timestamp > now() - INTERVAL 24 HOURS
-- ORDER BY timestamp;

-- Get hourly average temperature
-- SELECT
--   toStartOfHour(timestamp) as hour,
--   avg(state_float) as avg_temp,
--   min(state_float) as min_temp,
--   max(state_float) as max_temp
-- FROM homeassistant.state_history
-- WHERE entity_id = 'sensor.living_room_temperature'
--   AND timestamp > now() - INTERVAL 7 DAYS
-- GROUP BY hour
-- ORDER BY hour;

-- Count state changes per domain in the last 24 hours
-- SELECT domain, count(*) as changes
-- FROM homeassistant.state_history
-- WHERE timestamp > now() - INTERVAL 24 HOURS
-- GROUP BY domain
-- ORDER BY changes DESC;

-- Find entities with the most frequent state changes
-- SELECT entity_id, count(*) as changes
-- FROM homeassistant.state_history
-- WHERE timestamp > now() - INTERVAL 1 HOUR
-- GROUP BY entity_id
-- ORDER BY changes DESC
-- LIMIT 20;

-- Binary sensor on/off duration analysis
-- SELECT
--   entity_id,
--   state,
--   min(timestamp) as first_seen,
--   max(timestamp) as last_seen,
--   count(*) as occurrences
-- FROM homeassistant.state_history
-- WHERE domain = 'binary_sensor'
--   AND timestamp > now() - INTERVAL 24 HOURS
-- GROUP BY entity_id, state
-- ORDER BY entity_id, state;
