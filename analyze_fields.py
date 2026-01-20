"""Analyze SDP and CW fields for mapping."""
import sqlite3
import json

conn = sqlite3.connect('data/cwtosdp_compare.db')
cursor = conn.cursor()

print('='*80)
print('SDP FIELD ANALYSIS - What fields need to be populated?')
print('='*80)

# Get all SDP columns
cursor.execute('PRAGMA table_info(sdp_workstations_full)')
sdp_cols = [row[1] for row in cursor.fetchall() if row[1] not in ('id', 'raw_json', 'fetched_at', 'sdp_id')]

# Categorize SDP fields
ci_attrs = [c for c in sdp_cols if c.startswith('ci_attributes_')]
other = [c for c in sdp_cols if not c.startswith('ci_attributes_')]

print(f'\nTotal SDP fields: {len(sdp_cols)}')
print(f'  - ci_attributes_* fields: {len(ci_attrs)}')
print(f'  - Other fields: {len(other)}')

# Show ci_attributes breakdown
txt_fields = [c for c in ci_attrs if '_txt_' in c]
ref_fields = [c for c in ci_attrs if '_ref_' in c]

print(f'\nci_attributes breakdown:')
print(f'  - _txt_ (text fields): {len(txt_fields)}')
print(f'  - _ref_ (reference/lookup fields): {len(ref_fields)}')

# Show the actual TEXT fields
print(f'\n' + '='*40)
print('SDP TEXT FIELDS (directly populatable):')
print('='*40)
for field in sorted(txt_fields):
    clean_name = field.replace('ci_attributes_txt_', '')
    cursor.execute(f'SELECT "{field}" FROM sdp_workstations_full WHERE "{field}" IS NOT NULL LIMIT 1')
    row = cursor.fetchone()
    sample = str(row[0])[:40] if row else 'NULL'
    print(f'  {clean_name:30} | Sample: {sample}')

# CW fields analysis
print(f'\n' + '='*80)
print('CW FIELD ANALYSIS')
print('='*80)

cursor.execute('PRAGMA table_info(cw_devices_full)')
cw_cols = [row[1] for row in cursor.fetchall() if row[1] not in ('id', 'raw_json', 'fetched_at', 'endpointID')]

print(f'\nTotal CW fields: {len(cw_cols)}')

# Group by prefix
prefixes = {}
for col in cw_cols:
    if '_' in col:
        prefix = col.split('_')[0]
    else:
        prefix = 'root'
    prefixes.setdefault(prefix, []).append(col)

print('\nCW fields by category:')
for prefix, cols in sorted(prefixes.items()):
    print(f'  {prefix}: {len(cols)} fields')
    for col in cols[:5]:
        cursor.execute(f'SELECT "{col}" FROM cw_devices_full WHERE "{col}" IS NOT NULL LIMIT 1')
        row = cursor.fetchone()
        sample = str(row[0])[:35] if row else 'NULL'
        print(f'    - {col}: {sample}')
    if len(cols) > 5:
        print(f'    ... and {len(cols)-5} more')

# CW device type breakdown
print(f'\n' + '='*80)
print('CW DEVICE CLASSIFICATION')
print('='*80)

cursor.execute('''
    SELECT endpointType, resourceType, COUNT(*) 
    FROM cw_devices_full 
    GROUP BY endpointType, resourceType
''')
for row in cursor.fetchall():
    print(f'  {row[0]:15} / {row[1]:20} : {row[2]} devices')

# Check if we can differentiate laptops vs desktops
print('\n' + '='*40)
print('Desktop vs Laptop differentiation:')
print('='*40)

cursor.execute('''
    SELECT friendlyName, system_model, system_product, raw_json
    FROM cw_devices_full
    WHERE endpointType = 'Desktop'
''')
for row in cursor.fetchall():
    data = json.loads(row[3])
    chassis = data.get('chassis', {})
    chassis_type = chassis.get('chassisType', '?')
    print(f'  {row[0]:20} | Model: {str(row[1])[:22]:22} | Chassis: {chassis_type}')

# FIELD MAPPING
print('\n' + '='*80)
print('PROPOSED FIELD MAPPING: CW -> SDP')
print('='*80)

mapping = [
    ('name', 'friendlyName', 'Direct copy'),
    ('ip_address', 'networks[0].ipv4', 'Parse from networks JSON'),
    ('mac_address', 'networks[0].macAddress', 'Parse from networks JSON'),
    ('os', 'os_product', 'Direct copy'),
    ('serial_number', 'system_serialNumber', 'Use system, fallback to bios'),
    ('service_tag', 'system_serialNumber', 'Same as serial'),
    ('manufacturer', 'bios_manufacturer', 'HP, Dell, Lenovo, etc.'),
    ('processor_name', 'processor.product', 'Parse from processor JSON'),
]

print(f'\n{"SDP Field":25} | {"CW Source":30} | Notes')
print('-'*80)
for sdp, cw, notes in mapping:
    print(f'  {sdp:23} | {cw:30} | {notes}')

# Sample device
print('\n' + '='*80)
print('SAMPLE CW DEVICE (Desktop with physical serial)')
print('='*80)

cursor.execute('''
    SELECT raw_json FROM cw_devices_full
    WHERE endpointType = 'Desktop' AND system_serialNumber NOT LIKE '%VMware%'
    LIMIT 1
''')
row = cursor.fetchone()
if row:
    data = json.loads(row[0])
    print(f"friendlyName: {data.get('friendlyName')}")
    print(f"endpointType: {data.get('endpointType')}")
    print(f"os.product: {data.get('os', {}).get('product')}")
    print(f"system.serialNumber: {data.get('system', {}).get('serialNumber')}")
    print(f"system.model: {data.get('system', {}).get('model')}")
    print(f"bios.manufacturer: {data.get('bios', {}).get('manufacturer')}")
    print(f"chassis.chassisType: {data.get('chassis', {}).get('chassisType')}")
    networks = data.get('networks', [])
    if networks:
        print(f"networks[0].ipv4: {networks[0].get('ipv4')}")
        print(f"networks[0].macAddress: {networks[0].get('macAddress')}")
    processor = data.get('processor', {})
    print(f"processor.product: {processor.get('product')}")

conn.close()

