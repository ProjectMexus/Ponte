function getRecognitionConstructor() {
  return globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition || null;
}

function notify(state, onStateChange) {
  onStateChange?.(state);
}

export function createSpeechController({ onTranscript, onStateChange } = {}) {
  const Recognition = getRecognitionConstructor();
  const recognition = Recognition ? new Recognition() : null;
  const supported = Boolean(recognition);

  if (!supported) {
    notify("unsupported", onStateChange);
  }

  if (recognition) {
    recognition.lang = "zh-HK";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => notify("listening", onStateChange);
    recognition.onresult = (event) => {
      const text = Array.from(event.results)
        .map((result) => result[0]?.transcript || "")
        .join("")
        .trim();
      const lastResult = event.results[event.results.length - 1];
      onTranscript?.({ text, isFinal: Boolean(lastResult?.isFinal) });
    };
    recognition.onerror = (event) => {
      notify(event.error === "not-allowed" ? "permission-denied" : "error", onStateChange);
    };
    recognition.onend = () => notify("idle", onStateChange);
  }

  return {
    supported,
    start() {
      if (!recognition) return false;
      try {
        recognition.start();
        return true;
      } catch (error) {
        notify("error", onStateChange);
        return false;
      }
    },
    stop() {
      recognition?.stop();
    },
    speak(text, { onEnd } = {}) {
      const speechSynthesis = globalThis.speechSynthesis;
      const Utterance = globalThis.SpeechSynthesisUtterance;
      if (!text || !speechSynthesis || !Utterance) return false;
      try {
        speechSynthesis.cancel();
        const utterance = new Utterance(text);
        utterance.lang = "zh-HK";
        utterance.rate = 0.92;
        utterance.pitch = 1;
        utterance.onend = () => onEnd?.();
        utterance.onerror = () => onStateChange?.("audio-error");
        const voices = speechSynthesis.getVoices?.() || [];
        utterance.voice = voices.find((voice) => /^zh-HK/i.test(voice.lang))
          || voices.find((voice) => /^zh/i.test(voice.lang))
          || voices[0]
          || null;
        speechSynthesis.resume?.();
        // Speak immediately while this call is still inside the user gesture.
        // Voice enumeration is optional; browsers can select their default voice.
        speechSynthesis.speak(utterance);
        return true;
      } catch (error) {
        return false;
      }
    },
    unlock() {
      globalThis.speechSynthesis?.resume?.();
      const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!AudioContextClass) return false;
      try {
        const context = new AudioContextClass();
        if (context.state === "suspended") context.resume();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        gain.gain.value = 0.0001;
        oscillator.connect(gain).connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.03);
        oscillator.addEventListener("ended", () => context.close?.(), { once: true });
        return true;
      } catch (error) {
        return false;
      }
    },
    stopSpeaking() {
      globalThis.speechSynthesis?.cancel();
    },
  };
}
