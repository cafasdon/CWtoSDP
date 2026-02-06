"""
================================================================================
Field Mapper: ConnectWise → ServiceDesk Plus Field Mapping
================================================================================

This module handles the transformation of device data from ConnectWise RMM
format to ServiceDesk Plus CMDB format. It includes:

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
- ci_windows_workstation → Laptops and Desktops
- ci_virtual_machine → Virtual Servers
- ci_windows_server → Physical Servers
- ci_switch → Network Devices

Field Mapping:
--------------
CW stores data in nested JSON structures. For example:
- device.system.serialNumber → ci_attributes_txt_serial_number
- device.os.product → ci_attributes_txt_os
- device.networks[0].ipv4 → ci_attributes_txt_ip_address

Usage Example:
--------------
    from src.field_mapper import FieldMapper, DeviceClassifier

    # Classify a device
    category = DeviceClassifier.classify(cw_device)
    print(f"Category: {category}")  # e.g., "Laptop"

    # Map all fields
    mapper = FieldMapper(cw_device)
    sdp_data = mapper.get_sdp_data()
    print(sdp_data)  # {"name": "LAPTOP-001", "ci_attributes_txt_serial_number": "ABC123", ...}
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
    SDP CI type. The classification is based on:

    1. endpointType from ConnectWise (Desktop, Server, NetworkDevice)
    2. Model name patterns (to distinguish laptops from desktops)
    3. VM indicators (to distinguish virtual from physical servers)

    Classification Results:
    - "Laptop" → ci_windows_workstation (portable devices)
    - "Desktop" → ci_windows_workstation (fixed workstations)
    - "Virtual Server" → ci_virtual_machine (VMs)
    - "Physical Server" → ci_windows_server (bare metal)
    - "Network Device" → ci_switch (routers, switches, etc.)
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
    Map ConnectWise device fields to ServiceDesk Plus CI fields.

    This class handles the translation of field names and values from
    ConnectWise format to ServiceDesk Plus CMDB format.

    ConnectWise stores data in nested JSON structures:
    - device.system.serialNumber
    - device.os.product
    - device.networks[0].ipv4

    ServiceDesk Plus uses flat field names with prefixes:
    - ci_attributes_txt_serial_number
    - ci_attributes_txt_os
    - ci_attributes_txt_ip_address

    The FIELD_MAP dictionary defines the mapping between these formats,
    along with optional transformation functions for data cleaning.

    Example:
        >>> mapper = FieldMapper(cw_device)
        >>> sdp_data = mapper.get_sdp_data()
        >>> print(sdp_data)
        {
            '_category': 'Laptop',
            'name': 'LAPTOP-001',
            'ci_attributes_txt_serial_number': 'ABC123',
            'ci_attributes_txt_os': 'Windows 11 Pro',
            ...
        }
    """

    # =========================================================================
    # FIELD MAPPING CONFIGURATION
    # =========================================================================

    # CW -> SDP field mapping
    # Format: 'sdp_field': ('cw_path', 'transformation_method_name')
    #
    # cw_path uses dot notation for nested fields (e.g., 'system.serialNumber')
    # transformation_method_name is the name of a method on this class (or None)
    FIELD_MAP = {
        # CI Name - uses the CW friendly name (computer name)
        'name': ('friendlyName', None),

        # Serial Number - from system.serialNumber, cleaned to remove VM UUIDs
        'ci_attributes_txt_serial_number': ('system.serialNumber', '_clean_serial'),

        # Service Tag - same as serial number for most devices
        'ci_attributes_txt_service_tag': ('system.serialNumber', '_clean_serial'),

        # Operating System - from os.product (e.g., "Windows 11 Pro")
        'ci_attributes_txt_os': ('os.product', None),

        # Manufacturer - from bios.manufacturer, normalized (LENOVO → Lenovo)
        'ci_attributes_txt_manufacturer': ('bios.manufacturer', '_clean_manufacturer'),

        # IP Address - extracted from networks array (first valid internal IP)
        'ci_attributes_txt_ip_address': ('networks', '_extract_ip'),

        # MAC Address - extracted from networks array (comma-separated if multiple)
        'ci_attributes_txt_mac_address': ('networks', '_extract_mac'),

        # Processor - from processor.product (e.g., "Intel Core i7-1165G7")
        'ci_attributes_txt_processor_name': ('processor.product', None),
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

        Iterates through FIELD_MAP, extracts values from the CW device,
        applies any transformations, and returns a dictionary ready for
        SDP API calls.

        Returns:
            Dictionary with SDP field names as keys. Includes special
            '_category' key with the device classification.

        Example:
            >>> mapper = FieldMapper(cw_device)
            >>> data = mapper.get_sdp_data()
            >>> print(data['name'])  # "LAPTOP-001"
            >>> print(data['_category'])  # "Laptop"
        """
        # Start with the category (used to determine CI type)
        result = {'_category': self.category}

        # Process each field mapping
        for sdp_field, (cw_path, transform) in self.FIELD_MAP.items():
            # Extract value from nested CW structure
            value = self._get_nested(cw_path)

            # Apply transformation if specified
            if transform and hasattr(self, transform):
                value = getattr(self, transform)(value)

            # Only include non-empty values
            if value:
                result[sdp_field] = value

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

        Args:
            networks: List of network adapter dictionaries

        Returns:
            First valid internal IP address, or None
        """
        if not networks:
            return None

        for net in networks:
            ip = net.get('ipv4', '')
            # Skip invalid/loopback addresses
            if ip and ip != '0.0.0.0' and not ip.startswith('127.'):
                return ip

        return None

    def _extract_mac(self, networks: list) -> Optional[str]:
        """
        Extract MAC addresses from networks array.

        Returns all MAC addresses as a comma-separated string.

        Args:
            networks: List of network adapter dictionaries

        Returns:
            Comma-separated MAC addresses, or None if none found
        """
        if not networks:
            return None

        # Collect all MAC addresses
        macs = [net.get('macAddress') for net in networks if net.get('macAddress')]

        return ', '.join(macs) if macs else None

