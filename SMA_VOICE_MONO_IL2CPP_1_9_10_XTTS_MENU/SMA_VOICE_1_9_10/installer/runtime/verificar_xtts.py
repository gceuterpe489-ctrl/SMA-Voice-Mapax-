"""Installation smoke test; model download may prompt for its license."""
import argparse, inspect, os
from xtts_loader import load_xtts

def main():
    p=argparse.ArgumentParser(); p.add_argument('--device',choices=['auto','cpu','cuda'],default='auto'); p.add_argument('--model-dir'); p.add_argument('--audio-device',default='auto'); p.add_argument('--imports-only',action='store_true'); a=p.parse_args()
    import torch,numpy,sounddevice
    from TTS.api import TTS
    print('Python/XTTS imports OK; torch:',torch.__version__,'CUDA:',torch.cuda.is_available(),flush=True)
    if a.imports_only: return
    if a.model_dir: os.environ['SMA_XTTS_MODEL_DIR']=a.model_dir
    device=('cuda' if torch.cuda.is_available() else 'cpu') if a.device=='auto' else a.device
    if device=='cuda' and not torch.cuda.is_available(): raise RuntimeError('CUDA indisponivel. Verifique driver e ambiente, ou escolha CPU.')
    model,rate=load_xtts(device)
    sounddevice.check_output_settings(device=None if a.audio_device.lower()=='auto' else int(a.audio_device), channels=1, dtype='float32', samplerate=rate)
    speakers=model.speaker_manager.speakers
    if not speakers: raise RuntimeError('XTTS sem vozes internas')
    if not {'speed','temperature','top_p'}.issubset(inspect.signature(model.inference_stream).parameters): raise RuntimeError('API XTTS incompativel com os ajustes de voz')
    speaker=next(iter(speakers.values()))
    stream=model.inference_stream('Ola, teste de voz.', 'pt',speaker['gpt_cond_latent'].to(device),speaker['speaker_embedding'].to(device),stream_chunk_size=20,enable_text_splitting=False)
    try:
        if not any(chunk.numel() and torch.isfinite(chunk).all().item() for chunk in stream): raise RuntimeError('XTTS nao gerou audio valido')
    finally: stream.close()
    print('XTTS v2 OK |',device,'|',rate,'Hz |',len(speakers),'vozes | sintese validada',flush=True)
if __name__=='__main__': main()
