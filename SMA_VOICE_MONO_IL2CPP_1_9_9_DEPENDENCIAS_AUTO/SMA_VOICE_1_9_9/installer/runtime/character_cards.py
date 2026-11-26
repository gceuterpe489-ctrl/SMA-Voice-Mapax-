"""Read SMA character card PNGs without changing the game or executing card data."""
import hashlib, json, struct, wave, zlib
from pathlib import Path
from character_voices import VOICES, canonical_id

MARKER = b'TValle.Character.Data:'
PNG = b'\x89PNG\r\n\x1a\n'
MAX_CARD = 32 * 1024 * 1024
MAX_WAV = 20 * 1024 * 1024


def linked_model(node, sections):
    """SMA model record: both appearance and personality links resolve in this source."""
    fields = node.get('m_data', {})
    values = dict(zip(fields.get('keys', []), fields.get('values', [])))
    for field in ('AparienciaFisica', 'Personalidad'):
        ref = values.get(field)
        if not isinstance(ref, str) or not ref or not any(
                child.get('m_id') == ref for child in sections.get(field, {}).get('m_children', [])):
            return False
    return True


def read_card(path, model_ids=None):
    path = Path(path)
    if path.stat().st_size > MAX_CARD: raise ValueError('PNG grande demais')
    raw = path.read_bytes()
    if not raw.startswith(PNG): raise ValueError('PNG invalido')
    offset = 8
    while offset + 12 <= len(raw):
        n, kind = struct.unpack_from('>I4s', raw, offset)
        end = offset + 12 + n
        if end > len(raw): raise ValueError('PNG truncado')
        if kind == b'IEND':
            if n != 0 or zlib.crc32(kind) != struct.unpack_from('>I',raw,offset+8)[0]: raise ValueError('IEND invalido')
            break
        offset = end
    else: raise ValueError('PNG sem IEND')
    data = raw[end:]
    if not data.startswith(MARKER): raise ValueError('PNG sem dados SMA')
    root = json.loads(data[len(MARKER):].decode('utf-8-sig'))
    if root.get('m_id') != 'root': raise ValueError('Raiz SMA invalida')
    npc = [node for node in root.get('m_children',[]) if node.get('m_id') == 'NPC']
    if len(npc) != 1 or len(npc[0].get('m_children',[])) != 1: raise ValueError('Cartao sem NPC unico')
    node = npc[0]['m_children'][0]
    key = canonical_id(node.get('m_id'))
    if not key: raise ValueError('GUID de NPC invalido')
    fields = node.get('m_data',{})
    values = dict(zip(fields.get('keys',[]), fields.get('values',[])))
    name = ' '.join(str(values.get(k,'')) for k in ('Nombre','Apellido')).strip()
    if model_ids is not None and linked_model(node, {n['m_id']: n for n in root['m_children']}):
        model_ids.add(key)
    return key, name


def wav_reference(path):
    path = Path(path)
    if path.stat().st_size > MAX_WAV: raise ValueError('WAV excede 20 MB')
    with wave.open(str(path),'rb') as w:
        rate = w.getframerate(); duration = w.getnframes()/rate
        if not (3 <= duration <= 30 and 8000 <= rate <= 96000 and w.getnchannels() in (1,2) and w.getsampwidth() in (2,3,4)):
            raise ValueError('WAV PCM: 3 a 30 segundos, mono/estereo, 16/24/32 bits')
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CharacterCards:
    def __init__(self, directory, available, log=print, paths=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.model_ids = set(); self.names = {}; self.overrides = {}; self.references = {}; self.conflicts = set()
        self.available = set(available)
        for path in sorted(self.directory.rglob('*.png') if paths is None else paths):
            try:
                if paths is None and not path.resolve().is_relative_to(self.directory.resolve()): raise ValueError('Caminho fora da pasta')
                key, name = read_card(path, self.model_ids)
                self.names.setdefault(key,name)
                side = path.with_suffix('.voice.json')
                if not side.is_file(): continue
                if side.stat().st_size > 65536 or not side.resolve().is_relative_to(path.parent.resolve()): raise ValueError('Manifesto invalido')
                data = json.loads(side.read_text(encoding='utf-8-sig'))
                if data.get('schema') != 1 or canonical_id(data.get('character_id')) != key: raise ValueError('GUID do manifesto nao coincide com PNG')
                voice = data.get('voice')
                if voice == 'custom':
                    namefile = data.get('reference_wav','')
                    if not isinstance(namefile,str) or Path(namefile).name != namefile or '/' in namefile or '\\' in namefile or not namefile.lower().endswith('.wav'): raise ValueError('Referencia WAV deve ser um arquivo local ao cartao')
                    if data.get('authorized_reference') is not True: raise ValueError('Referencia de voz requer autorizacao explicita')
                    wav = (path.parent/namefile).resolve()
                    if not wav.is_relative_to(path.parent.resolve()): raise ValueError('WAV fora da pasta do cartao')
                    digest = wav_reference(wav)
                    voice = 'custom:' + digest
                    self.references[voice] = wav
                elif not isinstance(voice,str) or voice not in self.available:
                    raise ValueError('Voz interna indisponivel')
                if key in self.overrides and self.overrides[key] != voice:
                    self.conflicts.add(key)
                else: self.overrides[key] = voice
            except Exception as exc:
                if str(exc) != 'PNG sem dados SMA': log(f'Cartao ignorado ({path.name}): {type(exc).__name__}: {exc}')
        for key in self.conflicts:
            self.overrides.pop(key,None); log(f'Cartoes conflitantes para {key}; usando cadastro local.')
        log(f'Cartoes SMA: {len(self.names)} | vozes personalizadas/definidas: {len(self.overrides)}')

    def preferred(self, actor):
        key = canonical_id(actor)
        return self.overrides.get(key)
