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
    speak(text) {
      const speechSynthesis = globalThis.speechSynthesis;
      const Utterance = globalThis.SpeechSynthesisUtterance;
      if (!text || !speechSynthesis || !Utterance) return false;
      try {
        speechSynthesis.cancel();
        const utterance = new Utterance(text);
        utterance.lang = "zh-HK";
        utterance.rate = 0.92;
        utterance.pitch = 1;
        speechSynthesis.speak(utterance);
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
