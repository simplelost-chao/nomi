import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./Avatar.module.css";

export type CharacterState = "idle" | "listening" | "thinking" | "speaking" | "happy" | "sad" | "surprised";

interface AvatarProps {
  characterDir?: string; // path to character assets directory
  state: CharacterState;
  onClick: () => void;
}

// Map states to image names (without extension for API compatibility)
const STATE_NAMES: Record<CharacterState, string> = {
  idle: "idle",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
  happy: "happy",
  sad: "sad",
  surprised: "surprised",
};

export function Avatar({ characterDir = "./characters/frieren", state, onClick }: AvatarProps) {
  const [currentImage, setCurrentImage] = useState(STATE_NAMES.idle);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const prevState = useRef(state);

  // Preload all state images
  const isApi = characterDir.startsWith("http");
  useEffect(() => {
    Object.values(STATE_NAMES).forEach((name) => {
      const img = new Image();
      img.src = isApi ? `${characterDir}/${name}` : `${characterDir}/${name}.png`;
    });
  }, [characterDir, isApi]);

  // Switch image on state change with a brief crossfade
  useEffect(() => {
    if (state !== prevState.current) {
      setIsTransitioning(true);
      const timer = setTimeout(() => {
        setCurrentImage(STATE_NAMES[state]);
        setIsTransitioning(false);
        prevState.current = state;
      }, 150); // brief fade duration
      return () => clearTimeout(timer);
    }
  }, [state]);

  const imageSrc = isApi ? `${characterDir}/${currentImage}` : `${characterDir}/${currentImage}.png`;

  return (
    <div
      className={`${styles.avatar} ${styles[state] || styles.idle}`}
      onClick={onClick}
    >
      <img
        className={`${styles.avatarImage} ${isTransitioning ? styles.fading : ""}`}
        src={imageSrc}
        alt="Character"
        draggable={false}
      />
      <div
        className={`${styles.statusDot} ${
          state === "thinking"
            ? styles.dotThinking
            : state === "speaking"
            ? styles.dotSpeaking
            : styles.ready
        }`}
      />
    </div>
  );
}
