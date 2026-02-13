"""
Tests for sdp_client.py — _parse_extra_key_fields, create_asset, update_asset retry logic.

Uses unittest.mock to avoid real API calls.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from src.sdp_client import ServiceDeskPlusClient, ServiceDeskPlusClientError


class TestParseExtraKeyFields(unittest.TestCase):
    """Test _parse_extra_key_fields static method."""

    def test_parses_single_extra_key(self):
        """Should extract the field name from an EXTRA_KEY error."""
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {
                "status_code": 4000,
                "messages": [{
                    "status_code": 4001,
                    "field": "os",
                    "type": "failed",
                    "message": "EXTRA_KEY_FOUND_IN_JSON"
                }],
                "status": "failed"
            }
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, ["os"])

    def test_parses_multiple_extra_keys(self):
        """Should extract multiple rejected fields."""
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {
                "status_code": 4000,
                "messages": [
                    {"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"},
                    {"field": "mac_address", "message": "EXTRA_KEY_FOUND_IN_JSON"},
                ],
                "status": "failed"
            }
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, ["os", "mac_address"])

    def test_ignores_non_extra_key_errors(self):
        """Should return empty list for other error types."""
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {
                "status_code": 4000,
                "messages": [{"field": "name", "message": "REQUIRED_FIELD_MISSING"}],
                "status": "failed"
            }
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, [])

    def test_returns_empty_for_non_json_error(self):
        """Should return empty list for non-JSON error strings."""
        fields = ServiceDeskPlusClient._parse_extra_key_fields("Some generic error message")
        self.assertEqual(fields, [])

    def test_returns_empty_for_empty_string(self):
        fields = ServiceDeskPlusClient._parse_extra_key_fields("")
        self.assertEqual(fields, [])

    def test_returns_empty_for_malformed_json(self):
        fields = ServiceDeskPlusClient._parse_extra_key_fields("Request failed: 400 - {not valid json}")
        self.assertEqual(fields, [])

    def test_returns_empty_when_no_messages(self):
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {"status_code": 4000, "status": "failed"}
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, [])

    def test_mixed_errors_only_returns_extra_keys(self):
        """When mix of EXTRA_KEY and other errors, should only return EXTRA_KEY fields."""
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {
                "messages": [
                    {"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"},
                    {"field": "name", "message": "REQUIRED_FIELD_MISSING"},
                    {"field": "mac_address", "message": "EXTRA_KEY_FOUND_IN_JSON"},
                ]
            }
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, ["os", "mac_address"])

    def test_parses_validation_failure_fields(self):
        """Should return fields that fail validation (status 4014)."""
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {
                "status_code": 4000,
                "messages": [
                    {"status_code": 4014, "field": "ip_address", "type": "failed"}
                ],
                "status": "failed"
            }
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, ["ip_address"])

    def test_mixed_extra_key_and_validation_failures(self):
        """Should return both EXTRA_KEY and validation failure fields."""
        error = 'Request failed: 400 - ' + json.dumps({
            "response_status": {
                "messages": [
                    {"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"},
                    {"status_code": 4014, "field": "ip_address", "type": "failed"},
                    {"field": "name", "message": "REQUIRED_FIELD_MISSING"},
                ]
            }
        })
        fields = ServiceDeskPlusClient._parse_extra_key_fields(error)
        self.assertEqual(fields, ["os", "ip_address"])


class TestCreateAssetRetry(unittest.TestCase):
    """Test create_asset auto-retry on EXTRA_KEY errors."""

    def _make_client(self):
        """Create a ServiceDeskPlusClient with mocked internals (no real API calls)."""
        with patch.object(ServiceDeskPlusClient, '__init__', lambda self: None):
            client = ServiceDeskPlusClient.__new__(ServiceDeskPlusClient)
            client.dry_run = False
            client._access_token = "test-token"
            client._cancelled = False
            client.rate_limiter = MagicMock()
            client.max_retries = 3
            client.retry_delay = 0.1
            client._lock = MagicMock()
            return client

    def test_create_asset_success_first_try(self):
        """Should succeed on first try when no extra keys."""
        client = self._make_client()
        expected = {"id": "12345", "name": "LAPTOP-001"}
        client._make_request = MagicMock(return_value=expected)

        result = client.create_asset("asset_workstations", {
            "name": "LAPTOP-001",
            "serial_number": "ABC123",
        })

        self.assertEqual(result, expected)
        self.assertEqual(client._make_request.call_count, 1)

    def test_create_asset_retries_on_extra_key(self):
        """Should strip rejected field and retry on EXTRA_KEY error."""
        client = self._make_client()

        extra_key_error = ServiceDeskPlusClientError(
            'Request failed: 400 - ' + json.dumps({
                "response_status": {
                    "messages": [{"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"}],
                }
            })
        )
        expected = {"id": "12345", "name": "VM-001"}

        # First call fails with EXTRA_KEY, second succeeds
        client._make_request = MagicMock(side_effect=[extra_key_error, expected])

        result = client.create_asset("asset_virtual_machines", {
            "name": "VM-001",
            "os": "Windows Server 2019",
            "serial_number": "XYZ789",
        })

        self.assertEqual(result, expected)
        self.assertEqual(client._make_request.call_count, 2)

    def test_create_asset_retries_multiple_extra_keys(self):
        """Should handle multiple extra keys being rejected one at a time."""
        client = self._make_client()

        error_1 = ServiceDeskPlusClientError(
            'Request failed: 400 - ' + json.dumps({
                "response_status": {
                    "messages": [{"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"}],
                }
            })
        )
        error_2 = ServiceDeskPlusClientError(
            'Request failed: 400 - ' + json.dumps({
                "response_status": {
                    "messages": [{"field": "mac_address", "message": "EXTRA_KEY_FOUND_IN_JSON"}],
                }
            })
        )
        expected = {"id": "12345", "name": "VM-001"}

        client._make_request = MagicMock(side_effect=[error_1, error_2, expected])

        result = client.create_asset("asset_virtual_machines", {
            "name": "VM-001",
            "os": "Windows Server 2019",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "serial_number": "XYZ789",
        })

        self.assertEqual(result, expected)
        self.assertEqual(client._make_request.call_count, 3)

    def test_create_asset_fails_on_non_extra_key_error(self):
        """Should NOT retry on non-EXTRA_KEY errors (e.g. REQUIRED_FIELD_MISSING)."""
        client = self._make_client()

        error = ServiceDeskPlusClientError(
            'Request failed: 400 - ' + json.dumps({
                "response_status": {
                    "messages": [{"field": "name", "message": "REQUIRED_FIELD_MISSING"}],
                }
            })
        )
        client._make_request = MagicMock(side_effect=error)

        result = client.create_asset("asset_workstations", {
            "name": "",  # Missing name
            "serial_number": "ABC123",
        })

        self.assertIsNone(result)
        self.assertEqual(client._make_request.call_count, 1)

    def test_create_asset_dry_run_skips_api(self):
        """Dry run should return simulated result without making API calls."""
        client = self._make_client()
        client.dry_run = True
        client._make_request = MagicMock()

        result = client.create_asset("asset_workstations", {"name": "LAPTOP-001"})

        self.assertIsNotNone(result)
        self.assertTrue(result.get("dry_run"))
        client._make_request.assert_not_called()


class TestUpdateAssetRetry(unittest.TestCase):
    """Test update_asset auto-retry on EXTRA_KEY errors."""

    def _make_client(self):
        with patch.object(ServiceDeskPlusClient, '__init__', lambda self: None):
            client = ServiceDeskPlusClient.__new__(ServiceDeskPlusClient)
            client.dry_run = False
            client._access_token = "test-token"
            client._cancelled = False
            client.rate_limiter = MagicMock()
            client.max_retries = 3
            client.retry_delay = 0.1
            client._lock = MagicMock()
            return client

    def test_update_asset_success_first_try(self):
        client = self._make_client()
        expected = {"id": "12345", "name": "LAPTOP-001"}
        client._make_request = MagicMock(return_value=expected)

        result = client.update_asset("12345", {
            "name": "LAPTOP-001",
            "ip_address": "192.168.1.10",
        })

        self.assertEqual(result, expected)
        self.assertEqual(client._make_request.call_count, 1)

    def test_update_asset_retries_on_extra_key(self):
        client = self._make_client()

        extra_key_error = ServiceDeskPlusClientError(
            'Request failed: 400 - ' + json.dumps({
                "response_status": {
                    "messages": [{"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"}],
                }
            })
        )
        expected = {"id": "12345", "name": "VM-001"}
        client._make_request = MagicMock(side_effect=[extra_key_error, expected])

        result = client.update_asset("12345", {
            "name": "VM-001",
            "os": "Windows Server 2019",
            "ip_address": "10.0.0.5",
        })

        self.assertEqual(result, expected)
        self.assertEqual(client._make_request.call_count, 2)

    def test_update_asset_stops_on_404_invalid_url(self):
        """Should stop retrying immediately on 404 Invalid URL."""
        client = self._make_client()

        extra_key_error = ServiceDeskPlusClientError(
            'Request failed: 400 - ' + json.dumps({
                "response_status": {
                    "messages": [{"field": "os", "message": "EXTRA_KEY_FOUND_IN_JSON"}],
                }
            })
        )
        invalid_url_error = ServiceDeskPlusClientError(
            'Request failed: 404 - ' + json.dumps({
                "response_status": {
                    "messages": [{"message": "Invalid URL accessed"}],
                }
            })
        )
        client._make_request = MagicMock(side_effect=[extra_key_error, invalid_url_error])

        result = client.update_asset("12345", {
            "name": "VM-001",
            "os": "Windows Server 2019",
            "serial_number": "XYZ789",
        })

        self.assertIsNone(result)  # Should fail gracefully
        self.assertEqual(client._make_request.call_count, 2)  # Should NOT retry after 404

    def test_update_asset_dry_run_skips_api(self):
        client = self._make_client()
        client.dry_run = True
        client._make_request = MagicMock()

        result = client.update_asset("12345", {"name": "VM-001"})

        self.assertIsNotNone(result)
        self.assertTrue(result.get("dry_run"))
        client._make_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
