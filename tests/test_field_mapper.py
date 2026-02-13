"""
Tests for field_mapper.py — DeviceClassifier and FieldMapper.
"""

import unittest
from src.field_mapper import DeviceClassifier, FieldMapper


class TestDeviceClassifier(unittest.TestCase):
    """Test device classification logic."""

    # ── Laptop Detection ─────────────────────────────────────────────────

    def test_thinkpad_classified_as_laptop(self):
        device = {"endpointType": "Desktop", "system": {"model": "ThinkPad X1 Carbon"}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    def test_probook_classified_as_laptop(self):
        device = {"endpointType": "Desktop", "system": {"model": "HP ProBook 450 G8"}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    def test_latitude_classified_as_laptop(self):
        device = {"endpointType": "Desktop", "system": {"model": "Latitude 5520"}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    def test_lenovo_part_number_classified_as_laptop(self):
        """Lenovo internal part numbers like 21BT000BUK should be classified as Laptop."""
        device = {"endpointType": "Desktop", "system": {"model": "21BT000BUK"}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    def test_macbook_classified_as_laptop(self):
        device = {"endpointType": "Desktop", "system": {"model": "MacBook Pro 16"}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    # ── Desktop Detection ────────────────────────────────────────────────

    def test_optiplex_classified_as_desktop(self):
        device = {"endpointType": "Desktop", "system": {"model": "OptiPlex 7090"}}
        self.assertEqual(DeviceClassifier.classify(device), "Desktop")

    def test_thinkcentre_classified_as_desktop(self):
        device = {"endpointType": "Desktop", "system": {"model": "ThinkCentre M920"}}
        self.assertEqual(DeviceClassifier.classify(device), "Desktop")

    def test_prodesk_classified_as_desktop(self):
        device = {"endpointType": "Desktop", "system": {"model": "HP ProDesk 600 G6"}}
        self.assertEqual(DeviceClassifier.classify(device), "Desktop")

    # ── Default for Unknown Desktops ─────────────────────────────────────

    def test_unknown_desktop_model_defaults_to_laptop(self):
        """Unknown model with 'Desktop' endpointType defaults to Laptop."""
        device = {"endpointType": "Desktop", "system": {"model": "SomeUnknownModel123"}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    def test_missing_model_defaults_to_laptop(self):
        """No model info with 'Desktop' endpointType defaults to Laptop."""
        device = {"endpointType": "Desktop", "system": {}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    def test_none_model_defaults_to_laptop(self):
        """None model value should default to Laptop, not crash."""
        device = {"endpointType": "Desktop", "system": {"model": None}}
        self.assertEqual(DeviceClassifier.classify(device), "Laptop")

    # ── Server Detection ─────────────────────────────────────────────────

    def test_vmware_serial_classified_as_virtual_server(self):
        device = {
            "endpointType": "Server",
            "system": {"serialNumber": "VMware-42 1a 2b 3c", "model": "VMware Virtual Platform"},
            "bios": {"manufacturer": "VMware, Inc."},
        }
        self.assertEqual(DeviceClassifier.classify(device), "Virtual Server")

    def test_hyperv_classified_as_virtual_server(self):
        device = {
            "endpointType": "Server",
            "system": {"serialNumber": "1234-5678", "model": "Virtual Machine"},
            "bios": {"manufacturer": "Microsoft Corporation"},
        }
        self.assertEqual(DeviceClassifier.classify(device), "Virtual Server")

    def test_physical_server_classified_correctly(self):
        device = {
            "endpointType": "Server",
            "system": {"serialNumber": "MXL1234ABC", "model": "ProLiant DL380 Gen10"},
            "bios": {"manufacturer": "HPE"},
        }
        self.assertEqual(DeviceClassifier.classify(device), "Physical Server")

    # ── Network Device ───────────────────────────────────────────────────

    def test_network_device_classified_correctly(self):
        device = {"endpointType": "NetworkDevice"}
        self.assertEqual(DeviceClassifier.classify(device), "Network Device")

    # ── Unknown ──────────────────────────────────────────────────────────

    def test_unknown_endpoint_type(self):
        device = {"endpointType": "SomethingNew"}
        self.assertEqual(DeviceClassifier.classify(device), "Unknown")

    def test_empty_device(self):
        device = {}
        self.assertEqual(DeviceClassifier.classify(device), "Unknown")


class TestFieldMapper(unittest.TestCase):
    """Test field mapping and transformation logic."""

    def _make_device(self, **overrides):
        """Create a sample CW device dict with sensible defaults."""
        device = {
            "endpointType": "Desktop",
            "friendlyName": "LAPTOP-001",
            "system": {"serialNumber": "ABC123", "model": "ThinkPad X1 Carbon"},
            "bios": {"manufacturer": "LENOVO"},
            "os": {"product": "Windows 11 Pro"},
            "processor": {"product": "Intel Core i7-1165G7"},
            "networks": [
                {"ipv4": "192.168.1.10", "macAddress": "AA:BB:CC:DD:EE:FF"},
                {"ipv4": "10.0.0.5", "macAddress": "11:22:33:44:55:66"},
            ],
        }
        device.update(overrides)
        return device

    # ── Core Mapping ─────────────────────────────────────────────────────

    def test_get_sdp_data_returns_all_mapped_fields(self):
        mapper = FieldMapper(self._make_device())
        data = mapper.get_sdp_data()

        self.assertEqual(data["_category"], "Laptop")
        self.assertEqual(data["name"], "LAPTOP-001")
        self.assertEqual(data["serial_number"], "ABC123")
        self.assertEqual(data["operating_system"], {"os": "Windows 11 Pro"})
        # computer_system now includes model and service_tag from system.*
        self.assertEqual(data["computer_system"], {
            "system_manufacturer": "Lenovo",  # Normalized from LENOVO
            "model": "ThinkPad X1 Carbon",
            "service_tag": "ABC123",
        })
        self.assertEqual(data["ip_address"], "192.168.1.10")
        self.assertIn("AA:BB:CC:DD:EE:FF", data["mac_address"])
        # Sub-resource: network_adapters built from CW networks
        self.assertIn("network_adapters", data)
        self.assertEqual(len(data["network_adapters"]), 2)
        self.assertEqual(data["network_adapters"][0]["ip_address"], "192.168.1.10")

    def test_category_included_in_result(self):
        mapper = FieldMapper(self._make_device())
        data = mapper.get_sdp_data()
        self.assertIn("_category", data)
        self.assertIsInstance(data["_category"], str)

    # ── Serial Number Cleaning ───────────────────────────────────────────

    def test_clean_serial_passes_real_serial(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._clean_serial("MXL1234ABC"), "MXL1234ABC")

    def test_clean_serial_strips_whitespace(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._clean_serial("  ABC123  "), "ABC123")

    def test_clean_serial_rejects_vmware_uuid(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._clean_serial("VMware-42 1a 2b 3c"))

    def test_clean_serial_rejects_virtual(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._clean_serial("Virtual-UUID-12345"))

    def test_clean_serial_handles_none(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._clean_serial(None))

    def test_clean_serial_handles_empty(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._clean_serial(""))

    # ── Manufacturer Cleaning ────────────────────────────────────────────

    def test_clean_manufacturer_normalizes_lenovo(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._clean_manufacturer("LENOVO"), "Lenovo")

    def test_clean_manufacturer_normalizes_hp(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._clean_manufacturer("Hewlett-Packard"), "HP")

    def test_clean_manufacturer_normalizes_dell(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._clean_manufacturer("Dell Inc."), "Dell")

    def test_clean_manufacturer_passes_unknown_through(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._clean_manufacturer("CustomOEM"), "CustomOEM")

    def test_clean_manufacturer_rejects_vmware(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._clean_manufacturer("VMware, Inc."))

    def test_clean_manufacturer_handles_none(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._clean_manufacturer(None))

    # ── IP Address Extraction ────────────────────────────────────────────

    def test_extract_ip_returns_first_valid(self):
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "192.168.1.10"},
            {"ipv4": "10.0.0.5"},
        ]
        self.assertEqual(mapper._extract_ip(networks), "192.168.1.10")

    def test_extract_ip_skips_loopback(self):
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "127.0.0.1"},
            {"ipv4": "192.168.1.10"},
        ]
        self.assertEqual(mapper._extract_ip(networks), "192.168.1.10")

    def test_extract_ip_skips_zero(self):
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "0.0.0.0"},
            {"ipv4": "10.0.0.5"},
        ]
        self.assertEqual(mapper._extract_ip(networks), "10.0.0.5")

    def test_extract_ip_returns_none_for_empty(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._extract_ip([]))

    def test_extract_ip_returns_none_for_none(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._extract_ip(None))

    def test_extract_ip_returns_none_when_all_invalid(self):
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "0.0.0.0"},
            {"ipv4": "127.0.0.1"},
        ]
        self.assertIsNone(mapper._extract_ip(networks))

    def test_extract_ip_skips_apipa(self):
        """APIPA (169.254.x.x) addresses should be filtered out."""
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "169.254.1.100"},
            {"ipv4": "192.168.1.10"},
        ]
        self.assertEqual(mapper._extract_ip(networks), "192.168.1.10")

    def test_extract_ip_returns_none_when_only_apipa(self):
        """If only APIPA IPs are available, should return None."""
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "169.254.0.1"},
        ]
        self.assertIsNone(mapper._extract_ip(networks))

    # ── MAC Address Extraction ───────────────────────────────────────────

    def test_extract_mac_returns_first_only(self):
        mapper = FieldMapper(self._make_device())
        networks = [
            {"macAddress": "AA:BB:CC:DD:EE:FF"},
            {"macAddress": "11:22:33:44:55:66"},
        ]
        result = mapper._extract_mac(networks)
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_extract_mac_skips_missing(self):
        mapper = FieldMapper(self._make_device())
        networks = [
            {"ipv4": "192.168.1.10"},  # No macAddress
            {"macAddress": "AA:BB:CC:DD:EE:FF"},
        ]
        self.assertEqual(mapper._extract_mac(networks), "AA:BB:CC:DD:EE:FF")

    def test_extract_mac_returns_none_for_empty(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._extract_mac([]))

    def test_extract_mac_returns_none_for_none(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._extract_mac(None))

    # ── Nested Value Access ──────────────────────────────────────────────

    def test_get_nested_simple_key(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._get_nested("friendlyName"), "LAPTOP-001")

    def test_get_nested_deep_key(self):
        mapper = FieldMapper(self._make_device())
        self.assertEqual(mapper._get_nested("system.serialNumber"), "ABC123")

    def test_get_nested_missing_key_returns_none(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._get_nested("nonexistent.path"))

    def test_get_nested_partial_path_returns_none(self):
        mapper = FieldMapper(self._make_device())
        self.assertIsNone(mapper._get_nested("system.nonexistent"))

    # ── Edge Cases ───────────────────────────────────────────────────────

    def test_empty_device_produces_minimal_output(self):
        """An empty device should still produce _category without crashing."""
        mapper = FieldMapper({})
        data = mapper.get_sdp_data()
        self.assertIn("_category", data)

    def test_device_with_no_networks(self):
        """Device without networks should produce output without IP/MAC."""
        device = self._make_device(networks=None)
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        self.assertNotIn("ip_address", data)
        self.assertNotIn("mac_address", data)

    # ── New Sub-Resource Extractors ──────────────────────────────────────

    def test_extract_total_ram(self):
        """Should sum physicalMemory sizeBytes into a string."""
        device = self._make_device(physicalMemory=[
            {"sizeBytes": 8589934592},
            {"sizeBytes": 8589934592},
        ])
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        self.assertEqual(data["memory"], {"physical_memory": "17179869184"})

    def test_extract_total_ram_empty(self):
        """No physicalMemory should not produce a memory key."""
        device = self._make_device(physicalMemory=[])
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        self.assertNotIn("memory", data)

    def test_extract_network_adapters(self):
        """Should build adapters with real names from CW data."""
        device = self._make_device(networks=[
            {"ipv4": "10.0.0.5", "macAddress": "AA:BB:CC:DD:EE:FF",
             "product": "Realtek PCIe GbE"},
        ])
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        adapters = data["network_adapters"]
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0]["name"], "Realtek PCIe GbE")
        self.assertEqual(adapters[0]["ip_address"], "10.0.0.5")
        self.assertEqual(adapters[0]["mac_address"], "AA:BB:CC:DD:EE:FF")

    def test_extract_network_adapters_skips_unusable(self):
        """Adapters without IP or MAC are skipped."""
        device = self._make_device(networks=[
            {"ipv4": "0.0.0.0", "macAddress": ""},
            {"ipv4": "10.1.1.1", "macAddress": "11:22:33:44:55:66"},
        ])
        mapper = FieldMapper(device)
        adapters = mapper._extract_network_adapters()
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0]["ip_address"], "10.1.1.1")

    def test_extract_processors(self):
        """Should extract processor info from CW data."""
        device = self._make_device(processors=[
            {"product": "Intel Core i7-1165G7", "numberOfCores": 4,
             "clockSpeedMhz": 2800, "manufacturer": "GenuineIntel"},
        ])
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        self.assertIn("processors", data)
        self.assertEqual(len(data["processors"]), 1)
        self.assertEqual(data["processors"][0]["name"], "Intel Core i7-1165G7")
        self.assertEqual(data["processors"][0]["number_of_cores"], "4")
        self.assertEqual(data["processors"][0]["speed"], "2800")

    def test_extract_processors_empty(self):
        """No processors should not produce a processors key."""
        device = self._make_device(processors=[])
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        self.assertNotIn("processors", data)

    def test_os_version_fields(self):
        """Should map OS version, service_pack, and build_number."""
        device = self._make_device(os={
            "product": "Windows 11 Pro",
            "version": "10.0.26100",
            "displayVersion": "24H2",
            "buildNumber": "26100",
        })
        mapper = FieldMapper(device)
        data = mapper.get_sdp_data()
        self.assertEqual(data["operating_system"]["os"], "Windows 11 Pro")
        self.assertEqual(data["operating_system"]["version"], "10.0.26100")
        self.assertEqual(data["operating_system"]["service_pack"], "24H2")
        self.assertEqual(data["operating_system"]["build_number"], "26100")


if __name__ == "__main__":
    unittest.main()
