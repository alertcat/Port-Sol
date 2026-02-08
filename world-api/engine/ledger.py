"""Ledger persistence: audit log"""
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

class LedgerWriter:
    """Ledger writer"""
    
    def __init__(self, filepath: str = "ledger.jsonl"):
        self.filepath = filepath
        self._ensure_dir()
    
    def _ensure_dir(self):
        """Ensure directory exists"""
        dir_path = os.path.dirname(self.filepath)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path)
    
    def write(self, entry: Dict[str, Any]):
        """Write one entry"""
        entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def read_all(self) -> List[Dict[str, Any]]:
        """Read all entries"""
        if not os.path.exists(self.filepath):
            return []
        
        entries = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        return entries
    
    def clear(self):
        """Clear ledger (for testing)"""
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
