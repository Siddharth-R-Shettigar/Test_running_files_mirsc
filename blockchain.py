import hashlib
import json
import os
import time

CHAIN_FILE = os.path.join(os.path.dirname(__file__), "data", "kavach_chain.json")

class Block:
    def __init__(self, index, timestamp, data, previous_hash, nonce=0):
        self.index = index
        self.timestamp = timestamp
        self.data = data
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d):
        b = cls(d["index"], d["timestamp"], d["data"], d["previous_hash"], d.get("nonce", 0))
        b.hash = d["hash"]
        return b

class KavachChain:
    def __init__(self, difficulty=2):
        self.difficulty = difficulty
        self.chain = []
        self._load_or_create()

    def _create_genesis(self):
        return Block(0, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     {"message": "KAVACH Genesis", "type": "genesis"}, "0"*64)

    def _load_or_create(self):
        os.makedirs(os.path.dirname(CHAIN_FILE), exist_ok=True)
        if os.path.exists(CHAIN_FILE):
            try:
                with open(CHAIN_FILE) as f:
                    raw = json.load(f)
                self.chain = [Block.from_dict(b) for b in raw]
                if not self.is_chain_valid():
                    self.chain = [self._create_genesis()]
                    self._save()
            except:
                self.chain = [self._create_genesis()]
                self._save()
        else:
            self.chain = [self._create_genesis()]
            self._save()

    def _save(self):
        with open(CHAIN_FILE, "w") as f:
            json.dump([b.to_dict() for b in self.chain], f, indent=2)

    def get_latest_block(self):
        return self.chain[-1]

    def proof_of_work(self, block):
        target = "0" * self.difficulty
        while not block.hash.startswith(target):
            block.nonce += 1
            block.hash = block.calculate_hash()
        return block

    def add_report_anchor(self, report_hash, case_id=None, risk_level=None, extra=None):
        data = {
            "type": "report_anchor",
            "report_hash": report_hash,
            "case_id": case_id,
            "risk_level": risk_level,
            "anchored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if extra:
            data.update(extra)
        prev = self.get_latest_block()
        new_block = Block(prev.index + 1,
                          time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          data, prev.hash)
        new_block = self.proof_of_work(new_block)
        self.chain.append(new_block)
        self._save()
        return {
            "block_index": new_block.index,
            "block_hash": new_block.hash,
            "previous_hash": new_block.previous_hash,
            "timestamp": new_block.timestamp,
            "report_hash": report_hash,
            "difficulty": self.difficulty,
        }

    def is_chain_valid(self):
        for i in range(1, len(self.chain)):
            cur = self.chain[i]
            prev = self.chain[i-1]
            if cur.hash != cur.calculate_hash():
                return False
            if cur.previous_hash != prev.hash:
                return False
            if not cur.hash.startswith("0" * self.difficulty):
                return False
        return True

    def verify_report_hash(self, report_hash):
        if not self.is_chain_valid():
            return {"valid": False, "reason": "chain broken"}
        matches = [b for b in self.chain if b.data.get("report_hash") == report_hash]
        if not matches:
            return {"valid": False, "reason": "not found"}
        b = matches[-1]
        return {
            "valid": True,
            "block_index": b.index,
            "block_hash": b.hash,
            "timestamp": b.timestamp,
        }

    def get_chain_summary(self):
        return {
            "length": len(self.chain),
            "latest_hash": self.get_latest_block().hash,
            "is_valid": self.is_chain_valid(),
            "difficulty": self.difficulty,
        }

_chain = None

def get_chain():
    global _chain
    if _chain is None:
        _chain = KavachChain()
    return _chain
