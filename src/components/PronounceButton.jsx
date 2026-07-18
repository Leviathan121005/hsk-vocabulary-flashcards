export function PronounceButton({ text, onSpeak, onStop, isSpeaking = false, disabled = false }) {

  function handlePronounce() {
    if (isSpeaking) {
      onStop?.();
      return;
    }

    if (disabled || !text?.trim()) return;

    onSpeak?.(text);
  }

  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        handlePronounce();
      }}
      onKeyDown={(event) => event.stopPropagation()}
      disabled={disabled || !text?.trim()}
      aria-label={isSpeaking ? `Stop pronunciation for ${text}` : `Pronounce ${text}`}
      className={`inline-flex h-11 w-11 items-center justify-center rounded-full border shadow-sm transition focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300 disabled:cursor-not-allowed disabled:opacity-40 ${
        isSpeaking
          ? "border-sky-400 bg-sky-100 text-sky-700 shadow-sky-100"
          : "border-slate-200 bg-white text-slate-600 hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700"
      }`}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={`h-5 w-5 ${isSpeaking ? "animate-pulse" : ""}`}
      >
        <path d="M11 5 6 9H2v6h4l5 4V5Z" />
        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
        <path d="M19 5a10 10 0 0 1 0 14" />
      </svg>
    </button>
  );
}

export default PronounceButton;
