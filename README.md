SMA Voice — AI Dialogue Narration







Overview

SMA Voice is an unofficial AI-powered voice narration mod designed for Some Modeling Agency (SMA) and Corrupted Modeling Agency (CMA).

The project transforms in-game text dialogues into generated speech using local artificial intelligence, providing a more immersive gameplay experience without requiring a paid cloud API for the standard local workflow.

Features

AI-generated character voices using XTTS v2.

Local dialogue translation with Ollama.

Fixed dialogue box narration.

Floating dialogue bubble narration.

Priority-based speech scheduling.

Automatic dependency installation.

Audio caching and optimized speech generation.

Protection against repetitive audio.

Scene-aware audio cancellation.

Character-specific voice management.

Installation verification and diagnostic tools.

Documentation in seven languages.

Supported Games

Game

Unity Backend

Mod Loader

Some Modeling Agency (SMA)

Mono

BepInEx 5

Corrupted Modeling Agency (CMA)

IL2CPP

BepInEx 6

Other games and Unity backends are not officially supported.

Requirements

Windows 64-bit.

Python 3.11.

XTTS v2 environment.

Microsoft Visual C++ Redistributable.

Compatible .NET compilation environment.

Internet connection for initial dependency downloads.

NVIDIA GPU recommended for faster voice generation.

Ollama for local AI translation.

Installation

Download the latest SMA Voice package from the Releases section.

Extract the ZIP file.

Run VERIFICAR_E_INSTALAR_PRE_REQUISITOS.bat to check Windows prerequisites.

Run INSTALAR_OLLAMA_E_MODELO.bat if you need local AI translation.

Run INSTALAR.bat.

Manually select your game:

1 — Some Modeling Agency (Mono)

2 — Corrupted Modeling Agency (IL2CPP)

Enter your game installation directory.

Follow the installation instructions.

Launch the game.

Missing game dependencies are downloaded automatically. Compatible existing installations are preserved.

For a fresh CMA installation, launching and closing the game once may be required to generate IL2CPP interoperability assemblies.

Dependencies

Dependency

Version

BepInEx Mono

5.4.23.6

BepInEx IL2CPP

6.0.0-be.793

UnityGameTranslator

0.16.1

Python

3.11

Voice synthesis

XTTS v2

Default translation model

qwen3:4b-instruct

Official dependency sources

BepInEx 5

BepInEx 6

UnityGameTranslator

Python

Microsoft .NET

Visual C++ Redistributable

XTTS v2

Ollama

Qwen3 4B Instruct

AI Translation Models

The default translation model is qwen3:4b-instruct, selected for its relatively low resource requirements.

Users are free to experiment with other compatible Ollama models. Translation quality, speed and hardware requirements may vary.

The model can be changed through the configuration files.

Configuration

The central mod configuration file is located at:

BepInEx/plugins/SMAVoiceCapture/CONFIGURACOES.txt

Available settings include:

Speech language.

Voice generation quality.

Translation model.

Audio buffering.

Speech priority.

Dialogue expiration.

Audio caching.

Logging and diagnostics.

Please consult the included manual before changing advanced settings.

Troubleshooting

Two diagnostic utilities are installed in the game directory:

Utility

Purpose

SMA_VERIFICAR.bat

Verifies installation and runtime dependencies

SMA_DIAGNOSTICO.bat

Collects mod logs and interface diagnostics

When reporting a bug through GitHub Issues, please provide:

Game name and version.

SMA Voice version.

Description of the problem and steps to reproduce it.

Complete BepInEx console log.

SMA_VERIFICACAO.txt.

DIAGNOSTICO_SMA_VOICE.txt.

Remove personal information, credentials and sensitive content before uploading logs.

Available Documentation

The installation package includes manuals in:

Portuguese — Português

English

Spanish — Español

Russian — Русский

Chinese — 简体中文

Japanese — 日本語

French — Français

Project Status

SMA Voice is currently in active development.

Some features may behave differently depending on the game version, hardware, translation model and installed dependencies.

Copyright and License

Copyright © 2026 SMA Voice contributors and respective rights holders.

SMA Voice is distributed under the terms provided in the LICENSE file.

Third-party software, AI models and game assets remain subject to their respective licenses.

This project is an unofficial modification and is not affiliated with or endorsed by the original game developers.
