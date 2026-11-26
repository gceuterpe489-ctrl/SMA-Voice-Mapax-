"""Read the UnityGameTranslator language once per game session (no writes)."""
import ctypes, json, locale, os, re, unicodedata
from pathlib import Path
from urllib.parse import urlparse

LANGUAGES = {
    'en': ('English','Plugin loaded.'), 'es': ('Spanish','Plugin cargado.'),
    'fr': ('French','Module chargé.'), 'de': ('German','Plugin geladen.'),
    'it': ('Italian','Plugin caricato.'), 'pt': ('Brazilian Portuguese','Plugin carregado.'),
    'pl': ('Polish','Wtyczka załadowana.'), 'tr': ('Turkish','Eklenti yüklendi.'),
    'ru': ('Russian','Плагин загружен.'), 'nl': ('Dutch','Plugin geladen.'),
    'cs': ('Czech','Plugin načten.'), 'ar': ('Arabic','تم تحميل الإضافة.'),
    'zh-cn': ('Mandarin Chinese (Simplified)','插件已加载。'), 'ja': ('Japanese','プラグインを読み込みました。'),
    'hu': ('Hungarian','A bővítmény betöltve.'), 'ko': ('Korean','플러그인이 로드되었습니다.'),
    'hi': ('Hindi','प्लगइन लोड हो गया।'),
}

def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value).casefold()) if not unicodedata.combining(c)).strip().replace('_','-')

ALIASES = {normalize(label): code for code,(label,_) in LANGUAGES.items()}
ALIASES.update({
 'portuguese':'pt','portugues':'pt','portuguese (brazil)':'pt','portuguese (portugal)':'pt','portuguese (brazilian)':'pt','portuguese (brasil)':'pt','portuguese (pt-br)':'pt','portuguese brazil':'pt','brazilian portuguese':'pt','portuguese (european)':'pt','pt-br':'pt','pt-pt':'pt',
 'chinese':'zh-cn','chinese (simplified)':'zh-cn','simplified chinese':'zh-cn','chinese simplified':'zh-cn','mandarin':'zh-cn','zh':'zh-cn','zh-hans':'zh-cn','chinese (traditional)':'zh-cn','traditional chinese':'zh-cn','zh-tw':'zh-cn','zh-hant':'zh-cn',
 'espanol':'es','francais':'fr','english (us)':'en','english (uk)':'en','russian (russia)':'ru','japanese (japan)':'ja',
})

def code_for(value):
    v=normalize(value)
    if v in LANGUAGES: return v
    if v in ALIASES: return ALIASES[v]
    base=v.split('-',1)[0]
    if re.fullmatch(r'[a-z]{2,3}(?:-[a-z0-9]+)+',v):
        return base if base in LANGUAGES else ('zh-cn' if base=='zh' else None)
    return None

def system_language():
    if os.name=='nt':
        try:
            code=locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            if code: return code
        except (AttributeError,OSError): pass
    return locale.getlocale()[0] or 'en'

def find_config(queue):
    plugins=Path(queue).parent/'plugins'
    canonical=plugins/'UnityGameTranslator'/'config.json'
    if canonical.is_file(): return canonical
    # Also support installing the DLL directly in plugins or a differently named subfolder.
    dlls=sorted(plugins.rglob('UnityGameTranslator.dll')) if plugins.is_dir() else []
    for dll in dlls:
        config=dll.with_name('config.json')
        if config.is_file(): return config
    return None

def read_config(queue):
    config=find_config(queue)
    if config is None: return {},None
    data=json.loads(config.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict): raise ValueError('UnityGameTranslator config invalid')
    return data,config

def choose_language(data, override=None, system=None):
    selected=override or data.get('target_language') or 'pt'
    if normalize(selected)=='auto': selected=system or system_language()
    code=code_for(selected)
    if not code: raise ValueError('Idioma sem suporte XTTS: '+str(selected))
    return code

def resolve_session_language(data, override=None, *, sma=False, system=None):
    """SMA follows the translator's actual configured target; generic mode keeps overrides."""
    selected = data.get('target_language') if sma else None
    if selected:
        return choose_language(data, system=system)
    return choose_language(data, override, system)


def local_model(data):
    # Only borrow model names from the existing local Ollama endpoint. Never read or forward API keys.
    model=data.get('ai_model')
    url=data.get('ai_url') or 'http://127.0.0.1:11434'
    try: parsed=urlparse(url)
    except (TypeError,ValueError): return None
    try:
        if parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1') and parsed.port==11434 and isinstance(model,str) and model.strip(): return model.strip()
    except ValueError: pass
    return None

def translation_needed(ready, no_translate, target, source):
    if ready or no_translate: return False
    # The base game dialogue is normally English. If explicitly configured otherwise, translate.
    if target=='en' and (not source or normalize(source)=='auto'): return False
    return code_for(source)!=target

def audio_cache_key(text, model, speaker, no_translate, ready, chunk_size, language, source):
    import hashlib
    # Preserve existing Portuguese cache only for the old Portuguese processing route.
    payload=['v12-clean',text,model,speaker,no_translate,ready,chunk_size]
    if language!='pt' or (not ready and not no_translate and code_for(source)=='pt'):
        payload+=['language-v18',language,code_for(source) or 'auto']
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()
