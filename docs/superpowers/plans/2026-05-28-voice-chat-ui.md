# Voice Chat UI — Implementation Plan

**Goal:** Add STT endpoint + redesign desktop UI to voice-first (character + mic button, chat hidden by default).

---

### Task 1: Backend — STT endpoint with faster-whisper

**Files:**
- Create: `backend/app/api/stt.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Create STT endpoint**

`POST /api/stt/transcribe` — accepts audio file (webm/wav), returns transcribed text.

- Load whisper model lazily on first request (large-v3)
- Accept multipart file upload
- Return `{"text": "transcribed text", "language": "zh"}`

- [ ] **Step 2: Register router in main.py**
- [ ] **Step 3: Test with curl**
- [ ] **Step 4: Commit**

---

### Task 2: Desktop UI — Voice-first layout

**Files:**
- Rewrite: `desktop/src/renderer/App.tsx`
- Create: `desktop/src/renderer/components/VoiceButton.tsx`
- Modify: `desktop/src/renderer/api.ts`

- [ ] **Step 1: Add `transcribe` API method**

```typescript
transcribe: async (audioBlob: Blob): Promise<{ text: string; language: string }> => {
  const form = new FormData();
  form.append("file", audioBlob, "recording.webm");
  const res = await fetch(`${BACKEND_URL}/api/stt/transcribe`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`STT error: ${res.status}`);
  return res.json();
},
```

- [ ] **Step 2: Create VoiceButton component**

Press-and-hold mic button:
- mousedown/touchstart → start MediaRecorder (webm/opus)
- mouseup/touchend → stop recording → send to /api/stt/transcribe → return text
- Visual feedback: pulsing ring while recording
- Props: `onTranscribed: (text: string) => void`, `disabled: boolean`

- [ ] **Step 3: Redesign App.tsx layout**

Default view (compact):
```
┌─────────────────┐
│                 │
│   Avatar (big)  │
│                 │
│  「floating台词」│
│      🎤         │
└─────────────────┘
```

- Avatar takes full window, centered
- Floating subtitle: bot's last reply, fades after 5s
- Mic button at bottom center
- Small expand button (corner) to toggle chat panel
- When chat panel shown: slide in from right (like current layout)

Key state changes:
- `showChat` defaults to `false` (was `true`)
- New `subtitle` state for floating text
- VoiceButton triggers: record → STT → agentChat → show subtitle → TTS

- [ ] **Step 4: Build and test**
- [ ] **Step 5: Commit**
