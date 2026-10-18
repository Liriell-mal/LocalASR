# LocalASR

LocalASR is a **local-first Windows application for audio and video transcription**, with browser-based review and correction.

It was built as a personal technical project to explore practical, privacy-preserving speech-to-text workflows that can run entirely on a local machine.

The application is designed around a simple principle:

> Media stays local.  
> Transcription stays local.  
> Human correction remains part of the workflow.

LocalASR is an experimental personal project.

## LocalASR interface

![Interface principale de LocalASR](docs/LocalASR1.png)

## Validation and Exports

After reviewing and correcting the transcription, users can validate the final version and export it in PDF, TXT, SRT, or JSON format.

![Validation et exports](docs/localASR2.png)

---

## Key features

- Local transcription with **faster-whisper**
- Whisper **small** multilingual model
- CPU / INT8 inference
- **PyAV** media decoding
- Timestamped browser-based editor
- Direct playback of each transcript segment
- Autosave and project reopening
- Raw transcript preserved separately from edits
- Explicit validation step
- Local exports to **PDF, TXT, SRT and JSON**
- Offline workflow after initial installation and model acquisition

Supported input extensions currently include:

`.wav` · `.mp3` · `.m4a` · `.mp4` · `.mov` · `.mkv`

---

## Architecture

```text
AUDIO / VIDEO
      ↓
PyAV
      ↓
faster-whisper
      ↓
Raw transcript preserved
      ↓
Timestamped browser editor
      ↓
Human correction + autosave
      ↓
Validated transcript
      ↓
PDF / TXT / SRT / JSON

---
