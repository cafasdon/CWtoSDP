"""Analyze data quality for matching."""
import sqlite3

conn = sqlite3.connect('data/cwtosdp_compare.db')
cursor = conn.cursor()

print('=' * 80)
print('DATA ANALYSIS: ConnectWise vs ServiceDesk Plus')
print('=' * 80)

# ============== ConnectWise Analysis ==============
print('\n' + '='*40)
print('CONNECTWISE ANALYSIS')
print('='*40)

cursor.execute('SELECT COUNT(*) FROM cw_devices_full')
cw_total = cursor.fetchone()[0]
print(f'\nTotal CW devices: {cw_total}')

cursor.execute('SELECT COUNT(DISTINCT friendlyName) FROM cw_devices_full')
print(f'Unique hostnames (friendlyName): {cursor.fetchone()[0]}')

cursor.execute('SELECT COUNT(DISTINCT remoteAddress) FROM cw_devices_full')
print(f'Unique IP addresses (remoteAddress): {cursor.fetchone()[0]}')

print(f'\nIP Address Distribution (shared IPs):')
cursor.execute('''
    SELECT remoteAddress, COUNT(*) as cnt 
    FROM cw_devices_full 
    GROUP BY remoteAddress 
    HAVING cnt > 1
    ORDER BY cnt DESC
    LIMIT 10
''')
for row in cursor.fetchall():
    print(f'  {row[0]}: {row[1]} devices')

cursor.execute('''SELECT COUNT(DISTINCT system_serialNumber) FROM cw_devices_full 
                  WHERE system_serialNumber IS NOT NULL AND system_serialNumber != ""''')
print(f'\nUnique serial numbers: {cursor.fetchone()[0]}')

cursor.execute('''SELECT COUNT(*) FROM cw_devices_full 
                  WHERE system_serialNumber IS NULL OR system_serialNumber = "" OR system_serialNumber LIKE "%VMware%"''')
print(f'Missing/VMware serials: {cursor.fetchone()[0]}')

print(f'\nDevice Types:')
cursor.execute('SELECT endpointType, resourceType, COUNT(*) FROM cw_devices_full GROUP BY endpointType, resourceType')
for row in cursor.fetchall():
    print(f'  {row[0]} / {row[1]}: {row[2]}')

# Sample hostnames
print(f'\nSample CW hostnames:')
cursor.execute('SELECT friendlyName FROM cw_devices_full LIMIT 15')
for row in cursor.fetchall():
    print(f'  {row[0]}')

# ============== ServiceDesk Plus Analysis ==============
print('\n' + '='*40)
print('SERVICEDESK PLUS ANALYSIS')
print('='*40)

cursor.execute('SELECT COUNT(*) FROM sdp_workstations_full')
sdp_total = cursor.fetchone()[0]
print(f'\nTotal SDP workstations: {sdp_total}')

cursor.execute('SELECT COUNT(DISTINCT name) FROM sdp_workstations_full')
print(f'Unique names: {cursor.fetchone()[0]}')

cursor.execute('''SELECT COUNT(DISTINCT ci_attributes_txt_ip_address) FROM sdp_workstations_full
                  WHERE ci_attributes_txt_ip_address IS NOT NULL''')
print(f'Unique IP addresses: {cursor.fetchone()[0]}')

cursor.execute('''SELECT COUNT(DISTINCT ci_attributes_txt_serial_number) FROM sdp_workstations_full
                  WHERE ci_attributes_txt_serial_number IS NOT NULL AND ci_attributes_txt_serial_number != "None"''')
print(f'Unique serial numbers: {cursor.fetchone()[0]}')

cursor.execute('''SELECT COUNT(*) FROM sdp_workstations_full 
                  WHERE ci_attributes_txt_serial_number IS NULL OR ci_attributes_txt_serial_number = "None" OR ci_attributes_txt_serial_number = ""''')
print(f'Missing serials: {cursor.fetchone()[0]}')

# Sample names
print(f'\nSample SDP names:')
cursor.execute('SELECT name FROM sdp_workstations_full LIMIT 15')
for row in cursor.fetchall():
    print(f'  {row[0]}')

# ============== Matching Analysis ==============
print('\n' + '='*40)
print('MATCHING ANALYSIS')
print('='*40)

# Hostname matches
cursor.execute('''
    SELECT COUNT(*) FROM cw_devices_full cw
    INNER JOIN sdp_workstations_full sdp ON UPPER(cw.friendlyName) = UPPER(sdp.name)
''')
print(f'\nHostname matches (exact, case-insensitive): {cursor.fetchone()[0]}')

# Serial matches
cursor.execute('''
    SELECT COUNT(*) FROM cw_devices_full cw
    INNER JOIN sdp_workstations_full sdp ON UPPER(cw.system_serialNumber) = UPPER(sdp.ci_attributes_txt_serial_number)
    WHERE cw.system_serialNumber IS NOT NULL AND cw.system_serialNumber != "" 
    AND cw.system_serialNumber NOT LIKE "%VMware%"
''')
print(f'Serial number matches (excluding VMware): {cursor.fetchone()[0]}')

# Show some hostname matches
print(f'\nSample hostname matches:')
cursor.execute('''
    SELECT cw.friendlyName, sdp.name, cw.system_serialNumber, sdp.ci_attributes_txt_serial_number
    FROM cw_devices_full cw
    INNER JOIN sdp_workstations_full sdp ON UPPER(cw.friendlyName) = UPPER(sdp.name)
    LIMIT 10
''')
for row in cursor.fetchall():
    print(f'  CW: {row[0]:20} | SDP: {row[1]:20} | CW Serial: {str(row[2])[:25]:25} | SDP Serial: {str(row[3])[:20]}')

# CW devices NOT in SDP
cursor.execute('''
    SELECT COUNT(*) FROM cw_devices_full cw
    LEFT JOIN sdp_workstations_full sdp ON UPPER(cw.friendlyName) = UPPER(sdp.name)
    WHERE sdp.name IS NULL
''')
print(f'\nCW devices NOT in SDP (by hostname): {cursor.fetchone()[0]}')

# SDP workstations NOT in CW
cursor.execute('''
    SELECT COUNT(*) FROM sdp_workstations_full sdp
    LEFT JOIN cw_devices_full cw ON UPPER(sdp.name) = UPPER(cw.friendlyName)
    WHERE cw.friendlyName IS NULL
''')
print(f'SDP workstations NOT in CW (by hostname): {cursor.fetchone()[0]}')

# ============== Understanding the IP Issue ==============
print('\n' + '='*40)
print('IP ADDRESS DEEP DIVE')
print('='*40)

# Why 162 devices share one IP?
print('\nDevices sharing 62.232.46.98:')
cursor.execute('''
    SELECT friendlyName, endpointType, resourceType
    FROM cw_devices_full
    WHERE remoteAddress = "62.232.46.98"
    LIMIT 20
''')
for row in cursor.fetchall():
    print(f'  {row[0]:30} | {row[1]:15} | {row[2]}')

print('\n... This IP is likely a NAT/gateway IP. These are all behind the same firewall.')

# Check if CW has internal IP addresses
print('\n' + '='*40)
print('INTERNAL IP ANALYSIS')
print('='*40)

# Get all columns that might have network info
cursor.execute("PRAGMA table_info(cw_devices_full)")
cols = [row[1] for row in cursor.fetchall()]
network_cols = [c for c in cols if 'network' in c.lower() or 'ip' in c.lower()]
print(f'\nNetwork-related columns in CW: {network_cols}')

# Check networks column (it contains internal IPs)
cursor.execute('SELECT friendlyName, networks FROM cw_devices_full LIMIT 1')
row = cursor.fetchone()
if row and row[1]:
    import json
    try:
        networks = json.loads(row[1])
        print(f'\nSample networks data for {row[0]}:')
        for net in networks[:2]:
            print(f'  IPv4: {net.get("ipv4")} | MAC: {net.get("macAddress")}')
    except:
        print(f'  Networks data: {row[1][:200]}')

# ============== Naming Pattern Analysis ==============
print('\n' + '='*40)
print('NAMING PATTERN ANALYSIS')
print('='*40)

# CW naming patterns
print('\nCW hostname patterns:')
cursor.execute('SELECT friendlyName FROM cw_devices_full')
cw_names = [row[0] for row in cursor.fetchall()]

patterns = {}
for name in cw_names:
    if name.startswith('V0100553'):
        patterns['V0100553*'] = patterns.get('V0100553*', 0) + 1
    elif name.startswith('DMH'):
        patterns['DMH*'] = patterns.get('DMH*', 0) + 1
    elif name.startswith('XCC'):
        patterns['XCC*'] = patterns.get('XCC*', 0) + 1
    elif name.startswith('BDR'):
        patterns['BDR*'] = patterns.get('BDR*', 0) + 1
    else:
        patterns['Other'] = patterns.get('Other', 0) + 1

for pat, cnt in sorted(patterns.items(), key=lambda x: -x[1]):
    print(f'  {pat}: {cnt}')

# SDP naming patterns
print('\nSDP hostname patterns:')
cursor.execute('SELECT name FROM sdp_workstations_full')
sdp_names = [row[0] for row in cursor.fetchall()]

patterns = {}
for name in sdp_names:
    if name and name.startswith('DMH'):
        patterns['DMH*'] = patterns.get('DMH*', 0) + 1
    elif name and name.startswith('DESKTOP'):
        patterns['DESKTOP*'] = patterns.get('DESKTOP*', 0) + 1
    elif name and name.startswith('V0100553'):
        patterns['V0100553*'] = patterns.get('V0100553*', 0) + 1
    elif name and name.startswith('SCD'):
        patterns['SCD*'] = patterns.get('SCD*', 0) + 1
    else:
        patterns['Other'] = patterns.get('Other', 0) + 1

for pat, cnt in sorted(patterns.items(), key=lambda x: -x[1]):
    print(f'  {pat}: {cnt}')

# ============== Understanding Device Types ==============
print('\n' + '='*40)
print('WHAT IS EACH SYSTEM TRACKING?')
print('='*40)

print('\nConnectWise is tracking:')
print('  - 164 Servers (mostly virtual machines with VMware serials)')
print('  - 25 Desktops')
print('  - 15 Network Devices (switches, firewalls)')
print('  - External/NAT IP addresses (not internal)')

print('\nServiceDesk Plus is tracking:')
print('  - 690 "Workstations" (CMDB category)')
print('  - Mix of physical laptops/desktops and some servers')
print('  - Primarily user endpoints (DMH*, DESKTOP*, SCD* naming)')

# Key insight
print('\n' + '='*40)
print('KEY INSIGHTS')
print('='*40)
print('''
1. CW primarily tracks SERVERS (164/204 = 80%)
   - Most are VMware VMs with naming like V0100553*
   - External/NAT IPs only - 162 devices share one IP

2. SDP primarily tracks USER WORKSTATIONS (690 total)
   - DMH*, DESKTOP*, SCD* naming patterns
   - Physical devices with unique serials

3. Only 31 hostname matches found - these are servers that exist in both

4. IP matching WON'T work reliably because:
   - CW stores external/NAT IPs (many devices share same IP)
   - Need to parse "networks" JSON column for internal IPs

5. Serial matching is limited because:
   - CW VMs have "VMware-*" serials
   - SDP has mostly physical device serials

6. BEST APPROACH: Match by HOSTNAME (case-insensitive)
   - 31 devices currently match
   - 173 CW devices are NOT in SDP (need to create?)
   - 659 SDP workstations are NOT in CW (different device types)
''')

conn.close()

