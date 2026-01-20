"""Analyze device classification for CW -> SDP sync."""
import sqlite3
import json

conn = sqlite3.connect('data/cwtosdp_compare.db')
cursor = conn.cursor()

print('LENOVO MODEL CODES (from CW "Desktop" devices):')
print('  21BT000BUK = ThinkPad L14 Gen 3')
print('  20X100LWUK = ThinkPad T14 Gen 2')
print('  21C1002VUK = ThinkPad L14 Gen 3 AMD')
print('  21CB0064UK = ThinkPad L15 Gen 3')
print('  21SX000VUK = ThinkPad L14 Gen 5')
print('  HP ProBook 450 G7 = HP Laptop')
print()
print('=> All 25 CW "Desktop" devices are actually LAPTOPS!')
print()

# Check servers - can we identify VMs vs Physical?
print('='*80)
print('SERVER CLASSIFICATION: VM vs Physical')
print('='*80)

cursor.execute('''
    SELECT 
        friendlyName,
        system_model,
        bios_manufacturer,
        system_serialNumber
    FROM cw_devices_full 
    WHERE endpointType = 'Server'
''')

vm_count = 0
physical = []
for row in cursor.fetchall():
    is_vm = 'VMware' in str(row[2]) or 'VMware' in str(row[3]) or 'Virtual' in str(row[1])
    if is_vm:
        vm_count += 1
    else:
        physical.append(row)

print(f'\nPhysical Servers ({len(physical)}):')
for row in physical[:20]:
    print(f'  {row[0]:35} | {str(row[2])[:15]:15} | Serial: {str(row[3])[:20]}')

cursor.execute('SELECT COUNT(*) FROM cw_devices_full WHERE endpointType = "Server"')
total = cursor.fetchone()[0]
print(f'\nTotal Servers: {total}')
print(f'  Virtual Machines: {vm_count}')
print(f'  Physical Servers: {len(physical)}')

# Network devices
print('\n' + '='*80)
print('NETWORK DEVICES')
print('='*80)

cursor.execute('''
    SELECT friendlyName, resourceType, system_model
    FROM cw_devices_full 
    WHERE endpointType = 'NetworkDevice'
''')
for row in cursor.fetchall():
    print(f'  {row[0]:35} | {row[1]:15} | {row[2]}')

# Final classification summary
print('\n' + '='*80)
print('FINAL CW -> SDP CLASSIFICATION')
print('='*80)

print('''
CW endpointType    | CW resourceType  | SDP Category    | Count
-------------------|------------------|-----------------|-------
Desktop            | Desktop          | Laptop          | 25
Server             | Server (VM)      | Virtual Server  | ''' + str(vm_count) + '''
Server             | Server (Physical)| Physical Server | ''' + str(len(physical)) + '''
NetworkDevice      | FIREWALL         | Network Device  | 1
NetworkDevice      | SWITCH           | Network Device  | 4
NetworkDevice      | LAYER_3_SWITCH   | Network Device  | 1
NetworkDevice      | MODULE           | Network Device  | 9

Classification Logic:
1. endpointType = 'Desktop' -> Laptop (all are ThinkPads/ProBooks)
2. endpointType = 'Server' + 'VMware' in serial/manufacturer -> Virtual Server
3. endpointType = 'Server' + real serial -> Physical Server
4. endpointType = 'NetworkDevice' -> Network Device
''')

conn.close()

