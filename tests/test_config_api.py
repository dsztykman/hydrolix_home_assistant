"""Tests for the Hydrolix Config API module."""

import sys
import os

import pytest

# Allow importing without homeassistant dependency
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "custom_components",
        "hydrolix_history",
    ),
)
from config_api import (
    HA_TRANSFORM_BODY,
    HA_TRANSFORM_NAME,
    HA_TRANSFORM_SCHEMA,
    HydrolixConfigAPI,
)


class TestUnwrapHelpers:
    """Test that paginated / bare / single API responses are handled."""

    def test_unwrap_list_paginated(self):
        """Paginated response with 'results' key."""
        body = {
            "count": 2,
            "next": 0,
            "previous": 0,
            "results": [
                {"uuid": "aaa", "name": "org1"},
                {"uuid": "bbb", "name": "org2"},
            ],
        }
        result = HydrolixConfigAPI._unwrap_list(body)
        assert len(result) == 2
        assert result[0]["uuid"] == "aaa"

    def test_unwrap_list_bare_list(self):
        """Bare list response (older API versions)."""
        body = [{"uuid": "aaa", "name": "org1"}]
        result = HydrolixConfigAPI._unwrap_list(body)
        assert len(result) == 1
        assert result[0]["uuid"] == "aaa"

    def test_unwrap_list_single_object(self):
        """Single object response gets wrapped in a list."""
        body = {"uuid": "aaa", "name": "org1"}
        result = HydrolixConfigAPI._unwrap_list(body)
        assert len(result) == 1
        assert result[0]["uuid"] == "aaa"

    def test_unwrap_list_empty_paginated(self):
        """Paginated response with empty results."""
        body = {"count": 0, "results": []}
        result = HydrolixConfigAPI._unwrap_list(body)
        assert result == []

    def test_unwrap_list_empty_list(self):
        """Empty list."""
        assert HydrolixConfigAPI._unwrap_list([]) == []

    def test_unwrap_list_none(self):
        """None / unexpected type."""
        assert HydrolixConfigAPI._unwrap_list(None) == []

    def test_unwrap_single_bare_dict(self):
        """POST response as a bare dict."""
        body = {"uuid": "ccc", "name": "new_project"}
        result = HydrolixConfigAPI._unwrap_single(body)
        assert result["uuid"] == "ccc"

    def test_unwrap_single_list_of_one(self):
        """POST response as a list with one element."""
        body = [{"uuid": "ccc", "name": "new_project"}]
        result = HydrolixConfigAPI._unwrap_single(body)
        assert result["uuid"] == "ccc"

    def test_unwrap_single_paginated(self):
        """POST response wrapped in paginated format."""
        body = {"count": 1, "results": [{"uuid": "ccc", "name": "new_project"}]}
        result = HydrolixConfigAPI._unwrap_single(body)
        assert result["uuid"] == "ccc"


class TestTransformSchema:
    """Validate the built-in HA transform definition."""

    def test_schema_has_primary_timestamp(self):
        """The first column must be a primary datetime with Go format."""
        ts_col = HA_TRANSFORM_SCHEMA[0]
        assert ts_col["name"] == "timestamp"
        assert ts_col["datatype"]["type"] == "datetime"
        assert ts_col["datatype"]["primary"] is True
        assert "2006-01-02" in ts_col["datatype"]["format"]  # Go reference time

    def test_schema_column_count(self):
        """We expect 13 columns in the default schema."""
        assert len(HA_TRANSFORM_SCHEMA) == 13

    def test_schema_indexed_columns(self):
        """Key lookup columns should be indexed."""
        indexed = {
            col["name"]
            for col in HA_TRANSFORM_SCHEMA
            if col["datatype"].get("index") is True
        }
        assert "entity_id" in indexed
        assert "domain" in indexed
        assert "state" in indexed
        assert "friendly_name" in indexed
        assert "device_class" in indexed
        assert "unit_of_measurement" in indexed

    def test_schema_all_columns_have_names(self):
        """Every column must have a non-empty name."""
        for col in HA_TRANSFORM_SCHEMA:
            assert col.get("name"), f"Column missing name: {col}"

    def test_schema_all_columns_have_datatype(self):
        """Every column must have a datatype dict with a type key."""
        for col in HA_TRANSFORM_SCHEMA:
            dt = col.get("datatype")
            assert dt, f"Column '{col['name']}' missing datatype"
            assert "type" in dt, f"Column '{col['name']}' missing datatype.type"

    def test_transform_body_is_default(self):
        """The transform should be marked as the default."""
        assert HA_TRANSFORM_BODY["settings"]["is_default"] is True

    def test_transform_body_name(self):
        """The transform name matches the constant."""
        assert HA_TRANSFORM_BODY["name"] == HA_TRANSFORM_NAME
        assert HA_TRANSFORM_NAME == "ha_state_history"

    def test_transform_body_type_is_json(self):
        """Transform type should be json for NDJSON ingest."""
        assert HA_TRANSFORM_BODY["type"] == "json"

    def test_transform_body_no_compression_field(self):
        """Transform should not set compression — Content-Encoding handles it."""
        assert "compression" not in HA_TRANSFORM_BODY["settings"]

    def test_output_columns_are_full_schema(self):
        """output_columns should contain the full column definitions, not just names."""
        output_cols = HA_TRANSFORM_BODY["settings"]["output_columns"]
        assert output_cols is HA_TRANSFORM_SCHEMA
        # Every entry should be a dict with name + datatype
        for col in output_cols:
            assert "name" in col
            assert "datatype" in col

    def test_no_top_level_schema_key(self):
        """Transform body must NOT have a top-level 'schema' key."""
        assert "schema" not in HA_TRANSFORM_BODY

    def test_state_float_column_type(self):
        """state_float must be a double for numeric values."""
        col = next(c for c in HA_TRANSFORM_SCHEMA if c["name"] == "state_float")
        assert col["datatype"]["type"] == "double"

    def test_attributes_column_json_type(self):
        """attributes must use the native json datatype (no index)."""
        col = next(c for c in HA_TRANSFORM_SCHEMA if c["name"] == "attributes")
        assert col["datatype"]["type"] == "json"
        # json datatype does not support indexing
        assert "index" not in col["datatype"] or col["datatype"].get("index") is False

    def test_last_changed_is_datetime(self):
        """last_changed should be a datetime with Go format."""
        col = next(c for c in HA_TRANSFORM_SCHEMA if c["name"] == "last_changed")
        assert col["datatype"]["type"] == "datetime"
        assert "2006-01-02" in col["datatype"]["format"]

    def test_last_updated_is_datetime(self):
        """last_updated should be a datetime with Go format."""
        col = next(c for c in HA_TRANSFORM_SCHEMA if c["name"] == "last_updated")
        assert col["datatype"]["type"] == "datetime"
        assert "2006-01-02" in col["datatype"]["format"]
