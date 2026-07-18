import { useCallback, useEffect, useRef, useState } from "react";

function getPreferredChineseLocale() {
  const browserLanguage = navigator.language?.toLowerCase() || "";
  return browserLanguage.startsWith("zh-hk") || browserLanguage.startsWith("zh-tw")
    ? "zh-HK"
    : "zh-CN";
}

function findChineseVoice(voices) {
  const preferredLocale = getPreferredChineseLocale().toLowerCase();
  let bestVoice = null;
  let bestScore = -1;

  voices.forEach((voice) => {
    if (!voice.lang?.toLowerCase().startsWith("zh")) return;

    const name = voice.name.toLowerCase();
    let score = 0;

    if (name.includes("google 普通话")) score += 100;
    else if (name.includes("microsoft yahei")) score += 90;
    else if (name.includes("tingting")) score += 80;
    else if (/(neural|premium|enhanced|natural)/i.test(name)) score += 60;

    if (voice.lang.toLowerCase() === preferredLocale) score += 10;
    if (voice.localService) score += 5;

    if (score > bestScore) {
      bestVoice = voice;
      bestScore = score;
    }
  });

  return bestVoice;
}

export function useSpeech() {
  const [voice, setVoice] = useState(null);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const selectedVoiceRef = useRef(null);
  const speechRequestRef = useRef(0);

  useEffect(() => {
    if (!("speechSynthesis" in window)) return undefined;

    const loadVoice = () => {
      // Lock the first suitable system voice for this hook's lifetime. Browsers can
      // emit `voiceschanged` repeatedly as remote voices load, which must not alter
      // the voice mid-session.
      if (selectedVoiceRef.current) return;

      const selectedVoice = findChineseVoice(window.speechSynthesis.getVoices());
      if (!selectedVoice) return;

      selectedVoiceRef.current = selectedVoice;
      setVoice(selectedVoice);
    };

    loadVoice();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoice);

    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", loadVoice);
      speechRequestRef.current += 1;
      window.speechSynthesis.cancel();
    };
  }, []);

  const speak = useCallback(
    (text, { onEnd } = {}) => {
      if (!("speechSynthesis" in window) || !text?.trim()) return;

      const requestId = speechRequestRef.current + 1;
      speechRequestRef.current = requestId;

      // Stop only a previous request. A short delay before the next `speak()` avoids
      // the Chromium/WebKit cancel-and-speak race that can clip a final syllable.
      window.speechSynthesis.cancel();

      setIsSpeaking(true);

      window.setTimeout(() => {
        if (speechRequestRef.current !== requestId) return;

        const utterance = new SpeechSynthesisUtterance();
        const normalizedText = text.trim().normalize("NFKC");
        utterance.text = normalizedText;
        utterance.lang = voice?.lang || getPreferredChineseLocale();
        utterance.voice = voice;
        utterance.volume = 1;
        utterance.rate = 0.67;
        utterance.pitch = 1;
        utterance.onend = () => {
          if (speechRequestRef.current !== requestId) return;
          setIsSpeaking(false);
          onEnd?.();
        };
        utterance.onerror = () => {
          if (speechRequestRef.current !== requestId) return;
          setIsSpeaking(false);
          onEnd?.();
        };

        window.speechSynthesis.speak(utterance);
      }, 80);
    },
    [voice]
  );

  const stop = useCallback(() => {
    if (!("speechSynthesis" in window)) return;

    speechRequestRef.current += 1;
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  return { speak, stop, isSpeaking };
}

export default useSpeech;
