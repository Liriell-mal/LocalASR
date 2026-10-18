# LocalASR

LocalASR is a **local-first Windows application for audio and video transcription**, with browser-based review and correction.

It was built as a personal technical project to explore practical, privacy-preserving speech-to-text workflows that can run entirely on a local machine.

The application is designed around a simple principle:

> Media stays local.  
> Transcription stays local.  
> Human correction remains part of the workflow.

LocalASR is an experimental personal project.

---

## Features

### Local transcription

LocalASR uses:

- **faster-whisper**
- Whisper **small** multilingual model
- CPU inference
- INT8 compute
- **PyAV** for media decoding

PyAV uses its bundled FFmpeg libraries, so the current architecture does **not require an external `ffmpeg.exe` process**.

Available transcription profiles include:

- French
- English
- automatic language detection

The application uses `task=transcribe` and does not automatically translate speech.

---

## Human-in-the-loop correction

The local web interface provides a timestamped segment editor designed for rapid transcript review.

Each segment includes:

- start and end timestamps
- editable text
- direct playback of the corresponding audio section

The interface also supports:

- segment-to-segment navigation
- playback controls
- short backward / forward jumps
- playback speed control
- search
- pagination for long transcripts

The goal is not to eliminate human review, but to make correction fast and practical.

---

## Transcript integrity

LocalASR keeps the original machine transcript separate from the edited version.

The raw transcript is preserved and is not overwritten by manual corrections.

User edits are automatically saved.

The workflow distinguishes between:

- raw transcript
- editable working transcript
- validated version
- exported files

This makes it possible to retain the original ASR output while producing a corrected human-reviewed version.

---

## Validation and exports

After review, a transcript can be explicitly validated and exported locally.

Supported outputs include:

- PDF
- TXT
- SRT
- JSON

PDF generation is performed locally with **ReportLab**.

The application also includes a test mode that can limit processing to the first five minutes of a media file and clearly marks generated PDFs as test output.

---

## Offline operation

LocalASR was designed to continue operating after the initial installation and model acquisition without relying on a transcription API or cloud service.

The normal workflow was empirically tested on the development machine with:

- Wi-Fi disabled
- Ethernet disconnected

The following workflow completed successfully:

```text
Launch LocalASR
        ↓
Import local media
        ↓
Decode locally
        ↓
Transcribe locally
        ↓
Review timestamped segments
        ↓
Edit and autosave
        ↓
Reopen the project
        ↓
Validate
        ↓
Export PDF / TXT / SRT / JSON
