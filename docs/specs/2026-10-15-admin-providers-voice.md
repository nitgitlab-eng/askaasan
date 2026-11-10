# Admin-configurable providers + hands-free voice

**Status:** approved 2026-10-15. Vision and the Live Class screen are deferred to the final phase.

## Goal
Admins choose the provider for each capability and paste API keys in a branded console. Learners can talk to the mentor hands-free and hear answers aloud, in English and Tamil, and can interrupt it like a real teacher.

## Capabilities (one config row each)
| Capability | Used for | Providers |
|---|---|---|
| `tutor` | mentor chat, lesson authoring | anthropic, openai, gemini |
| `utility` | grading, suggestions, onboarding | anthropic, openai, gemini |
| `stt` | listening | browser (on-device, no key), sarvam, google, openai |
| `tts` | speaking | browser (on-device, no key), sarvam, google, openai |
| `vision` | stored now, used in the Live Class phase | anthropic, openai, gemini |

Each row stores: provider, model, voices (en/ta), the key encrypted with Fernet (`AASAN_SECRETS_KEY` in `.env`), enabled, and limits (`stt_seconds_per_day`, `tts_chars_per_day`).
Key resolution: admin DB key first, then `.env`. Keys are never returned by the API; only `••••last4` is shown.

## Architecture
- **Server relay.** Browser → `/api/voice/transcribe/` (audio clip) and `/api/voice/speak/` (one sentence → audio). Keys stay server-side.
- **Browser engine.** When the provider is `browser`, the client uses Web Speech (SpeechRecognition / speechSynthesis); no server call.
- **Admin API** (staff only): `GET /api/admin/providers/`, `PATCH /api/admin/providers/<cap>/`, `POST /api/admin/providers/<cap>/test/`.
- **Daily usage counters** per user and metric enforce the limits (HTTP 429 → friendly message).

## Hands-free voice loop (mentor chat)
1. Energy VAD: calibrate the noise floor, fast attack (~60 ms), end after ~900 ms of silence.
2. Utterance → STT → sent as a normal chat message over the existing WebSocket.
3. Streamed reply → sentence splitter → markdown/code-stripped text → TTS queue (starts speaking at the first sentence). Each sentence's language is picked by script detection (Tamil script → ta-IN voice).
4. Barge-in: speech detected while Aasan talks (with a raised threshold and echo cancellation) → stop audio, clear the queue, cancel generation.
5. Kili: `watching` while the learner speaks, `thinking` while waiting, `talking` with the beak driven by output loudness.

## Testing
Backend: encryption round-trip, masking, staff-only permissions, DB→env resolution, voice endpoints via fake adapters, budget 429s.
Frontend: VAD state machine, sentence splitter, speakable-text sanitiser, language detection.
