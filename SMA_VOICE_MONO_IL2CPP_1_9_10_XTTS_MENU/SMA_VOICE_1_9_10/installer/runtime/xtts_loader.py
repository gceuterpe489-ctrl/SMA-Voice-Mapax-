"""Load the standard XTTS v2 or a trusted local checkpoint directory."""
import os
from pathlib import Path

def load_xtts(device):
    local=os.environ.get('SMA_XTTS_MODEL_DIR')
    if local:
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts
        path=Path(local)
        for name in ('config.json','model.pth','vocab.json','speakers_xtts.pth'):
            if not (path/name).is_file(): raise FileNotFoundError(path/name)
        config=XttsConfig(); config.load_json(str(path/'config.json'))
        model=Xtts.init_from_config(config)
        model.load_checkpoint(config,checkpoint_dir=str(path),eval=True,use_deepspeed=False)
        return model.to(device),int(config.audio.output_sample_rate)
    from TTS.api import TTS
    api=TTS('tts_models/multilingual/multi-dataset/xtts_v2').to(device)
    return api.synthesizer.tts_model,int(api.synthesizer.output_sample_rate)
