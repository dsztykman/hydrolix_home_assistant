"""Constants for the Hydrolix History integration."""

DOMAIN = "hydrolix_history"

# Configuration keys - connection
CONF_HYDROLIX_HOST = "hydrolix_host"
CONF_HYDROLIX_TOKEN = "hydrolix_token"
CONF_HYDROLIX_USE_SSL = "hydrolix_use_ssl"

# Configuration keys - project / table / transform (stored after provisioning)
CONF_HYDROLIX_PROJECT = "hydrolix_project"
CONF_HYDROLIX_TABLE = "hydrolix_table"
CONF_HYDROLIX_DATABASE = (
    "hydrolix_database"  # kept for backward compat (= project name)
)
CONF_ORG_UUID = "org_uuid"
CONF_PROJECT_UUID = "project_uuid"
CONF_TABLE_UUID = "table_uuid"
CONF_TRANSFORM_NAME = "transform_name"

# Configuration keys - batching & filtering
CONF_BATCH_SIZE = "batch_size"
CONF_BATCH_INTERVAL = "batch_interval"
CONF_INCLUDE_DOMAINS = "include_domains"
CONF_EXCLUDE_DOMAINS = "exclude_domains"
CONF_INCLUDE_ENTITIES = "include_entities"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_INCLUDE_ENTITY_GLOBS = "include_entity_globs"
CONF_EXCLUDE_ENTITY_GLOBS = "exclude_entity_globs"

# Config-flow provisioning step keys
CONF_PROJECT_MODE = "project_mode"  # "existing" | "create"
CONF_PROJECT_SELECT = "project_select"  # UUID of selected project
CONF_PROJECT_NEW_NAME = "project_new_name"
CONF_TABLE_MODE = "table_mode"  # "existing" | "create"
CONF_TABLE_SELECT = "table_select"  # UUID of selected table
CONF_TABLE_NEW_NAME = "table_new_name"

# Defaults
DEFAULT_DATABASE = "homeassistant"
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

# Provisioning modes
MODE_EXISTING = "existing"
MODE_CREATE = "create"
