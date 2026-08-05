export const VOICE_CAPTURE_DEFAULTS = Object.freeze({
  silenceMs: 1350,
  onsetMs: 250,
  minDurationMs: 400,
  maxDurationMs: 20_000,
  vadThreshold: 0.018,
});

function chooseMimeType(MediaRecorderClass) {
  if (!MediaRecorderClass?.isTypeSupported) return "";
  return ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/ogg"]
    .find((type) => MediaRecorderClass.isTypeSupported(type)) || "";
}

export function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Unable to read recorded audio."));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(blob);
  });
}

/**
 * Captures one spoken turn. VAD intentionally uses the browser analyser rather
 * than a service so the recording is private until the caller submits it.
 */
export function createVoiceCapture(options = {}) {
  const settings = { ...VOICE_CAPTURE_DEFAULTS, ...options };
  const mediaDevices = options.mediaDevices || globalThis.navigator?.mediaDevices;
  const MediaRecorderClass = options.MediaRecorderClass || globalThis.MediaRecorder;
  const AudioContextClass = options.AudioContextClass || globalThis.AudioContext || globalThis.webkitAudioContext;
  const raf = options.requestAnimationFrame || globalThis.requestAnimationFrame || ((callback) => setTimeout(callback, 16));
  const caf = options.cancelAnimationFrame || globalThis.cancelAnimationFrame || clearTimeout;
  const now = options.now || (() => performance.now());
  let stream = null;
  let recorder = null;
  let audioContext = null;
  let analyser = null;
  let animationFrame = null;
  let maximumTimer = null;
  let startedAt = 0;
  let speechStartedAt = null;
  let silentSince = null;
  let isRecording = false;
  let onStateChange = null;
  let onLevel = null;
  let onComplete = null;
  let onFailure = null;
  let chunks = [];
  let stopReason = "complete";
  let discardCapture = false;

  function emitState(state, detail = {}) {
    onStateChange?.(state, detail);
  }

  function cleanup() {
    if (animationFrame !== null) caf(animationFrame);
    if (maximumTimer !== null) clearTimeout(maximumTimer);
    animationFrame = null;
    maximumTimer = null;
    analyser?.disconnect();
    audioContext?.close?.().catch?.(() => {});
    stream?.getTracks?.().forEach((track) => track.stop());
    analyser = null;
    audioContext = null;
    stream = null;
    recorder = null;
    isRecording = false;
  }

  function amplitude() {
    if (!analyser) return 0;
    const samples = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(samples);
    const sum = samples.reduce((total, value) => {
      const centered = (value - 128) / 128;
      return total + centered * centered;
    }, 0);
    return Math.sqrt(sum / samples.length);
  }

  function monitor() {
    if (!isRecording) return;
    const level = amplitude();
    const stamp = now();
    onLevel?.(Math.min(1, level / Math.max(settings.vadThreshold * 3, 0.001)));
    if (level >= settings.vadThreshold) {
      if (speechStartedAt === null) speechStartedAt = stamp;
      silentSince = null;
      if (stamp - speechStartedAt >= settings.onsetMs) emitState("speaking");
    } else if (speechStartedAt !== null && stamp - speechStartedAt >= settings.onsetMs) {
      if (silentSince === null) silentSince = stamp;
      if (stamp - silentSince >= settings.silenceMs) {
        stop("silence");
        return;
      }
    }
    animationFrame = raf(monitor);
  }

  function finish(reason) {
    if (discardCapture) {
      cleanup();
      return;
    }
    const durationMs = Math.max(0, Math.round(now() - startedAt));
    const mimeType = recorder?.mimeType || chooseMimeType(MediaRecorderClass) || "audio/webm";
    const blob = new Blob(chunks, { type: mimeType });
    cleanup();
    if (durationMs < settings.minDurationMs || blob.size === 0) {
      emitState("ready", { reason: "too-short", durationMs });
      return;
    }
    blobToDataUrl(blob)
      .then((dataUrl) => {
        emitState("captured", { reason, durationMs });
        onComplete?.({ blob, dataUrl, mimeType, durationMs, reason });
      })
      .catch((error) => onFailure?.(error));
  }

  function stop(reason = "manual") {
    if (!isRecording || !recorder) return false;
    stopReason = reason;
    emitState("stopping", { reason });
    if (recorder.state !== "inactive") recorder.stop();
    return true;
  }

  return {
    supported: Boolean(mediaDevices?.getUserMedia && MediaRecorderClass && AudioContextClass),
    async start(handlers = {}) {
      if (isRecording) return true;
      onStateChange = handlers.onStateChange;
      onLevel = handlers.onLevel;
      onComplete = handlers.onComplete;
      onFailure = handlers.onFailure;
      if (!this.supported) {
        const error = new Error("Audio recording is not supported in this browser.");
        emitState("unsupported");
        onFailure?.(error);
        return false;
      }
      try {
        emitState("requesting-permission");
        stream = await mediaDevices.getUserMedia({ audio: true });
        audioContext = new AudioContextClass();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 1024;
        source.connect(analyser);
        const mimeType = chooseMimeType(MediaRecorderClass);
        recorder = mimeType ? new MediaRecorderClass(stream, { mimeType }) : new MediaRecorderClass(stream);
        chunks = [];
        discardCapture = false;
        stopReason = "complete";
        recorder.ondataavailable = (event) => {
          if (event.data?.size) chunks.push(event.data);
        };
        recorder.onerror = (event) => onFailure?.(event.error || new Error("Audio recording failed."));
        recorder.onstop = () => finish(stopReason);
        startedAt = now();
        isRecording = true;
        recorder.start();
        maximumTimer = setTimeout(() => stop("maximum-duration"), settings.maxDurationMs);
        emitState("listening");
        monitor();
        return true;
      } catch (error) {
        cleanup();
        emitState(error?.name === "NotAllowedError" ? "permission-denied" : "error");
        onFailure?.(error);
        return false;
      }
    },
    stop,
    cancel() {
      if (!isRecording) return;
      discardCapture = true;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      else cleanup();
      emitState("ready", { reason: "cancelled" });
    },
  };
}
