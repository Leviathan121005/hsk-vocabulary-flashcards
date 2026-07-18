import { useEffect, useMemo, useState } from "react";
import { PronounceButton } from "./PronounceButton";

/**
 * FlashcardSession
 *
 * Props:
 * - sessionWords: current queue for this session.
 * - totalCount: initial number of cards for progress UI.
 * - onMarkWord: callback(wordId, decision) where decision is "mastered" or "not_mastered".
 */
export function FlashcardSession({
  sessionWords = [],
  currentIndex = 0,
  totalCount,
  onMarkWord,
  onGoPrevious,
  onGoNext,
  onFinishSession,
  currentDecision,
  speak,
  stop,
  isSpeaking = false,
}) {
  const [isFlipped, setIsFlipped] = useState(false);

  const currentWord = sessionWords[currentIndex] ?? null;
  const safeTotalCount = Math.max(totalCount || sessionWords.length, sessionWords.length);

  const progressLabel = useMemo(() => {
    if (safeTotalCount === 0) return "0 / 0";
    if (!currentWord) return `${safeTotalCount} / ${safeTotalCount}`;
    return `${currentIndex + 1} / ${safeTotalCount}`;
  }, [currentIndex, currentWord, safeTotalCount]);

  const canGoPrevious = currentIndex > 0;
  const canGoNext = currentIndex < safeTotalCount - 1;

  function navigateWithFlip(action) {
    if (isSpeaking) {
      stop();
    }

    if (isFlipped) {
      setIsFlipped(false);
      setTimeout(() => {
        action?.();
      }, 600);
      return;
    }

    action?.();
  }

  function handleMarkMastered() {
    if (!currentWord) return;

    if (isSpeaking) {
      stop();
    }

    if (!canGoNext) {
      navigateWithFlip(() =>
        onFinishSession?.({
          wordId: currentWord.id,
          decision: "mastered",
        })
      );
      return;
    }

    onMarkWord?.(currentWord.id, "mastered");
    navigateWithFlip(onGoNext);
  }

  function handleMarkNotMastered() {
    if (!currentWord) return;

    if (isSpeaking) {
      stop();
    }

    if (!canGoNext) {
      navigateWithFlip(() =>
        onFinishSession?.({
          wordId: currentWord.id,
          decision: "not_mastered",
        })
      );
      return;
    }

    onMarkWord?.(currentWord.id, "not_mastered");
    navigateWithFlip(onGoNext);
  }

  useEffect(() => {
    function handleKeyDown(event) {
      if (!currentWord) return;

      if (event.key === " ") {
        event.preventDefault();
        if (isSpeaking) stop();
        setIsFlipped((previous) => !previous);
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        navigateWithFlip(onGoNext);
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        navigateWithFlip(onGoPrevious);
        return;
      }

      if (event.key.toLowerCase() === "m") {
        event.preventDefault();
        handleMarkMastered();
        return;
      }

      if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        handleMarkNotMastered();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentWord, handleMarkMastered, handleMarkNotMastered, isSpeaking, navigateWithFlip, onGoNext, onGoPrevious, stop]);

  if (!currentWord) {
    return (
      <section className="mx-auto w-full max-w-3xl rounded-3xl border border-slate-200 bg-white/90 p-8 text-center shadow-sm">
        <h2 className="text-2xl font-semibold text-slate-900">No Session Words Available</h2>
        <p className="mt-2 text-slate-600">
          Start a session with at least one word to begin reviewing cards.
        </p>
      </section>
    );
  }

  return (
    <section className="session-shell mx-auto w-full max-w-3xl rounded-3xl border border-slate-200 bg-white/90 p-4 shadow-xl sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Session Progress</p>
        <div className="flex items-center gap-2">
          {currentDecision && (
            <p
              className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${
                currentDecision === "mastered" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
              }`}
            >
              {currentDecision === "mastered" ? "Mastered" : "Not Mastered"}
            </p>
          )}
          <p className="session-progress-pill rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
            {progressLabel}
          </p>
        </div>
      </div>

      <div className="mt-2 flex items-center gap-3 sm:gap-4">
        <button
          type="button"
          onClick={() => navigateWithFlip(onGoPrevious)}
          disabled={!canGoPrevious}
          className="session-nav-button inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-slate-300 bg-white text-xl font-bold text-slate-700 shadow-sm transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="Go to previous card"
        >
          &lt;
        </button>

        <div
          role="button"
          tabIndex={0}
          onClick={() => {
            if (isSpeaking) stop();
            setIsFlipped((previous) => !previous);
          }}
          onKeyDown={(event) => {
            if (event.key === " " || event.key === "Enter") {
              event.preventDefault();
              event.stopPropagation();
              if (isSpeaking) stop();
              setIsFlipped((previous) => !previous);
            }
          }}
          className="session-flip-button group w-full rounded-3xl text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          aria-label="Flip flashcard"
        >
          <div className="[perspective:1200px]">
            <div
              className={`relative h-80 w-full rounded-3xl transition-transform duration-500 [transform-style:preserve-3d] sm:h-96 ${
                isFlipped ? "[transform:rotateY(180deg)]" : ""
              }`}
            >
              <div className="session-card-face absolute inset-0 flex flex-col items-center justify-center rounded-3xl border border-slate-200 bg-[linear-gradient(135deg,#ffffff,#f8fafc)] p-6 text-center shadow-md [backface-visibility:hidden]">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#64748b]">Chinese</p>
                <div className="absolute right-4 top-4">
                  <PronounceButton text={currentWord.hanzi} onSpeak={speak} onStop={stop} isSpeaking={isSpeaking} disabled />
                </div>
                <p className="mt-4 text-5xl font-bold text-[#0f172a] sm:text-6xl">{currentWord.hanzi}</p>
                <p className="mt-4 text-sm text-[#64748b]">Click card or press Space to reveal answer</p>
              </div>

              <div className="session-card-face absolute inset-0 flex flex-col items-center justify-center rounded-3xl border border-slate-200 bg-[linear-gradient(135deg,#ffffff,#f8fafc)] p-6 text-center shadow-md [backface-visibility:hidden] [transform:rotateY(180deg)]">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#64748b]">Answer</p>
                <div className="absolute right-4 top-4">
                  <PronounceButton text={currentWord.hanzi} onSpeak={speak} onStop={stop} isSpeaking={isSpeaking} />
                </div>
                <p className="mt-3 text-4xl font-bold text-[#0f172a] sm:text-5xl">{currentWord.hanzi}</p>
                <p className="mt-2 text-xl font-medium text-[#1e293b] sm:text-2xl">{currentWord.pinyin}</p>
                <p className="mt-4 max-w-lg text-base text-[#0f172a] sm:text-lg">{currentWord.english}</p>
              </div>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => navigateWithFlip(onGoNext)}
          className="session-nav-button inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-slate-300 bg-white text-xl font-bold text-slate-700 shadow-sm transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          aria-label="Go to next card"
        >
          &gt;
        </button>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
        <button
          type="button"
          onClick={handleMarkNotMastered}
          className="inline-flex items-center justify-center rounded-2xl bg-rose-600 px-5 py-4 text-base font-semibold text-white shadow-md transition hover:bg-rose-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-rose-300"
        >
          Not Mastered (N)
        </button>
        <button
          type="button"
          onClick={handleMarkMastered}
          className="inline-flex items-center justify-center rounded-2xl bg-emerald-600 px-5 py-4 text-base font-semibold text-white shadow-md transition hover:bg-emerald-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-emerald-300"
        >
          Mastered (M)
        </button>
      </div>

      <button
        type="button"
        onClick={() => {
          if (isSpeaking) stop();
          onFinishSession?.();
        }}
        className="mt-4 inline-flex w-full items-center justify-center rounded-2xl border border-slate-300 bg-white px-5 py-3 text-sm font-semibold uppercase tracking-wide text-slate-700 hover:bg-slate-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-300"
      >
        End Session
      </button>
    </section>
  );
}
