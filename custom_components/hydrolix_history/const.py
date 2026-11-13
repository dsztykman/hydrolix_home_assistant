"""Constants for the Hydrolix History integration."""

DOMAIN = "hydrolix_history"

# Configuration keys - connection
CONF_HYDROLIX_HOST = "hydrolix_host"
CONF_HYDROLIX_TOKEN = "hydrolix_token"
CONF_HYDROLIX_USE_SSL = "hydrolix_use_ssl"

# Configuration keys - ingest target
CONF_HYDROLIX_PROJECT = "hydrolix_project"
CONF_HYDROLIX_TABLE = "hydrolix_table"

# Configuration keys - batching & filtering
CONF_BATCH_SIZE = "batch_size"
CONF_BATCH_INTERVAL = "batch_interval"
CONF_INCLUDE_DOMAINS = "include_domains"
CONF_EXCLUDE_DOMAINS = "exclude_domains"
CONF_INCLUDE_ENTITIES = "include_entities"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_INCLUDE_ENTITY_GLOBS = "include_entity_globs"
CONF_EXCLUDE_ENTITY_GLOBS = "exclude_entity_globs"
CONF_INCLUDE_DEVICE_CLASSES = "include_device_classes"
CONF_EXCLUDE_DEVICE_CLASSES = "exclude_device_classes"

# Defaults
DEFAULT_PROJECT = "homeassistant"
DEFAULT_TABLE = "state_history"
DEFAULT_BATCH_SIZE = 100
DEFAULT_BATCH_INTERVAL = 5  # seconds
DEFAULT_USE_SSL = True

# Sensor attributes
ATTR_EVENTS_SENT = "events_sent"
ATTR_EVENTS_DROPPED = "events_dropped"
ATTR_EVENTS_QUEUED = "events_queued"
ATTR_LAST_ERROR = "last_error"
ATTR_LAST_SENT = "last_sent"
ATTR_CONNECTED = "connected"
