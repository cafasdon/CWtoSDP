"""Test the field mapper."""
import sqlite3
import json
from src.field_mapper import FieldMapper, DeviceClassifier

conn = sqlite3.connect('data/cwtosdp_compare.db')
cursor = conn.cursor()

print('='*80)
print('FIELD MAPPER TEST - CW -> SDP Transformation')
print('='*80)

# Test with different device types
test_cases = [
    ('Laptop', "endpointType = 'Desktop' AND system_serialNumber NOT LIKE '%VMware%'"),
    ('Virtual Server', "endpointType = 'Server' AND bios_manufacturer LIKE '%VMware%'"),
    ('Physical Server', "endpointType = 'Server' AND bios_manufacturer NOT LIKE '%VMware%'"),
    ('Network Device', "endpointType = 'NetworkDevice'"),
]

for expected_type, where in test_cases:
    print(f'\n--- Testing: {expected_type} ---')
    cursor.execute(f'SELECT raw_json FROM cw_devices_full WHERE {where} LIMIT 1')
    row = cursor.fetchone()
    if row:
        device = json.loads(row[0])
        mapper = FieldMapper(device)
        sdp_data = mapper.get_sdp_data()
        
        print(f'CW Device: {device.get("friendlyName")}')
        print(f'Classified as: {sdp_data.pop("_category")}')
        print('SDP Fields:')
        for field, value in sdp_data.items():
            clean_field = field.replace('ci_attributes_txt_', '')
            print(f'  {clean_field:20}: {value}')

# Summary stats
print('\n' + '='*80)
print('CLASSIFICATION SUMMARY')
print('='*80)

cursor.execute('SELECT raw_json FROM cw_devices_full')
categories = {}
for row in cursor.fetchall():
    device = json.loads(row[0])
    cat = DeviceClassifier.classify(device)
    categories[cat] = categories.get(cat, 0) + 1

for cat, count in sorted(categories.items()):
    print(f'  {cat:20}: {count}')

conn.close()

