"""
================================================================================
Field Mapper: ConnectWise → ServiceDesk Plus Field Mapping
================================================================================

This module handles the transformation of device data from ConnectWise RMM
format to ServiceDesk Plus Assets API format. It includes:

1. Device Classification - Categorizing devices into SDP asset types
2. Field Mapping - Translating CW field names to SDP field names
3. Data Transformation - Cleaning and formatting values

Device Classification Logic:
----------------------------
ConnectWise uses "endpointType" to categorize devices:
- "Desktop" → Could be Laptop or Desktop (we check model name)
- "Server" → Could be Virtual or Physical (we check for VM indicators)
- "NetworkDevice" → Network Device

SDP CI Types:
- asset_workstations → Laptops and Desktops
- asset_virtual_machines → Virtual Servers
- asset_servers → Physical Servers
- asset_switches → Network Devices

Field Mapping:
--------------
CW stores data in nested JSON structures. For example:
- device.system.serialNumber → serial_number
- device.os.product → operating_system.os
- device.networks[0].ipv4 → ip_address

Usage Example:
--------------
    from src.field_mapper import FieldMapper, DeviceClassifier

    # Classify a device
    category = DeviceClassifier.classify(cw_device)
    print(f"Category: {category}")  # e.g., "Laptop"

    # Map all fields
    mapper = FieldMapper(cw_device)
    sdp_data = mapper.get_sdp_data()
    print(sdp_data)  # {"name": "LAPTOP-001", "serial_number": "ABC123", ...}
"""

import json
import re
from typing import Dict, Any, Optional, Tuple


# =============================================================================
# DEVICE CLASSIFIER
# =============================================================================

class DeviceClassifier:
    """
    Classify ConnectWise devices into ServiceDesk Plus asset categories.

    This class analyzes device properties to determine the appropriate
    SDP Asset product type. The classification is based on:

    1. endpointType from ConnectWise (Desktop, Server, NetworkDevice)
    2. Model name patterns (to distinguish laptops from desktops)
    3. VM indicators (to distinguish virtual from physical servers)

    Classification Results:
    - "Laptop" → asset_workstations (portable devices)
    - "Desktop" → asset_workstations (fixed workstations)
    - "Virtual Server" → asset_virtual_machines (VMs)
    - "Physical Server" → asset_servers (bare metal)
    - "Network Device" → asset_switches (routers, switches, etc.)
    """

    # =========================================================================
    # MODEL NAME PATTERNS
    # =========================================================================

    # Regex patterns that indicate a laptop model
    # These are checked against the device.system.model field
    LAPTOP_PATTERNS = [
        r'^\d{2}[A-Z0-9]{2}\d{3,4}[A-Z]{2}$',  # Lenovo part numbers: 21BT000BUK, 21C1002VUK
        r'ProBook',      # HP ProBook series
        r'EliteBook',    # HP EliteBook series
        r'Latitude',     # Dell Latitude series
        r'ThinkPad',     # Lenovo ThinkPad series
        r'Pavilion',     # HP Pavilion (consumer laptops)
        r'MacBook',      # Apple MacBook
        r'XPS',          # Dell XPS series
        r'Inspiron',     # Dell Inspiron series
        r'ZBook',        # HP ZBook workstation laptops
    ]

    # Regex patterns that indicate a desktop workstation model
    DESKTOP_PATTERNS = [
        r'OptiPlex',         # Dell OptiPlex desktops
        r'ThinkCentre',      # Lenovo ThinkCentre desktops
        r'ProDesk',          # HP ProDesk desktops
        r'EliteDesk',        # HP EliteDesk desktops
        r'Precision Tower',  # Dell Precision Tower workstations
    ]

    # =========================================================================
    # MAIN CLASSIFICATION METHOD
    # =========================================================================

    @classmethod
    def classify(cls, device: Dict[str, Any]) -> str:
        """
        Classify a ConnectWise device into an SDP category.

        Args:
            device: ConnectWise device dictionary with fields like:
                   - endpointType: "Desktop", "Server", or "NetworkDevice"
                   - system: {"model": "...", "serialNumber": "..."}
                   - bios: {"manufacturer": "..."}

        Returns:
            One of: "Laptop", "Desktop", "Virtual Server", "Physical Server",
                   "Network Device", or "Unknown"

        Example:
            >>> device = {"endpointType": "Desktop", "system": {"model": "ThinkPad X1"}}
            >>> DeviceClassifier.classify(device)
            'Laptop'
        """
        # Get the CW endpoint type
        endpoint_type = device.get('endpointType', '')
        resource_type = device.get('resourceType', '')

        # Network devices are straightforward
        if endpoint_type == 'NetworkDevice':
            return 'Network Device'

        # "Desktop" in CW means "endpoint with agent" - could be laptop or desktop
        if endpoint_type == 'Desktop':
            # Check model name to distinguish laptop from desktop
            model = device.get('system', {}).get('model', '') or ''

            if cls._is_desktop(model):
                return 'Desktop'

            # Default to Laptop for portable devices
            # Most CW "Desktop" endpoints are actually laptops (ThinkPads, ProBooks, etc.)
            return 'Laptop'

        # Servers need to be classified as virtual or physical
        if endpoint_type == 'Server':
            if cls._is_virtual(device):
                return 'Virtual Server'
            return 'Physical Server'

        # Unknown endpoint type
        return 'Unknown'

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @classmethod
    def _is_laptop(cls, model: str) -> bool:
        """
        Check if model name indicates a laptop.

        Args:
            model: The device model name (e.g., "ThinkPad X1 Carbon")

        Returns:
            True if model matches any laptop pattern
        """
        for pattern in cls.LAPTOP_PATTERNS:
            if re.search(pattern, model, re.IGNORECASE):
                return True
        return False

    @classmethod
    def _is_desktop(cls, model: str) -> bool:
        """
        Check if model name indicates a desktop workstation.

        Args:
            model: The device model name (e.g., "OptiPlex 7090")

        Returns:
            True if model matches any desktop pattern
        """
        for pattern in cls.DESKTOP_PATTERNS:
            if re.search(pattern, model, re.IGNORECASE):
                return True

        # Note: "Virtual Machine" in model is NOT treated as desktop.
        # VMs with endpointType "Desktop" should default to Laptop (the
        # classify() caller), and VMs with endpointType "Server" are
        # handled by _is_virtual(). Classifying VMs as Desktop would
        # prevent them from being correctly identified as virtual servers.

        return False

    @classmethod
    def _is_virtual(cls, device: Dict[str, Any]) -> bool:
        """
        Check if device is a virtual machine.

        Checks multiple fields for VM indicators:
        - Serial number (VMware VMs have UUIDs)
        - BIOS manufacturer (VMware, Microsoft, etc.)
        - Model name (Virtual Machine, etc.)

        Args:
            device: ConnectWise device dictionary

        Returns:
            True if any VM indicator is found
        """
        # Fields to check for VM indicators
        checks = [
            device.get('system', {}).get('serialNumber', ''),
            device.get('bios', {}).get('manufacturer', ''),
            device.get('system', {}).get('model', ''),
        ]

        # Known VM platform indicators
        vm_indicators = ['VMware', 'Virtual', 'Hyper-V', 'QEMU', 'VirtualBox', 'Xen']

        # Check each field for any VM indicator
        for value in checks:
            if value:
                for indicator in vm_indicators:
                    if indicator.lower() in str(value).lower():
                        return True

        return False


# =============================================================================
# FIELD MAPPER
# =============================================================================

class FieldMapper:
    """
    Map ConnectWise device fields to ServiceDesk Plus Asset fields.

    This class handles the translation of field names and values from
    ConnectWise format to ServiceDesk Plus Assets format.

    ConnectWise stores data in nested JSON structures:
    - device.system.serialNumber
    - device.os.product
    - device.networks[0].ipv4

    ServiceDesk Plus Assets use flat field names:
    - serial_number
    - os
    - ip_address

    The FIELD_MAP dictionary defines the mapping between these formats,
    along with optional transformation functions for data cleaning.

    Example:
        >>> mapper = FieldMapper(cw_device)
        >>> sdp_data = mapper.get_sdp_data()
        >>> print(sdp_data)
        {
            '_category': 'Laptop',
            'name': 'LAPTOP-001',
            'serial_number': 'ABC123',
            'os': 'Windows 11 Pro',
            ...
        }
    """

    # =========================================================================
    # FIELD MAPPING CONFIGURATION
    # =========================================================================

    # CW -> SDP Asset field mapping (flat fields)
    # Format: 'sdp_field': ('cw_path', 'transformation_method_name')
    #
    # cw_path uses dot notation for nested fields (e.g., 'system.serialNumber')
    # transformation_method_name is the name of a method on this class (or None)
    FIELD_MAP = {
        # Asset Name - uses the CW friendly name (computer name)
        'name': ('friendlyName', None),

        # Serial Number - from system.serialNumber, cleaned to remove VM UUIDs
        'serial_number': ('system.serialNumber', '_clean_serial'),

        # IP Address - extracted from networks array (first valid internal IP)
        'ip_address': ('networks', '_extract_ip'),

        # MAC Address - extracted from networks array (comma-separated if multiple)
        'mac_address': ('networks', '_extract_mac'),
    }

    # CW -> SDP nested field mapping
    # The SDP Assets API requires certain fields to be wrapped in nested objects.
    # Format: 'sdp_parent_key': {'sdp_child_key': ('cw_path', 'transform')}
    NESTED_FIELD_MAP = {
        # Operating System info — SDP expects:
        # {"operating_system": {"os": "...", "version": "...", ...}}
        'operating_system': {
            'os': ('os.product', None),
            'version': ('os.version', None),
            'service_pack': ('os.displayVersion', None),
            'build_number': ('os.buildNumber', None),
        },
        # Computer System info — SDP expects:
        # {"computer_system": {"system_manufacturer": "...", "model": "...", ...}}
        'computer_system': {
            'system_manufacturer': ('bios.manufacturer', '_clean_manufacturer'),
            'model': ('system.model', None),
            'service_tag': ('system.serialNumber', '_clean_serial'),
        },
        # Memory totals — SDP expects: {"memory": {"physical_memory": "..."}}
        'memory': {
            'physical_memory': ('physicalMemory', '_extract_total_ram'),
        },
    }

    # =========================================================================
    # SUB-RESOURCE ARRAY MAPPING
    # =========================================================================
    # These produce lists-of-dicts that must be sent on the type-specific
    # SDP endpoint (like network_adapters).  Each entry is:
    #   'sdp_array_key': 'extractor_method_name'
    SUB_RESOURCE_MAP = {
        'network_adapters': '_extract_network_adapters',
        'processors': '_extract_processors',
    }

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def __init__(self, cw_device: Dict[str, Any]):
        """
        Initialize the field mapper with a ConnectWise device.

        Args:
            cw_device: Raw ConnectWise device dictionary from API

        Note:
            Device classification happens during initialization.
        """
        self.device = cw_device
        # Classify the device type (Laptop, Server, etc.)
        self.category = DeviceClassifier.classify(cw_device)

    # =========================================================================
    # MAIN MAPPING METHOD
    # =========================================================================

    def get_sdp_data(self) -> Dict[str, Any]:
        """
        Map all CW device fields to SDP field values.

        Iterates through FIELD_MAP (flat fields) and NESTED_FIELD_MAP
        (fields requiring nested JSON objects), extracts values from the
        CW device, applies transformations, and returns a dictionary
        ready for SDP API calls.

        Returns:
            Dictionary with SDP field names as keys. Includes special
            '_category' key with the device classification.
            Nested fields are returned as sub-dictionaries, e.g.:
            {'operating_system': {'os': 'Windows 11 Pro'}}

        Example:
            >>> mapper = FieldMapper(cw_device)
            >>> data = mapper.get_sdp_data()
            >>> print(data['name'])  # "LAPTOP-001"
            >>> print(data['operating_system']['os'])  # "Windows 11 Pro"
            >>> print(data['_category'])  # "Laptop"
        """
        # Start with the category (used to determine CI type)
        result = {'_category': self.category}

        # Process flat field mappings
        for sdp_field, (cw_path, transform) in self.FIELD_MAP.items():
            # Extract value from nested CW structure
            value = self._get_nested(cw_path)

            # Apply transformation if specified
            if transform and hasattr(self, transform):
                value = getattr(self, transform)(value)

            # Only include non-empty values
            if value:
                result[sdp_field] = value

        # Process nested field mappings (e.g., operating_system, computer_system)
        for parent_key, children in self.NESTED_FIELD_MAP.items():
            nested = {}
            for child_key, (cw_path, transform) in children.items():
                value = self._get_nested(cw_path)
                if transform and hasattr(self, transform):
                    value = getattr(self, transform)(value)
                if value:
                    nested[child_key] = value
            # Only include the parent if at least one child has a value
            if nested:
                result[parent_key] = nested

        # Process sub-resource arrays (sent on type-specific endpoints)
        for sdp_key, extractor in self.SUB_RESOURCE_MAP.items():
            if hasattr(self, extractor):
                items = getattr(self, extractor)()
                if items:
                    result[sdp_key] = items

        return result

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _get_nested(self, path: str) -> Any:
        """
        Get a nested value from the device dict using dot notation.

        Args:
            path: Dot-separated path (e.g., "system.serialNumber")

        Returns:
            The value at the path, or None if not found

        Example:
            >>> self._get_nested("system.serialNumber")
            "ABC123"
            >>> self._get_nested("os.product")
            "Windows 11 Pro"
        """
        parts = path.split('.')
        value = self.device

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    # =========================================================================
    # TRANSFORMATION METHODS
    # =========================================================================

    def _clean_serial(self, value: str) -> Optional[str]:
        """
        Clean serial number, filtering out VM UUIDs.

        Virtual machines often have UUIDs or VMware-specific serial numbers
        that aren't useful for asset tracking. This method filters those out.

        Args:
            value: Raw serial number string

        Returns:
            Cleaned serial number, or None for VM serials
        """
        if not value:
            return None

        # Skip VMware/Virtual UUIDs - they're not real serial numbers
        if 'VMware' in value or 'Virtual' in value:
            return None

        return value.strip()

    def _clean_manufacturer(self, value: str) -> Optional[str]:
        """
        Clean and normalize manufacturer name.

        Standardizes manufacturer names for consistency in SDP:
        - "LENOVO" → "Lenovo"
        - "Hewlett-Packard" → "HP"
        - "Dell Inc." → "Dell"

        Args:
            value: Raw manufacturer string

        Returns:
            Normalized manufacturer name, or None for VMs
        """
        if not value or 'VMware' in value:
            return None

        # Normalize common manufacturer names
        mapping = {
            'LENOVO': 'Lenovo',
            'Hewlett-Packard': 'HP',
            'Dell Inc.': 'Dell',
        }

        return mapping.get(value, value)

    def _extract_ip(self, networks: list) -> Optional[str]:
        """
        Extract the first valid internal IP from networks array.

        ConnectWise returns an array of network adapters. This method
        finds the first adapter with a valid internal IP address.

        Filters out:
        - 0.0.0.0 (no IP assigned)
        - 127.x.x.x (loopback addresses)
        - 169.254.x.x (APIPA / link-local, no DHCP lease)

        Args:
            networks: List of network adapter dictionaries

        Returns:
            First valid internal IP address, or None
        """
        if not networks:
            return None

        for net in networks:
            ip = net.get('ipv4', '')
            # Skip invalid/loopback/link-local addresses
            if ip and ip != '0.0.0.0' and not ip.startswith('127.') and not ip.startswith('169.254.'):
                return ip

        return None

    def _extract_mac(self, networks: list) -> Optional[str]:
        """
        Extract the first valid MAC address from networks array.

        Returns only the first MAC address. SDP does not accept
        comma-separated multiple MACs — sending multiple causes
        validation failures.

        Args:
            networks: List of network adapter dictionaries

        Returns:
            First MAC address string, or None if none found
        """
        if not networks:
            return None

        for net in networks:
            mac = net.get('macAddress')
            if mac:
                return mac

        return None

    # =========================================================================
    # SUB-RESOURCE EXTRACTORS
    # =========================================================================

    def _is_valid_ip(self, ip: str) -> bool:
        """Return True if *ip* is a usable internal address."""
        return bool(
            ip
            and ip != '0.0.0.0'
            and not ip.startswith('127.')
            and not ip.startswith('169.254.')
        )

    def _extract_total_ram(self, memory_modules: list) -> Optional[str]:
        """
        Sum all physical memory module sizes and return as a string (bytes).

        SDP stores physical_memory as a string of the total byte count.

        Args:
            memory_modules: CW physicalMemory list, each with 'sizeBytes'

        Returns:
            Total bytes as string, or None if no modules
        """
        if not memory_modules:
            return None

        total = 0
        for mod in memory_modules:
            size = mod.get('sizeBytes', 0)
            if isinstance(size, (int, float)) and size > 0:
                total += int(size)

        return str(total) if total > 0 else None

    def _extract_network_adapters(self) -> list:
        """
        Build the SDP network_adapters array from CW networks data.

        Returns a list of adapter dicts with name, ip_address, mac_address,
        description, gateway, dhcp, and ipnet_mask.  Only adapters with a
        valid IP or MAC are included.

        Returns:
            List of adapter dicts ready for the SDP type-specific endpoint
        """
        networks = self.device.get('networks')
        if not networks:
            return []

        adapters = []
        for net in networks:
            ip = net.get('ipv4', '')
            mac = net.get('macAddress', '')

            # Skip adapters without a usable IP or MAC
            if not self._is_valid_ip(ip) and not mac:
                continue

            adapter: Dict[str, Any] = {
                'name': net.get('product') or net.get('logicalName') or 'NIC',
            }
            if self._is_valid_ip(ip):
                adapter['ip_address'] = ip
            if mac:
                adapter['mac_address'] = mac

            # Optional enrichment fields
            desc = net.get('product') or net.get('logicalName')
            if desc:
                adapter['description'] = desc
            gw = net.get('defaultIPGateway')
            if gw and gw != '0.0.0.0':
                adapter['gateway'] = gw
            mask = net.get('subnetMask')
            if mask and mask != '0.0.0.0':
                adapter['ipnet_mask'] = mask
            dhcp = net.get('dhcpEnabled')
            if dhcp is not None:
                adapter['dhcp'] = 'true' if dhcp else 'false'

            adapters.append(adapter)

        return adapters

    def _extract_processors(self) -> list:
        """
        Build the SDP processors array from CW processors data.

        Returns a list of processor dicts with name, number_of_cores,
        speed, and manufacturer.

        Returns:
            List of processor dicts ready for the SDP type-specific endpoint
        """
        processors = self.device.get('processors')
        if not processors:
            return []

        result = []
        for proc in processors:
            name = proc.get('product')
            if not name:
                continue

            entry: Dict[str, Any] = {'name': name}

            cores = proc.get('numberOfCores')
            if cores:
                entry['number_of_cores'] = str(cores)
            speed = proc.get('clockSpeedMhz')
            if speed:
                entry['speed'] = str(speed)
            mfr = proc.get('manufacturer')
            if mfr:
                entry['manufacturer'] = mfr

            result.append(entry)

        return result

