"""Portable example producer, compatible with the original SMA event protocol."""
import argparse, base64, time, uuid
from pathlib import Path

def enqueue(queue, actor, speaker, text, ready=True):
    actor = uuid.UUID(str(actor))
    if not actor.int or not text.strip(): raise ValueError('GUID nao vazio e texto obrigatorios')
    queue = Path(queue); queue.mkdir(parents=True, exist_ok=True)
    ticks = 621355968000000000 + time.time_ns() // 100
    p = queue / f'{ticks:019d}-{uuid.uuid4().hex}.evt'
    tmp = p.with_suffix('.evt.tmp')
    enc = lambda s: base64.b64encode(s.encode('utf-8')).decode('ascii')
    try:
        tmp.write_text('\n'.join((str(actor),enc(speaker),enc(text),'pt-ready' if ready else 'translate','-')), encoding='utf-8')
        tmp.replace(p)
    finally: tmp.unlink(missing_ok=True)
    return p

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--actor',default='a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10'); parser.add_argument('--speaker',default='Personagem teste'); parser.add_argument('--text',required=True); parser.add_argument('--translate',action='store_true')
    a=parser.parse_args(); print(enqueue(a.queue,a.actor,a.speaker,a.text,not a.translate))
