import hashlib
import json

# 1. Original valid block data from your blockchain
original_block = {
    "index": 7,
    "timestamp": "2026-09-19T17:32:05Z",
    "data": {
        "type": "report_anchor",
        "report_hash": "7d98b5d724f3329a91ad6bf50bd6f92dda7097c790e70af366527114da402889",
        "case_id": None,
        "risk_level": "REVIEW",
        "anchored_at": "2026-09-19T17:32:05Z",
        "file_analyzed": "adhaar_card.jpeg",
        "engine": "KAVACH",
    },
    "previous_hash": "00eb742bc24aaf03a732652ab0cb4320e8278a1200027e4c216de2c18dcf4ce6",
    "nonce": 190,
}

expected_hash = (
    "00b0447916bcca6abd4cef35b605958818be781e1c109dc4575aeef751a70c56"
)


def calculate_hash(block):
    # Converts block dictionary to a deterministic JSON string and calculates SHA-256
    block_string = json.dumps(block, sort_keys=True).encode("utf-8")
    return hashlib.sha256(block_string).hexdigest()


# --- TEST 1: Check Original Block ---
original_calculated = calculate_hash(original_block)
print("=== ORIGINAL BLOCK CHECK ===")
print("Expected Hash:  ", expected_hash)
print("Calculated Hash:", original_calculated)
print("Match?          ", original_calculated == expected_hash)
print()

# --- TEST 2: Tamper with Data ("REVIEW" -> "PASS") ---
# We create a copy and modify 1 value
tampered_block = json.loads(json.dumps(original_block))
tampered_block["data"]["risk_level"] = "PASS"

tampered_calculated = calculate_hash(tampered_block)

print("=== TAMPERED BLOCK CHECK ===")
print("Modified field:  risk_level = 'PASS'")
print("Expected Hash:  ", expected_hash)
print("Calculated Hash:", tampered_calculated)
print("Match?          ", tampered_calculated == expected_hash)

if tampered_calculated != expected_hash:
    print("\n✓ TAMPER DETECTED: Changing 1 character completely broke the hash!")