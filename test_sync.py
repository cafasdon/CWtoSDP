"""Test sync preview."""
from src.sync_engine import SyncEngine, SyncAction

engine = SyncEngine()
items = engine.build_sync_preview()
summary = engine.get_summary(items)

print("="*80)
print("SYNC PREVIEW: CW -> SDP")
print("="*80)

print(f"\nTotal CW devices: {summary['total']}")

print("\nBy Action:")
for action, count in sorted(summary['by_action'].items()):
    print(f"  {action.upper()}: {count}")

print("\nBy CW Category:")
for cat, count in sorted(summary['by_category'].items()):
    print(f"  {cat}: {count}")

print("\nBy SDP CI Type:")
for ci_type, count in sorted(summary['by_ci_type'].items()):
    print(f"  {ci_type}: {count}")

# Show sample of each action type
print("\n" + "="*80)
print("SAMPLE: Items to CREATE (new in SDP)")
print("="*80)
creates = [i for i in items if i.action == SyncAction.CREATE][:10]
for item in creates:
    print(f"  {item.cw_name:30} | {item.cw_category:15} -> {item.sdp_ci_type}")

print("\n" + "="*80)
print("SAMPLE: Items to UPDATE (matched in SDP)")
print("="*80)
updates = [i for i in items if i.action == SyncAction.UPDATE][:10]
for item in updates:
    print(f"  {item.cw_name:30} | {item.cw_category:15} | Match: {item.match_reason}")

# Show fields that would be synced for one update
print("\n" + "="*80)
print("SAMPLE: Fields to sync for first UPDATE")
print("="*80)
if updates:
    item = updates[0]
    print(f"CW: {item.cw_name} -> SDP: {item.sdp_name}")
    for field, value in item.fields_to_sync.items():
        clean = field.replace('ci_attributes_txt_', '')
        print(f"  {clean}: {value}")

engine.close()

