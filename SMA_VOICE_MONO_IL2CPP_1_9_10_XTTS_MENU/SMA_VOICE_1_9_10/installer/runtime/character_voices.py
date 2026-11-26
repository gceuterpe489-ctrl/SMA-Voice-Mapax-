"""Persistent, balanced random voice assignment for verified character GUIDs."""
import json
import random
import re
import uuid
from pathlib import Path

VOICES = ('Ana Florence', 'Claribel Dervla', 'Daisy Studious', 'Gracie Wise')

def canonical_id(value):
    try:
        key = uuid.UUID(str(value).strip())
        return str(key) if key.int else None
    except (ValueError, TypeError, AttributeError):
        return None

def valid_voice_id(value):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=256 and (not value.startswith('custom:') or re.fullmatch(r'custom:[0-9a-f]{64}',value) is not None)

class CharacterVoices:
    def __init__(self, path, available, rng=None):
        self.path = Path(path)
        self.rng = rng or random.SystemRandom()
        self.voices = tuple(v for v in VOICES if v in available)
        if not self.voices:
            self.voices = tuple(available)[:1]
        self.mapping = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if not isinstance(raw, dict) or any(not canonical_id(k) or not valid_voice_id(v) for k,v in raw.items()):
                raise ValueError('character_voices.json invalido; preserve o arquivo e corrija os dados.')
            self.mapping = {canonical_id(k): v for k,v in raw.items()}

    def select(self, actor):
        key = canonical_id(actor)
        if key is None:
            # Shared prefab path is NOT a character ID. No permanent assignment.
            return self.voices[0], False, False
        if key in self.mapping:
            chosen = self.mapping[key]
            if chosen in self.voices:
                return chosen, False, True
            # Missing voice: temporary fallback, never erase saved assignment.
            return self.voices[0], False, False
        counts = {v: sum(x == v for x in self.mapping.values()) for v in self.voices}
        minimum = min(counts.values())
        chosen = self.rng.choice([v for v in self.voices if counts[v] == minimum])
        updated = dict(self.mapping, **{key: chosen})
        temp = self.path.with_suffix('.json.tmp')
        try:
            temp.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)
        self.mapping = updated
        return chosen, True, True
