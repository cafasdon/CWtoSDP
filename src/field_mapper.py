"""
Field Mapper: CW -> SDP field mapping with classification logic.

This module handles:
1. Device type classification (Laptop, Virtual Server, Physical Server, Network Device)
2. Field mapping from ConnectWise to ServiceDesk Plus
3. Data transformations (parsing nested JSON, formatting values)
"""
import json
import re
from typing import Dict, Any, Optional, Tuple


class DeviceClassifier:
    """Classify CW devices into SDP asset categories."""

    # Known laptop model patterns (Lenovo part numbers, HP ProBook, etc.)
    LAPTOP_PATTERNS = [
        r'^\d{2}[A-Z0-9]{2}\d{3,4}[A-Z]{2}$',  # Lenovo: 21BT000BUK, 21C1002VUK, 21SX000VUK
        r'ProBook',
        r'EliteBook',
        r'Latitude',
        r'ThinkPad',
        r'Pavilion',
        r'MacBook',
        r'XPS',
        r'Inspiron',
        r'ZBook',
    ]

    # Known desktop model patterns
    DESKTOP_PATTERNS = [
        r'OptiPlex',
        r'ThinkCentre',
        r'ProDesk',
        r'EliteDesk',
        r'Precision Tower',
    ]
    
    @classmethod
    def classify(cls, device: Dict[str, Any]) -> str:
        """
        Classify a CW device into an SDP category.
        
        Returns one of: Laptop, Desktop, Virtual Server, Physical Server, Network Device
        """
        endpoint_type = device.get('endpointType', '')
        resource_type = device.get('resourceType', '')
        
        if endpoint_type == 'NetworkDevice':
            return 'Network Device'
        
        if endpoint_type == 'Desktop':
            # Check if it's actually a laptop based on model
            model = device.get('system', {}).get('model', '') or ''
            if cls._is_desktop(model):
                return 'Desktop'
            # Default to laptop for portable devices (ThinkPads, ProBooks, etc.)
            # Since CW "Desktop" = endpoint with agent, most are laptops
            return 'Laptop'
        
        if endpoint_type == 'Server':
            if cls._is_virtual(device):
                return 'Virtual Server'
            return 'Physical Server'
        
        return 'Unknown'
    
    @classmethod
    def _is_laptop(cls, model: str) -> bool:
        """Check if model name indicates a laptop."""
        for pattern in cls.LAPTOP_PATTERNS:
            if re.search(pattern, model, re.IGNORECASE):
                return True
        return False

    @classmethod
    def _is_desktop(cls, model: str) -> bool:
        """Check if model name indicates a desktop workstation."""
        for pattern in cls.DESKTOP_PATTERNS:
            if re.search(pattern, model, re.IGNORECASE):
                return True
        # Virtual Machine is a desktop-like category
        if 'Virtual Machine' in model:
            return True
        return False
    
    @classmethod
    def _is_virtual(cls, device: Dict[str, Any]) -> bool:
        """Check if device is a virtual machine."""
        checks = [
            device.get('system', {}).get('serialNumber', ''),
            device.get('bios', {}).get('manufacturer', ''),
            device.get('system', {}).get('model', ''),
        ]
        vm_indicators = ['VMware', 'Virtual', 'Hyper-V', 'QEMU', 'VirtualBox', 'Xen']
        for value in checks:
            if value:
                for indicator in vm_indicators:
                    if indicator.lower() in str(value).lower():
                        return True
        return False


class FieldMapper:
    """Map CW fields to SDP fields."""
    
    # CW -> SDP field mapping
    # Format: 'sdp_field': ('cw_path', transformation_function)
    FIELD_MAP = {
        'name': ('friendlyName', None),
        'ci_attributes_txt_serial_number': ('system.serialNumber', '_clean_serial'),
        'ci_attributes_txt_service_tag': ('system.serialNumber', '_clean_serial'),
        'ci_attributes_txt_os': ('os.product', None),
        'ci_attributes_txt_manufacturer': ('bios.manufacturer', '_clean_manufacturer'),
        'ci_attributes_txt_ip_address': ('networks', '_extract_ip'),
        'ci_attributes_txt_mac_address': ('networks', '_extract_mac'),
        'ci_attributes_txt_processor_name': ('processor.product', None),
    }
    
    def __init__(self, cw_device: Dict[str, Any]):
        """Initialize with a CW device (raw JSON)."""
        self.device = cw_device
        self.category = DeviceClassifier.classify(cw_device)
    
    def get_sdp_data(self) -> Dict[str, Any]:
        """Map CW device to SDP field values."""
        result = {'_category': self.category}
        
        for sdp_field, (cw_path, transform) in self.FIELD_MAP.items():
            value = self._get_nested(cw_path)
            if transform and hasattr(self, transform):
                value = getattr(self, transform)(value)
            if value:
                result[sdp_field] = value
        
        return result
    
    def _get_nested(self, path: str) -> Any:
        """Get nested value from device dict using dot notation."""
        parts = path.split('.')
        value = self.device
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value
    
    def _clean_serial(self, value: str) -> Optional[str]:
        """Clean serial number, return None for VM serials."""
        if not value:
            return None
        if 'VMware' in value or 'Virtual' in value:
            return None  # Skip VM UUIDs
        return value.strip()
    
    def _clean_manufacturer(self, value: str) -> Optional[str]:
        """Clean manufacturer name."""
        if not value or 'VMware' in value:
            return None
        # Normalize common names
        mapping = {
            'LENOVO': 'Lenovo',
            'Hewlett-Packard': 'HP',
            'Dell Inc.': 'Dell',
        }
        return mapping.get(value, value)
    
    def _extract_ip(self, networks: list) -> Optional[str]:
        """Extract first valid internal IP from networks array."""
        if not networks:
            return None
        for net in networks:
            ip = net.get('ipv4', '')
            if ip and ip != '0.0.0.0' and not ip.startswith('127.'):
                return ip
        return None
    
    def _extract_mac(self, networks: list) -> Optional[str]:
        """Extract MAC addresses from networks array."""
        if not networks:
            return None
        macs = [net.get('macAddress') for net in networks if net.get('macAddress')]
        return ', '.join(macs) if macs else None

