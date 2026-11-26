"""Validated shared plain text settings (UTF-8, key=value)."""
from pathlib import Path
from voice_language import code_for

SPEC = {
 'ENABLE_LOG':(True,), 'ENABLE_INSPECTOR':(True,), 'ENABLE_CMA_BARK':(True,), 'ENABLE_CMA_FIXED_BOX':(True,), 'PROTEGER_AUDIO_IL2CPP':(True,), 'PROTEGER_AUDIO_MONO':(True,), 'ENABLE_MONO_BARK_RECOVERY':(True,),
 'DELAY_CAIXA_NORMAL_MS':(150,0,5000),'FALLBACK_CAIXA_NORMAL_MS':(500,0,10000),
 'DELAY_BALAO_FLUTUANTE_MS':(350,0,5000),'FALLBACK_BALAO_FLUTUANTE_MS':(1500,0,10000),
 'INTERVALO_CAPTURA_MS':(150,50,1000),'DEDUP_CAPTURA_MS':(1500,0,10000),
 'BUFFER_INICIAL_MS':(960,100,5000),'BUFFER_CAIXA_NORMAL_MS':(500,100,5000),'MODO_REPRODUCAO':('adaptive','adaptive','stream','stable'),
 'INICIO_CAIXA_POR_SEGMENTO':(True,), 'INICIO_BALAO_POR_SEGMENTO':(True,),
 'QUALIDADE_VOZ':('original','original','consistent','expressive'),'VELOCIDADE_VOZ':(1.0,0.8,1.25),
 'CACHE_AUDIO':(True,), 'CHUNK_XTTS':(20,5,100),'PAUSA_ENTRE_FRASES_MS':(120,0,1000),
 'LATENCIA_AUDIO':('high','high','low'),'DISPOSITIVO_AUDIO':('auto',),'PROCESSAMENTO':('auto','auto','cpu','cuda'),
 'AQUECIMENTO':(True,), 'IDIOMA':('auto',),'IDIOMA_ORIGEM':('auto',),'VOZ_PADRAO':('Sofia Hellen',),
 'PRIORIDADE_CAIXA_FIXA':(True,), 'INTERVALO_FILA_MS':(50,10,1000),'IDADE_MAX_EVENTO_S':(20,5,120),'IDADE_MAX_CAIXA_FIXA_S':(45,5,120),'DEDUP_FILA_MS':(2000,0,10000),
 'TRADUCAO':(True,), 'MODELO_OLLAMA':('auto',),'TIMEOUT_TRADUCAO_S':(25,1,120),
}

def read_settings(path=None):
    result={k:v[0] for k,v in SPEC.items()}
    if path is None: return result
    path=Path(path); seen=set()
    for n,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'): continue
        key,sep,value=line.partition('='); key=key.strip().upper(); value=value.strip()
        if not sep or key not in SPEC or key in seen or not value: raise ValueError(f'{path.name}:{n}: chave invalida, duplicada ou vazia: {key}')
        seen.add(key); spec=SPEC[key]; default=spec[0]
        try:
            if isinstance(default,bool):
                if value.lower() not in ('true','false'): raise ValueError()
                v=value.lower()=='true'
            elif isinstance(default,(int,float)):
                v=type(default)(value)
                if not spec[1]<=v<=spec[2]: raise ValueError()
            elif len(spec)>1:
                v=value.lower()
                if v not in spec[1:]: raise ValueError()
            else: v=value
            if key in ('IDIOMA','IDIOMA_ORIGEM'):
                v='auto' if v.lower()=='auto' else code_for(v)
                if not v: raise ValueError()
            if key=='MODELO_OLLAMA' and v.lower()=='auto': v='auto'
            if key=='DISPOSITIVO_AUDIO' and v.lower()!='auto' and int(v)<0: raise ValueError()
        except (ValueError,OverflowError): raise ValueError(f'{path.name}:{n}: valor invalido para {key}: {value}') from None
        result[key]=v
    return result

def inference_options(quality,speed):
    opts={}
    if quality=='consistent': opts.update(temperature=0.60,top_p=0.80)
    if quality=='expressive': opts.update(temperature=0.85,top_p=0.90)
    if speed!=1.0: opts['speed']=speed
    return opts


def protected_audio_backend(cfg, env):
    """Respect per-engine opt-outs; do not change unknown/manual generic projects."""
    backend = 'IL2CPP' if env.get('SMA_VOICE_IL2CPP') == '1' else env.get('SMA_VOICE_BACKEND', 'unknown')
    key = {'IL2CPP':'PROTEGER_AUDIO_IL2CPP', 'Mono':'PROTEGER_AUDIO_MONO'}.get(backend)
    return backend, bool(key and cfg[key])
