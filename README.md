# 🎙️ SMA Voice — AI Dialogue Narration

![Version](https://img.shields.io/badge/version-1.9.9-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Unity](https://img.shields.io/badge/Unity-Mono%20%7C%20IL2CPP-black)
![Status](https://img.shields.io/badge/status-Beta-orange)
![AI](https://img.shields.io/badge/AI-Local-green)

**Less reading. More immersion. Your characters, your voices.**

## Overview

SMA Voice is an unofficial AI-powered voice narration mod designed for Some Modeling Agency (SMA) and Corrupted Modeling Agency (CMA).

The project transforms in-game text dialogues into generated speech using local artificial intelligence, providing a more immersive and personalized gameplay experience without requiring paid cloud APIs for the standard local workflow.

Rather than simply reading text aloud, SMA Voice gives characters individual vocal identities that can persist across gameplay sessions.

## Features

- AI-generated character voices using XTTS v2.
- Four initial built-in voices.
- Balanced random voice assignment for new characters.
- Persistent character voice save system.
- Expandable custom voice library.
- Individual character voice customization.
- Automatic recognition of supported character cards and game saves.
- Local dialogue translation with Ollama.
- Fixed and floating dialogue narration.
- Priority-based speech scheduling.
- Automatic installation of missing dependencies.
- Audio caching and optimized speech generation.
- Protection against repetitive audio.
- Scene-aware audio cancellation.
- Customizable voice quality, speed and expressiveness.
- Installation verification and diagnostic tools.
- Documentation in seven languages.

---

## 🎙️ Character Voice System

### Initial Voice Library

SMA Voice starts with four built-in XTTS v2 voices:

| Voice | Type |
|---|---|
| Ana Florence | Built-in |
| Claribel Dervla | Built-in |
| Daisy Studious | Built-in |
| Gracie Wise | Built-in |

When a new character is encountered, the system automatically assigns a voice from the available library.

Voice selection uses a balanced random distribution to reduce excessive repetition of the same voice among different characters.

Users are not limited to these four voices. The library can be expanded or customized at any time.

### Temporary Character Voices

Newly encountered characters receive a voice dynamically during gameplay.

When a character has not yet been verified through a supported save or character card, their voice assignment remains temporary.

The character retains that temporary voice throughout the session whenever their identity can be consistently recognized.

There is no need to manually configure every new character.

### Persistent Voice Save System

When a character becomes part of a supported game save or becomes a registered model whose identity can be verified, SMA Voice can promote their temporary voice assignment to a permanent one.

The system is designed to preserve the voice that was previously assigned to that character.

This means:

- New characters automatically receive a voice.
- Temporary characters maintain their voice during the current session.
- Saved and verified characters retain their assigned voices across sessions.
- Existing characters do not receive a new random voice every time the game starts.
- Adding new voices does not automatically replace existing assignments.

Voice assignments are linked to verified character identifiers (GUIDs), rather than relying exclusively on character names.

The mod reads supported game saves and character cards without modifying the original files.

Persistent voice assignments are stored separately in `character_voices.json`.

If a previously assigned custom voice becomes unavailable, the system can use a temporary fallback without deleting the saved assignment.

---

## 🎧 Custom Voice Library

Users can expand the voice library with their own authorized WAV reference files.

XTTS v2 uses these audio samples to generate entirely new dialogue in the corresponding voice.

### How to Add New Voices

1. Open the following directory:

   `Documents/TValle Games/Some Modeling Agency/SMA Voice/voices/`

2. Place your WAV reference files inside the folder.
3. Make sure `include_wav` is enabled in `voice_library.json`.
4. Valid audio samples will automatically be recognized and added to the available voice pool.

The library is periodically refreshed during gameplay.

### Audio Requirements

| Property | Requirement |
|---|---|
| Format | WAV PCM |
| Duration | 3–30 seconds |
| Channels | Mono or stereo |
| Bit depth | 16, 24 or 32-bit |
| Sample rate | 8–96 kHz |
| Maximum file size | 20 MB |

For better results, use clean recordings without background music, excessive noise or multiple speakers.

Only use voice recordings that you own or have permission to use.

Custom voices are identified by their audio content. Renaming a WAV file does not change its voice identifier, but replacing its contents may create a new identifier.

### Customizing the Voice Pool

The `voice_library.json` file allows users to control which built-in voices participate in random character voice assignment and whether custom WAV files are included.

Example:

```json
{
  "builtin_voices": [
    "Ana Florence",
    "Claribel Dervla",
    "Daisy Studious",
    "Gracie Wise"
  ],
  "include_wav": true
}
```

Users can customize this list according to their preferences.

---

## 👤 Individual Character Personalization

SMA Voice also supports individual voice customization.

Users can associate a specific built-in voice or an authorized custom voice reference with a compatible PNG character card.

Character-specific configurations are defined through `.voice.json` files.

For example:

```text
cards/
├── Character.png
├── Character.voice.json
└── MyVoice.wav
```

Example of a custom voice configuration:

```json
{
  "schema": 1,
  "character_id": "CHARACTER-GUID-HERE",
  "voice": "custom",
  "reference_wav": "MyVoice.wav",
  "authorized_reference": true
}
```

Replace `CHARACTER-GUID-HERE` with the actual character identifier.

To assign a built-in voice instead:

```json
{
  "schema": 1,
  "character_id": "CHARACTER-GUID-HERE",
  "voice": "Ana Florence"
}
```

Valid character-specific voice configurations take priority over automatic voice assignments.

### Voice Management Files

| File or folder | Purpose |
|---|---|
| `voices/` | Custom WAV voice references |
| `cards/` | Character cards and individual voice configurations |
| `voice_library.json` | Voice library settings |
| `character_voices.json` | Persistent character voice assignments |
| `characters.json` | Detected characters and their assigned voices |
| `sources.json` | Additional character and save locations |

Voice references and saved assignments are preserved during normal mod updates.

Back up these files if you wish to preserve your personalized voice library.

---

## Supported Games

| Game | Unity Backend | Mod Loader |
|---|---|---|
| Some Modeling Agency (SMA) | Mono | BepInEx 5 |
| Corrupted Modeling Agency (CMA) | IL2CPP | BepInEx 6 |

Other games and Unity backends are not officially supported.

## Requirements

- Windows 64-bit.
- Python 3.11 for new XTTS environments.
- XTTS v2 environment.
- Microsoft Visual C++ Redistributable.
- Compatible .NET compilation environment.
- Internet connection for initial dependency downloads.
- NVIDIA GPU recommended for faster voice generation.
- Ollama for local AI translation.

CPU processing is supported but may be considerably slower.

## 📥 Installation

Download the latest version from the [Releases section](https://github.com/gceuterpe489-ctrl/SMA-Voice-Mapax-/releases).

1. Extract the entire ZIP file.
2. Run `VERIFICAR_E_INSTALAR_PRE_REQUISITOS.bat` to check Windows prerequisites.
3. Run `INSTALAR_OLLAMA_E_MODELO.bat` if you need Ollama and the default AI translation model.
4. Run `INSTALAR.bat`.
5. Manually select your game:
   - **1 — Some Modeling Agency (Mono)**
   - **2 — Corrupted Modeling Agency (IL2CPP)**
6. Enter your game installation directory.
7. Follow the installation instructions.
8. Launch the game.

Missing game dependencies are downloaded automatically. Compatible existing installations are preserved.

For a fresh CMA installation, launching and closing the game once may be required to generate IL2CPP interoperability assemblies.

## Dependencies

| Dependency | Version |
|---|---|
| BepInEx Mono | 5.4.23.6 |
| BepInEx IL2CPP | 6.0.0-be.793 |
| UnityGameTranslator | 0.16.1 |
| Python | 3.11 |
| Voice synthesis | XTTS v2 |
| Default translation model | qwen3:4b-instruct |

### Official Dependency Sources

- [BepInEx 5](https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.6)
- [BepInEx 6](https://builds.bepinex.dev/projects/bepinex_be)
- [UnityGameTranslator 0.16.1](https://sourceforge.net/projects/unitygametranslator/files/v0.16.1/)
- [Python](https://www.python.org/downloads/)
- [Microsoft .NET](https://dotnet.microsoft.com/download)
- [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
- [XTTS v2](https://huggingface.co/coqui/XTTS-v2)
- [PyTorch](https://pytorch.org/)
- [Ollama](https://ollama.com/download)
- [Qwen3 4B Instruct](https://ollama.com/library/qwen3:4b-instruct)

## AI Translation Models

The default translation model is `qwen3:4b-instruct`, selected for its relatively low resource requirements.

Users are free to experiment with other compatible Ollama models.

To change the model, install the desired model through Ollama and update the UnityGameTranslator and SMA Voice configurations accordingly.

Translation quality, speed and hardware requirements may vary depending on the selected model.

## ⚙️ Configuration

The central mod configuration file is located at:

`BepInEx/plugins/SMAVoiceCapture/CONFIGURACOES.txt`

Available settings include:

- Speech language.
- Voice generation quality and expressiveness.
- Speech speed.
- Translation model.
- Audio buffering.
- Dialogue capture intervals.
- Speech priority.
- Dialogue expiration.
- Audio caching.
- CPU or GPU processing.
- Audio output device.
- Logging and diagnostics.

The mod also includes a detailed configuration manual.

Restart the game after modifying the main configuration file.

## 🛠️ Troubleshooting

Two diagnostic utilities are installed in the game directory:

| Utility | Purpose |
|---|---|
| `SMA_VERIFICAR.bat` | Verifies installation and runtime dependencies |
| `SMA_DIAGNOSTICO.bat` | Collects mod logs and interface diagnostics |

When reporting a bug through [GitHub Issues](https://github.com/gceuterpe489-ctrl/SMA-Voice-Mapax-/issues), please provide:

- Game name and version.
- SMA Voice version.
- Description of the problem and steps to reproduce it.
- Complete BepInEx console log.
- `SMA_VERIFICACAO.txt`.
- `DIAGNOSTICO_SMA_VOICE.txt`.

Remove personal information, credentials and sensitive content before uploading logs.

Do not upload private voice recordings or game saves.

## 🌐 Available Documentation

The installation package includes manuals in seven languages:

- 🇧🇷 Portuguese — Português
- 🇺🇸 English
- 🇪🇸 Spanish — Español
- 🇷🇺 Russian — Русский
- 🇨🇳 Chinese — 简体中文
- 🇯🇵 Japanese — 日本語
- 🇫🇷 French — Français

## Project Status

SMA Voice is currently in active development and is distributed as a beta release.

Some features may behave differently depending on the game version, hardware, translation model and installed dependencies.

Feedback, suggestions and bug reports are welcome.

## Copyright and License

Copyright © 2026 SMA Voice contributors and respective rights holders.

SMA Voice is distributed under the terms provided in the LICENSE file.

Third-party software, AI models and game assets remain subject to their respective licenses.

This project is an unofficial modification and is not affiliated with or endorsed by the original game developers.

---

**SMA Voice — Your characters. Your voices. Your experience.**
