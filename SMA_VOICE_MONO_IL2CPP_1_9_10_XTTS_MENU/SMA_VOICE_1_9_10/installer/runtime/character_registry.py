"""Read-only game/card/save identity sources and session-scoped voice assignments."""
import gzip, json, os, time, unicodedata, zlib
from pathlib import Path
from character_voices import CharacterVoices, VOICES, canonical_id, valid_voice_id
from character_cards import CharacterCards, linked_model
from voice_library import VoiceLibrary

MAX_SAVE = 96 * 1024 * 1024
PLAYER_ID = '00000001-0000-0000-0000-000000000000'

def fields(node):
    d = node.get('m_data', {})
    return dict(zip(d.get('keys', []), d.get('values', [])))

def read_save(path, model_ids=None):
    with gzip.open(path, 'rb') as f:
        raw = f.read(MAX_SAVE + 1)
    if len(raw) > MAX_SAVE: raise ValueError('Save excede limite de descompressao')
    root = json.loads(raw.decode('utf-8-sig'))
    if root.get('m_id') != 'root': raise ValueError('Raiz SMA invalida')
    sections = {n['m_id']:n for n in root['m_children']}
    result = {}
    for node in sections['NPC']['m_children']:
        key = canonical_id(node.get('m_id'))
        if not key or key == PLAYER_ID: continue
        v = fields(node)
        name = ' '.join(str(v.get(k,'') or '') for k in ('Nombre','Apellido')).strip()
        if name:
            result[key] = name
            if model_ids is not None and linked_model(node, sections): model_ids.add(key)
    return result

def normalize(name):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', name or '').casefold() if not unicodedata.combining(c)).split())

def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')
        tmp.replace(path)
    finally: tmp.unlink(missing_ok=True)

def signature(path):
    s = path.stat(); return (s.st_size, s.st_mtime_ns)

def discover(roots):
    """Bounded search only inside game-specific or explicitly selected directories."""
    saves, cards = set(), set()
    budget = 12000
    for root in roots:
        root = Path(root)
        if root.is_file():
            if root.suffix.lower()=='.sav': saves.add(root.resolve())
            elif root.suffix.lower()=='.png': cards.add(root.resolve())
            continue
        if not root.is_dir(): continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            current = Path(directory)
            if len(current.relative_to(root).parts)>=6: dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith('.') and not d.lower().endswith('_data') and d.lower() not in {'bepinex','cache','voice_cache_v12','logs','backups','venv','managed','streamingassets'} and not (current/d).is_symlink()]
            for name in files:
                budget -= 1
                if budget < 0: return saves,cards
                p=current/name
                if p.is_symlink(): continue
                if p.suffix.lower()=='.sav': saves.add(p.resolve())
                elif p.suffix.lower()=='.png': cards.add(p.resolve())
    return saves,cards

class Registry:
    def __init__(self, base, queue, available, log=print, rng=None, game_docs=None):
        self.base=Path(base); self.queue=Path(queue); self.log=log
        self.game_docs=Path(game_docs) if game_docs is not None else None
        self.local=CharacterVoices(self.base/'character_voices.json',available,rng)
        self.available=set(available); self.voices=self.local.voices; self.mapping=self.local.mapping
        self.library=VoiceLibrary(self.base,self.available,self.log)
        self.temporary={}; self.aliases={}; self.records={}; self.name_index={}; self.last_scan=-1e9
        self.save_cache={}; self.card_signature=None; self.cards=None; self.last_summary=None
        self.document=self.base/'characters.json'; self.last_document=None; self.last_subtitle_names=None
        self.refresh(force=True)

    def roots(self):
        roots=[self.base/'cards']
        if self.game_docs is not None: roots += [self.game_docs/'Characters', self.game_docs/'Save']
        marker=self.queue/'identity-sources.txt'
        if marker.is_file():
            try: roots += [Path(x) for x in marker.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
            except OSError: pass
        config=self.base/'sources.json'
        if config.is_file():
            try:
                data=json.loads(config.read_text(encoding='utf-8-sig'))
                roots += [Path(x) for x in data.get('paths',[]) if isinstance(x,str) and x.strip()]
            except (ValueError,OSError,TypeError,AttributeError) as exc: self.log('SMA fontes: configuracao invalida: '+str(exc))
        if os.environ.get('SMA_VOICE_GENERIC') != '1': roots.append(self.queue.parent.parent)
        return list(dict.fromkeys(roots))

    def refresh(self, force=False):
        now=time.monotonic()
        if not force and now-self.last_scan<5: return
        self.last_scan=now
        self.library.refresh(); self.voices=self.library.voices
        saves, pngs=discover(self.roots())
        # Prefer primary files; backups are not independent current character rosters.
        primary={p for p in saves if not p.stem.lower().endswith('.backup')}
        selected=primary | {p for p in saves-primary if not any(q.parent==p.parent and q.stem.lower()==p.stem.lower()[:-7] for q in primary)}
        data={}
        for p in sorted(selected):
            try:
                sig=signature(p); old=self.save_cache.get(p)
                if old is None or old[0]!=sig:
                    model_ids=set(); records=read_save(p,model_ids)
                    self.save_cache[p]=(sig,records,model_ids)
            except (OSError,ValueError,KeyError,TypeError,AttributeError,EOFError,zlib.error) as exc:
                self.log('Save ainda indisponivel: '+p.name+' | '+str(exc))
            if p in self.save_cache:
                source='backup' if p.stem.lower().endswith('.backup') else 'save'
                for key,name in self.save_cache[p][1].items():
                    row=data.setdefault(key,{'name':name,'sources':set(),'model':False}); row['sources'].add(source)
                    row['model'] |= key in self.save_cache[p][2]
        self.save_cache={k:v for k,v in self.save_cache.items() if k in selected}
        # Track sidecars and WAVs, so imports can be refreshed during the session.
        card_sig=[]
        for p in sorted(pngs):
            try:
                card_sig.append((str(p),signature(p)))
                side=p.with_suffix('.voice.json')
                if side.is_file():
                    card_sig.append((str(side),signature(side)))
                    for wav in sorted(p.parent.glob('*.wav')): card_sig.append((str(wav),signature(wav)))
            except OSError: continue
        if self.cards is None or card_sig!=self.card_signature:
            self.cards=CharacterCards(self.base/'cards',self.available,self.log,paths=pngs)
            self.card_signature=card_sig
            self.card_references=dict(self.cards.references)
        self.cards.references={**self.card_references,**self.library.references}
        for key,name in self.cards.names.items():
            row=data.setdefault(key,{'name':name,'sources':set(),'model':False}); row['sources'].add('card')
            row['model'] |= key in self.cards.model_ids
        self.records=data
        self.name_index={}
        for key,row in data.items():
            n=normalize(row['name'])
            if n: self.name_index.setdefault(n,set()).add(key)
        # A runtime GUID becomes permanent only when independently found in a save or card.
        for key in list(self.temporary):
            if key in data:
                self.persist(key,self.temporary.pop(key)); self.log('Voz temporaria promovida: '+key)
        self.write_document()
        self.write_subtitle_names()
        summary=(len(selected),len(self.cards.names),len(data))
        if summary!=self.last_summary:
            self.log(f'SMA fontes: saves={summary[0]} | cartoes={summary[1]} | GUIDs conhecidos={summary[2]}'); self.last_summary=summary

    def write_subtitle_names(self):
        # Names are an authorization fallback only; the event still goes through the normal
        # provisional identity resolver. Never export player, unknown records or ambiguous names.
        names=sorted({self.records[next(iter(ids))]['name'] for ids in self.name_index.values()
                      if len(ids)==1 and self.records[next(iter(ids))]['model']
                      and next(iter(ids))!=PLAYER_ID},key=normalize)
        content='\n'.join(n for n in names if '\n' not in n and '\r' not in n)+'\n'
        path=self.queue/'subtitle-model-names.txt'; tmp=path.with_suffix('.tmp')
        if content==self.last_subtitle_names and path.is_file(): return
        try:
            tmp.write_text(content,encoding='utf-8'); tmp.replace(path)
        except OSError as exc:
            self.log('SMA subtitle registry unavailable: '+str(exc)); return
        finally:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass
        self.last_subtitle_names=content
        self.log(f'SMA subtitle registry: {len(names)} model names available')

    def write_document(self):
        doc={k:{'name':v['name'],'sources':sorted(v['sources']),'voice':self.cards.preferred(k) or self.mapping.get(k)} for k,v in self.records.items()}
        if doc!=self.last_document:
            atomic_json(self.document,doc); self.last_document=doc

    def persist(self,key,voice):
        if not valid_voice_id(voice) or key not in self.records or key in self.mapping: return
        updated={**self.mapping,key:voice}
        atomic_json(self.local.path,updated); self.mapping.clear(); self.mapping.update(updated)

    def draw(self):
        counts={v:0 for v in self.voices}
        for v in list(self.mapping.values())+list(self.temporary.values()):
            if v in counts: counts[v]+=1
        minimum=min(counts.values())
        return self.local.rng.choice([v for v in self.voices if counts[v]==minimum])

    def resolve(self, actor, name='', alias=''):
        self.refresh()
        key=canonical_id(actor)
        if key==PLAYER_ID: return self.voices[0],'fallback',key
        # Never override a live GUID with an identically named saved character.
        if not key:
            existing=alias or (actor if actor.startswith('live:') else '')
            if existing and existing in self.temporary:
                v=self.temporary[existing]
                return (v if v in self.available or v in self.cards.references else self.voices[0]),'temporaria',existing
            matches=self.name_index.get(normalize(name or (actor if not actor.startswith(('/','live:')) else '')),set())
            if len(matches)==1:
                candidate=next(iter(matches))
                # Existing source voice is a provisional fallback, not proof of identity.
                preferred=self.cards.preferred(candidate) or self.mapping.get(candidate)
                if preferred in self.available or preferred in self.cards.references:
                    if existing: self.temporary[existing]=preferred
                    return preferred,'nome unico (provisorio)',candidate
                # The source GUID is valid but the live name match is not identity proof.
                # Allocate a voice to the saved record, not to an inferred runtime GUID.
                chosen=self.draw(); self.persist(candidate,chosen); self.write_document()
                if existing: self.temporary[existing]=chosen
                return chosen,'nome unico (provisorio)',candidate
            token=alias or (actor if actor.startswith('live:') else '')
            if not token and name: token='name:'+normalize(name)
            if not token and actor and not actor.startswith('/'): token='name:'+normalize(actor)
            if not token: return self.voices[0],'fallback sem identidade',None
            if token not in self.temporary: self.temporary[token]=self.draw()
            v=self.temporary[token]
            return (v if v in self.available or v in self.cards.references else self.voices[0]),'temporaria',token
        if alias:
            old=self.aliases.get(alias)
            if old is None or old==key:
                self.aliases[alias]=key
                if alias in self.temporary and key not in self.temporary and key not in self.mapping:
                    self.temporary[key]=self.temporary.pop(alias)
        preferred=self.cards.preferred(key)
        if preferred: return preferred,'cartao',key
        if key in self.mapping:
            v=self.mapping[key]
            return (v if v in self.available or v in self.cards.references else self.voices[0]),'cadastro existente',key
        v=self.temporary.get(key)
        if v is None: v=self.draw(); self.temporary[key]=v
        if key in self.records:
            self.persist(key,v); self.temporary.pop(key,None); self.write_document()
            return (v if v in self.available or v in self.cards.references else self.voices[0]),'permanente ('+'+'.join(sorted(self.records[key]['sources']))+')',key
        return (v if v in self.available or v in self.cards.references else self.voices[0]),'temporaria GUID',key
