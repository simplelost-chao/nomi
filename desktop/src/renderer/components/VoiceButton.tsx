import { useCallback, useRef, useState } from "react";

interface Props {
  onTranscribed: (text: string) => void;
  disabled?: boolean;
}

export function VoiceButton({ onTranscribed, disabled }: Props) {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    if (disabled || processing) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      chunks.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks.current, { type: "audio/webm" });
        if (blob.size < 500) {
          console.warn("[voice] Recording too short, ignoring");
          return;
        }

        setProcessing(true);
        try {
          const form = new FormData();
          form.append("file", blob, "recording.webm");
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 15000);
          const res = await fetch("http://127.0.0.1:8100/api/stt/transcribe", {
            method: "POST",
            body: form,
            signal: controller.signal,
          });
          clearTimeout(timeout);
          if (res.ok) {
            const { text } = await res.json();
            if (text?.trim()) onTranscribed(text.trim());
          } else {
            console.error("[voice] STT error:", res.status);
          }
        } catch (err) {
          console.error("[voice] STT failed:", err);
        } finally {
          setProcessing(false);
        }
      };

      mediaRecorder.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (err) {
      console.error("[voice] Mic access denied:", err);
    }
  }, [disabled, processing, onTranscribed]);

  const stopRecording = useCallback(() => {
    if (mediaRecorder.current && recording) {
      mediaRecorder.current.stop();
      setRecording(false);
    }
  }, [recording]);

  const isActive = recording || processing;

  return (
    <button
      onMouseDown={startRecording}
      onMouseUp={stopRecording}
      onMouseLeave={stopRecording}
      onTouchStart={startRecording}
      onTouchEnd={stopRecording}
      disabled={disabled || processing}
      className={`relative w-14 h-14 rounded-full flex items-center justify-center transition-all select-none
        ${isActive
          ? "bg-red-400 shadow-lg shadow-red-200 scale-110"
          : "bg-white/80 hover:bg-white shadow-md hover:shadow-lg hover:scale-105"
        }
        ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}
      `}
      title="按住说话"
    >
      {/* Pulsing ring when recording */}
      {recording && (
        <span className="absolute inset-0 rounded-full bg-red-400/30 animate-ping" />
      )}

      {processing ? (
        /* Spinner while processing */
        <svg className="w-6 h-6 text-purple-500 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="40 60" />
        </svg>
      ) : (
        /* Mic icon */
        <svg
          width="22" height="22" viewBox="0 0 24 24" fill="none"
          stroke={recording ? "white" : "#9333ea"}
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        >
          <rect x="9" y="1" width="6" height="12" rx="3" />
          <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
      )}
    </button>
  );
}
