import os
import json
import hashlib

target_file = "kavach_chain.json"
found_path = None

for root, dirs, files in os.walk("."):
    if target_file in files:
        found_path = os.path.join(root, target_file)
        break

if not found_path:
    print("Error: Could not find kavach_chain.json in directory structure.")
    exit(1)

print("Found ledger at:", found_path)

with open(found_path, "r") as f:
    chain = json.load(f)

if isinstance(chain, dict):
    chain = [chain]

chain_valid = True

for block in chain:
    block_copy = json.loads(json.dumps(block))
    stored_hash = block_copy.pop("hash", None)
    
    calculated_hash = hashlib.sha256(json.dumps(block_copy, sort_keys=True).encode("utf-8")).hexdigest()
    
    idx = block.get("index", "Unknown")
    if calculated_hash != stored_hash:
        print(f"[TAMPER DETECTED] Block #{idx} has been modified!")
        print(f"   Stored Hash:     {stored_hash}")
        print(f"   Calculated Hash: {calculated_hash}\n")
        chain_valid = False
    else:
        print(f"[OK] Block #{idx} is valid.")

if chain_valid:
    print("Entire chain integrity verified!")
else:
    print("CHAIN CORRUPTED: One or more blocks failed verification.")

