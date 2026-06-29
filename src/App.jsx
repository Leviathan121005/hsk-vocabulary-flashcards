import { useEffect, useMemo, useRef, useState } from "react";
import { FlashcardSession } from "./components/FlashcardSession";
import { useLocalStorage } from "./hooks/useLocalStorage";
import { countByMastery, getReviewPoolWords, markWordMastered, markWordNotMastered, pickSessionWords } from "./logic/sessionLogic";
import { loadWordsFromCsv } from "./logic/csvWordLoader";

const BUILTIN_DATASETS = [
  {
    value: "hsk1",
    label: "HSK 1 Vocabulary",
    csvFile: "hsk-1-vocabulary.csv",
  },
  {
    value: "hsk2",
    label: "HSK 2 Vocabulary",
    csvFile: "hsk-2-vocabulary.csv",
  },
  {
    value: "hsk3",
    label: "HSK 3 Vocabulary",
    csvFile: "hsk-3-vocabulary.csv",
  },
  {
    value: "hsk4",
    label: "HSK 4 Vocabulary",
    csvFile: "hsk-4-vocabulary.csv",
  },
  {
    value: "hsk5",
    label: "HSK 5 Vocabulary",
    csvFile: "hsk-5-vocabulary.csv",
    expectedCount: 1600,
  },
];

const PROGRESS_EXPORT_KIND = "flashcards-progress";
const PROGRESS_EXPORT_VERSION = 1;
const UI_THEMES = [
  { value: "classic", label: "Classic" },
  { value: "paper", label: "Paper" },
  { value: "dark", label: "Dark" },
];

function getThemeTokens(theme) {
  if (theme === "paper") {
    return {
      appBackground: "bg-stone-100 text-stone-900",
      headerCard: "bg-stone-50 border-stone-300 shadow-sm",
      surfaceCard: "bg-stone-50 border-stone-300 shadow-sm",
      mutedCard: "bg-stone-100 border-stone-300",
      noticeCard: "bg-amber-50 border-amber-200 text-amber-900",
      primaryButton: "bg-stone-900 hover:bg-stone-800 text-white focus-visible:ring-stone-300",
      secondaryButton: "border-stone-400 bg-stone-50 text-stone-900 hover:bg-stone-100 focus-visible:ring-stone-300",
      themeActive: "border-stone-700 bg-stone-200 text-stone-900",
      themeInactive: "border-stone-300 bg-white text-stone-700 hover:bg-stone-100",
      headingTag: "text-stone-700",
      tableHead: "bg-stone-200 text-stone-700",
      dropdownButton: "border-stone-400 bg-stone-50 text-stone-900 hover:bg-stone-100 focus-visible:ring-stone-300",
      dropdownPanel: "border-stone-300 bg-stone-50",
      dropdownItem: "hover:bg-stone-100 text-stone-900",
      dropdownItemActive: "bg-stone-200 text-stone-900",
    };
  }

  if (theme === "dark") {
    return {
      appBackground: "bg-slate-950 text-slate-100",
      headerCard: "bg-slate-900 border-slate-700 shadow-md",
      surfaceCard: "bg-slate-900 border-slate-700 shadow-md",
      mutedCard: "bg-slate-800 border-slate-700",
      noticeCard: "bg-slate-800 border-sky-800 text-sky-100",
      primaryButton: "bg-blue-600 hover:bg-blue-500 text-white focus-visible:ring-blue-400",
      secondaryButton: "border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 focus-visible:ring-slate-500",
      themeActive: "border-sky-500 bg-sky-900 text-sky-100",
      themeInactive: "border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700",
      headingTag: "text-sky-300",
      tableHead: "bg-slate-800 text-slate-200",
      dropdownButton: "border-slate-600 bg-slate-800 text-slate-100 hover:bg-slate-700 focus-visible:ring-slate-500",
      dropdownPanel: "border-slate-600 bg-slate-800",
      dropdownItem: "hover:bg-slate-700 text-slate-100",
      dropdownItemActive: "bg-sky-900 text-sky-100",
    };
  }

  return {
    appBackground: "bg-transparent text-slate-900",
    headerCard: "bg-white/80 border-slate-200 shadow-lg",
    surfaceCard: "bg-white border-slate-200 shadow-xl",
    mutedCard: "bg-slate-50 border-slate-200",
    noticeCard: "bg-sky-50 border-sky-100 text-sky-900",
    primaryButton: "bg-sky-600 hover:bg-sky-700 text-white focus-visible:ring-sky-300",
    secondaryButton: "border-slate-300 bg-white text-slate-800 hover:bg-slate-50 focus-visible:ring-slate-300",
    themeActive: "border-sky-300 bg-sky-100 text-sky-900",
    themeInactive: "border-slate-300 bg-white text-slate-700 hover:bg-slate-100",
    headingTag: "text-sky-700",
    tableHead: "bg-slate-100 text-slate-700",
    dropdownButton: "border-slate-300 bg-white text-slate-900 hover:bg-slate-50 focus-visible:ring-slate-300",
    dropdownPanel: "border-slate-200 bg-white",
    dropdownItem: "hover:bg-slate-100 text-slate-900",
    dropdownItemActive: "bg-sky-100 text-sky-900",
  };
}

function CompactDropdown({
  value,
  options,
  onChange,
  buttonClassName,
  panelClassName,
  itemClassName,
  itemActiveClassName,
  fullWidth = false,
  compact = false,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    function handleOutsideClick(event) {
      if (!rootRef.current) return;
      if (rootRef.current.contains(event.target)) return;
      setIsOpen(false);
    }

    function handleEscape(event) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    window.addEventListener("mousedown", handleOutsideClick);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handleOutsideClick);
      window.removeEventListener("keydown", handleEscape);
    };
  }, []);

  const selectedOption = options.find((option) => option.value === value) || options[0];

  return (
    <div ref={rootRef} className={`relative ${fullWidth ? "w-full" : "w-auto"}`}>
      <button
        type="button"
        onClick={() => setIsOpen((previous) => !previous)}
        className={`inline-flex items-center justify-between gap-3 rounded-xl border px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-4 ${
          compact ? "py-2" : "py-3"
        } ${
          fullWidth ? "w-full" : "min-w-[140px]"
        } ${buttonClassName}`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className="truncate">{selectedOption?.label || "Select"}</span>
        <span aria-hidden="true" className="text-base leading-none">
          ▾
        </span>
      </button>

      {isOpen && (
        <div className={`absolute z-30 mt-2 max-h-72 overflow-auto rounded-xl border p-1 shadow-lg ${fullWidth ? "w-full" : "w-56"} ${panelClassName}`}>
          <ul role="listbox" className="space-y-1">
            {options.map((option) => (
              <li key={option.value}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(option.value);
                    setIsOpen(false);
                  }}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm ${itemClassName} ${
                    option.value === value ? itemActiveClassName : ""
                  }`}
                >
                  {option.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function resolvePublicCsvPath(fileName) {
  const baseUrl = import.meta.env.BASE_URL || "/";
  return `${baseUrl}${fileName}`;
}

export default function App() {
  const [selectedSet, setSelectedSet] = useLocalStorage("flashcards.v1.selectedSet", "hsk5");
  const [sessionSizeInput, setSessionSizeInput] = useLocalStorage("flashcards.v1.sessionSize", 10);
  const [reviewPool, setReviewPool] = useLocalStorage("flashcards.v1.reviewPool", "not_mastered");
  const [uiTheme, setUiTheme] = useLocalStorage("flashcards.v1.uiTheme", "classic");
  const [builtinWordSets, setBuiltinWordSets] = useLocalStorage("flashcards.v2.builtinWordSets", {});
  const [customSets, setCustomSets] = useLocalStorage("flashcards.v1.customSets", []);

  const [view, setView] = useState("dashboard");
  const [sessionWords, setSessionWords] = useState([]);
  const [sessionIndex, setSessionIndex] = useState(0);
  const [sessionDecisions, setSessionDecisions] = useState({});
  const [sessionStats, setSessionStats] = useState({
    total: 0,
    mastered: 0,
    notMastered: 0,
    reviewed: 0,
  });
  const [showSessionComplete, setShowSessionComplete] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [vocabularyFilter, setVocabularyFilter] = useState("all");
  const [vocabularySearch, setVocabularySearch] = useState("");
  const [visibleRows, setVisibleRows] = useState(120);
  const progressImportRef = useRef(null);
  const themeTokens = useMemo(() => getThemeTokens(uiTheme), [uiTheme]);

  useEffect(() => {
    if (UI_THEMES.some((theme) => theme.value === uiTheme)) return;
    setUiTheme("classic");
  }, [uiTheme, setUiTheme]);

  const datasetOptions = useMemo(() => {
    const uploaded = customSets.map((set) => ({
      value: set.id,
      label: set.label,
    }));

    return [...BUILTIN_DATASETS, ...uploaded];
  }, [customSets]);

  const allWords = useMemo(() => {
    const builtin = BUILTIN_DATASETS.find((set) => set.value === selectedSet);
    if (builtin) return builtinWordSets[selectedSet] || [];

    const custom = customSets.find((set) => set.id === selectedSet);
    return custom?.words || [];
  }, [builtinWordSets, customSets, selectedSet]);

  const counts = useMemo(() => countByMastery(allWords), [allWords]);
  const reviewPoolWords = useMemo(() => getReviewPoolWords(allWords, reviewPool), [allWords, reviewPool]);

  const filteredVocabulary = useMemo(() => {
    const query = vocabularySearch.trim().toLowerCase();

    return allWords.filter((word) => {
      if (vocabularyFilter === "mastered" && word.masteryStatus !== "mastered") return false;
      if (vocabularyFilter === "not_mastered" && word.masteryStatus !== "not_mastered") return false;

      if (!query) return true;

      const haystack = `${word.hanzi} ${word.pinyin} ${word.english}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [allWords, vocabularyFilter, vocabularySearch]);

  const visibleVocabularyRows = useMemo(
    () => filteredVocabulary.slice(0, visibleRows),
    [filteredVocabulary, visibleRows]
  );

  const remainingVocabularyRows = Math.max(0, filteredVocabulary.length - visibleVocabularyRows.length);

  const reviewPoolLabel = useMemo(() => {
    if (reviewPool === "mastered") return "Mastered";
    if (reviewPool === "all") return "All";
    return "Not Mastered";
  }, [reviewPool]);

  useEffect(() => {
    setVocabularyFilter("all");
    setVocabularySearch("");
    setVisibleRows(120);
  }, [selectedSet]);

  useEffect(() => {
    setVisibleRows(120);
  }, [vocabularyFilter, vocabularySearch]);

  useEffect(() => {
    let isMounted = true;

    async function bootstrapSelectedBuiltInDataset() {
      const selectedBuiltin = BUILTIN_DATASETS.find((set) => set.value === selectedSet);
      if (!selectedBuiltin) return;

      const cachedWords = builtinWordSets[selectedSet] || [];
      const hasExpectedCount =
        !selectedBuiltin.expectedCount || cachedWords.length === selectedBuiltin.expectedCount;

      if (cachedWords.length > 0 && hasExpectedCount) return;

      setIsLoading(true);
      setError("");

      try {
        const loadedWords = await loadWordsFromCsv(resolvePublicCsvPath(selectedBuiltin.csvFile));
        if (!isMounted) return;

        setBuiltinWordSets((previous) => ({
          ...previous,
          [selectedSet]: loadedWords,
        }));
      } catch (_error) {
        if (!isMounted) return;
        setError(`Could not load ${selectedBuiltin.label}. Make sure public/${selectedBuiltin.csvFile} exists.`);
      } finally {
        if (!isMounted) return;
        setIsLoading(false);
      }
    }

    bootstrapSelectedBuiltInDataset();

    return () => {
      isMounted = false;
    };
  }, [builtinWordSets, selectedSet, setBuiltinWordSets]);

  useEffect(() => {
    if (BUILTIN_DATASETS.some((set) => set.value === selectedSet)) return;

    const existsInCustom = customSets.some((set) => set.id === selectedSet);
    if (!existsInCustom) {
      setSelectedSet("hsk5");
    }
  }, [customSets, selectedSet, setSelectedSet]);

  function updateSelectedSetWords(updater) {
    if (BUILTIN_DATASETS.some((set) => set.value === selectedSet)) {
      setBuiltinWordSets((previousSets) => ({
        ...previousSets,
        [selectedSet]: updater(previousSets[selectedSet] || []),
      }));
      return;
    }

    setCustomSets((previousSets) =>
      previousSets.map((set) => {
        if (set.id !== selectedSet) return set;

        return {
          ...set,
          words: updater(set.words),
        };
      })
    );
  }

  function buildSessionStats(decisions, total) {
    const entries = Object.values(decisions);
    const mastered = entries.filter((decision) => decision === "mastered").length;
    const notMastered = entries.filter((decision) => decision === "not_mastered").length;

    return {
      total,
      reviewed: entries.length,
      mastered,
      notMastered,
    };
  }

  function applySessionDecisions(decisions) {
    const entries = Object.entries(decisions);
    if (entries.length === 0) return;

    updateSelectedSetWords((previousWords) =>
      previousWords.map((word) => {
        const decision = decisions[word.id];
        if (!decision) return word;

        if (decision === "mastered") {
          return {
            ...word,
            masteryStatus: "mastered",
          };
        }

        return {
          ...word,
          masteryStatus: "not_mastered",
        };
      })
    );
  }

  function handleStartSession() {
    const desiredCount = Math.max(1, Number(sessionSizeInput) || 1);
    const pickedWords = pickSessionWords(allWords, desiredCount, reviewPool);

    if (pickedWords.length === 0) {
      setError(`No words available in the ${reviewPoolLabel} pool. Choose another review pool or update word status.`);
      return;
    }

    setError("");
    setMessage("");
    setSessionWords(pickedWords);
    setSessionIndex(0);
    setSessionDecisions({});
    setSessionStats({
      total: pickedWords.length,
      mastered: 0,
      notMastered: 0,
      reviewed: 0,
    });
    setShowSessionComplete(false);
    setView("session");
  }

  function handleSessionSizeChange(event) {
    const rawValue = event.target.value;
    const digitsOnly = rawValue.replace(/\D+/g, "");

    if (!digitsOnly) {
      setSessionSizeInput(1);
      return;
    }

    const normalized = digitsOnly.replace(/^0+/, "") || "1";
    const parsed = Number.parseInt(normalized, 10);
    const maxAllowed = Math.max(1, reviewPoolWords.length || 1);
    const clamped = Number.isFinite(parsed) ? Math.min(Math.max(1, parsed), maxAllowed) : 1;
    setSessionSizeInput(clamped);
  }

  function handleSessionAnswer(wordId, decision) {
    if (!wordId) return;

    setSessionDecisions((previousDecisions) => {
      const nextDecisions = {
        ...previousDecisions,
        [wordId]: decision,
      };

      setSessionStats(buildSessionStats(nextDecisions, sessionWords.length));
      return nextDecisions;
    });
  }

  function handleSessionPrevious() {
    setSessionIndex((previousIndex) => Math.max(0, previousIndex - 1));
  }

  function handleSessionNext() {
    if (sessionIndex >= sessionWords.length - 1) {
      handleFinishSession();
      return;
    }

    setSessionIndex((previousIndex) => previousIndex + 1);
  }

  function handleFinishSession() {
    applySessionDecisions(sessionDecisions);
    setShowSessionComplete(true);
    setView("summary");
  }

  function handleReturnToDashboard() {
    setView("dashboard");
    setShowSessionComplete(false);
  }

  function handleOpenVocabularyBrowser() {
    setError("");
    setMessage("");
    setView("vocabulary");
  }

  function handleOpenBackupMenu() {
    setError("");
    setMessage("");
    setView("backup");
  }

  function handleLoadMoreVocabulary() {
    setVisibleRows((previous) => previous + 120);
  }

  function handleSetVocabularyWordStatus(wordId, nextStatus) {
    if (!wordId) return;

    updateSelectedSetWords((previousWords) => {
      if (nextStatus === "mastered") {
        return markWordMastered(previousWords, wordId);
      }

      return markWordNotMastered(previousWords, wordId);
    });
  }

  function handleResetCurrentSetStatus() {
    if (allWords.length === 0) return;

    const shouldReset = window.confirm(
      "Reset all words in the current set to Not Mastered? This clears mastered/not mastered progress for this set only."
    );

    if (!shouldReset) return;

    updateSelectedSetWords((previousWords) =>
      previousWords.map((word) => ({
        ...word,
        masteryStatus: "not_mastered",
      }))
    );

    setMessage("Current set status has been reset to Not Mastered.");
    setError("");
  }

  function handleDownloadProgress() {
    const payload = {
      kind: PROGRESS_EXPORT_KIND,
      version: PROGRESS_EXPORT_VERSION,
      exportedAt: new Date().toISOString(),
      data: {
        selectedSet,
        sessionSizeInput,
        reviewPool,
        builtinWordSets,
        customSets,
      },
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const datePart = new Date().toISOString().slice(0, 10);

    anchor.href = url;
    anchor.download = `flashcards-progress-${datePart}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);

    setError("");
    setMessage("Progress backup file downloaded.");
  }

  function handleOpenProgressImport() {
    progressImportRef.current?.click();
  }

  async function handleImportProgress(event) {
    const file = event.target.files?.[0];
    if (!file) return;

    setError("");
    setMessage("");

    try {
      const raw = await file.text();
      const parsed = JSON.parse(raw);

      if (!parsed || parsed.kind !== PROGRESS_EXPORT_KIND) {
        setError("Invalid progress file. Please choose a file exported from this app.");
        return;
      }

      const data = parsed.data || {};

      if (data.builtinWordSets && typeof data.builtinWordSets === "object") {
        setBuiltinWordSets(data.builtinWordSets);
      }

      if (Array.isArray(data.customSets)) {
        setCustomSets(data.customSets);
      }

      if (typeof data.selectedSet === "string") {
        setSelectedSet(data.selectedSet);
      }

      if (typeof data.sessionSizeInput === "number" && Number.isFinite(data.sessionSizeInput)) {
        setSessionSizeInput(data.sessionSizeInput);
      }

      if (["not_mastered", "mastered", "all"].includes(data.reviewPool)) {
        setReviewPool(data.reviewPool);
      }

      setMessage("Progress imported successfully. Your local progress has been updated from this file.");
    } catch (_error) {
      setError("Could not import progress. Please upload a valid JSON progress file.");
    } finally {
      event.target.value = "";
    }
  }

  return (
    <main className={`theme-${uiTheme} min-h-screen py-8 sm:py-12 ${themeTokens.appBackground}`}>
      <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
        <header className={`mb-8 rounded-3xl border p-6 backdrop-blur ${themeTokens.headerCard}`}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="pl-1 sm:pl-2">
              <h1 className="text-3xl font-bold text-slate-900 sm:text-4xl">HSK Vocabulary Learning Flashcards</h1>
              <p className="mt-3 max-w-2xl text-slate-600">
                Pick your vocabulary set, choose session size, and review one card at a time.
              </p>
            </div>

            <CompactDropdown
              value={uiTheme}
              options={UI_THEMES}
              onChange={setUiTheme}
              buttonClassName={themeTokens.dropdownButton}
              panelClassName={themeTokens.dropdownPanel}
              itemClassName={themeTokens.dropdownItem}
              itemActiveClassName={themeTokens.dropdownItemActive}
              compact
            />
          </div>

          <div className={`mt-4 rounded-2xl border p-4 text-sm ${themeTokens.noticeCard}`}>
            This web app is static and local. All data stays in this browser only. To transfer across devices, use
            <button
              type="button"
              onClick={handleOpenBackupMenu}
              className="mx-1 font-semibold underline underline-offset-4"
            >
              Progress Backup
            </button>
            to export / import a JSON file.
          </div>

        </header>

        {isLoading && (
          <section className="rounded-3xl border border-slate-200 bg-white p-6 text-slate-700 shadow-md">
            Loading vocabulary set...
          </section>
        )}

        {error && (
          <section className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-red-700">{error}</section>
        )}

        {message && (
          <section className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800">
            {message}
          </section>
        )}

        {!isLoading && view === "dashboard" && (
          <section className={`rounded-3xl border p-6 ${themeTokens.surfaceCard}`}>
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="sm:col-span-2">
                <span className="mb-2 block text-sm font-semibold text-slate-700">Vocabulary Set</span>
                <CompactDropdown
                  value={selectedSet}
                  options={datasetOptions}
                  onChange={setSelectedSet}
                  buttonClassName={themeTokens.dropdownButton}
                  panelClassName={themeTokens.dropdownPanel}
                  itemClassName={themeTokens.dropdownItem}
                  itemActiveClassName={themeTokens.dropdownItemActive}
                  fullWidth
                  compact={false}
                />
              </label>

              <label>
                <span className="mb-2 block text-sm font-semibold text-slate-700">Session Size</span>
                <input
                  type="number"
                  inputMode="numeric"
                  pattern="[1-9][0-9]*"
                  min={1}
                  max={reviewPoolWords.length || 1}
                  step={1}
                  value={sessionSizeInput}
                  onChange={handleSessionSizeChange}
                  className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
                />
              </label>
            </div>

            <div className={`mt-4 rounded-2xl border p-4 ${themeTokens.mutedCard}`}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-700">Review Pool</p>
                <button
                  type="button"
                  onClick={handleResetCurrentSetStatus}
                  className="inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-300"
                >
                  Reset Status
                </button>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                <button
                  type="button"
                  onClick={() => setReviewPool("all")}
                  className={`rounded-xl border px-3 py-2 text-sm font-medium transition ${
                    reviewPool === "all"
                      ? "border-sky-300 bg-sky-100 text-sky-900"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  All ({allWords.length})
                </button>
                <button
                  type="button"
                  onClick={() => setReviewPool("not_mastered")}
                  className={`rounded-xl border px-3 py-2 text-sm font-medium transition ${
                    reviewPool === "not_mastered"
                      ? "border-rose-300 bg-rose-100 text-rose-900"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  Not Mastered ({counts.notMastered})
                </button>
                <button
                  type="button"
                  onClick={() => setReviewPool("mastered")}
                  className={`rounded-xl border px-3 py-2 text-sm font-medium transition ${
                    reviewPool === "mastered"
                      ? "border-emerald-300 bg-emerald-100 text-emerald-900"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  Mastered ({counts.mastered})
                </button>
              </div>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl p-4">
                <p className="text-sm font-medium text-slate-500">Total Words</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{allWords.length}</p>
              </div>
              <div className="rounded-2xl bg-rose-50 p-4">
                <p className="text-sm font-medium text-rose-700">Not Mastered</p>
                <p className="mt-1 text-2xl font-bold text-rose-900">{counts.notMastered}</p>
              </div>
              <div className="rounded-2xl bg-emerald-50 p-4">
                <p className="text-sm font-medium text-emerald-700">Mastered</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{counts.mastered}</p>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleStartSession}
                className={`inline-flex items-center justify-center rounded-2xl px-8 py-3 text-base font-semibold shadow-md transition focus:outline-none focus-visible:ring-4 ${themeTokens.primaryButton}`}
              >
                Start
              </button>
              <button
                type="button"
                onClick={handleOpenVocabularyBrowser}
                className={`inline-flex items-center justify-center rounded-2xl border px-6 py-3 text-base font-semibold shadow-sm transition focus:outline-none focus-visible:ring-4 ${themeTokens.secondaryButton}`}
              >
                View Vocabulary
              </button>
              <button
                type="button"
                onClick={handleOpenBackupMenu}
                className={`inline-flex items-center justify-center rounded-2xl border px-6 py-3 text-base font-semibold shadow-sm transition focus:outline-none focus-visible:ring-4 ${themeTokens.secondaryButton}`}
              >
                Progress Backup
              </button>
            </div>
          </section>
        )}

        {!isLoading && view === "session" && sessionWords.length > 0 && (
          <FlashcardSession
            sessionWords={sessionWords}
            currentIndex={sessionIndex}
            totalCount={sessionStats.total}
            onMarkWord={handleSessionAnswer}
            onGoPrevious={handleSessionPrevious}
            onGoNext={handleSessionNext}
            onFinishSession={handleFinishSession}
            currentDecision={sessionDecisions[sessionWords[sessionIndex]?.id] || null}
          />
        )}

        {!isLoading && view === "summary" && showSessionComplete && (
          <section className="rounded-3xl border border-slate-200 bg-white p-6 text-center shadow-xl sm:p-8">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-sky-700">Session Complete</p>
            <h2 className="mt-2 text-3xl font-bold text-slate-900">Great Work</h2>
            <p className="mt-2 text-slate-600">You finished this review session. Here is your result snapshot.</p>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-500">Reviewed</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{sessionStats.reviewed}</p>
              </div>
              <div className="rounded-2xl bg-rose-50 p-4">
                <p className="text-sm font-medium text-rose-700">Not Mastered</p>
                <p className="mt-1 text-2xl font-bold text-rose-900">{sessionStats.notMastered}</p>
              </div>
              <div className="rounded-2xl bg-emerald-50 p-4">
                <p className="text-sm font-medium text-emerald-700">Mastered</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{sessionStats.mastered}</p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleReturnToDashboard}
              className="mt-8 inline-flex items-center justify-center rounded-2xl bg-slate-900 px-8 py-3 text-base font-semibold text-white shadow-md transition hover:bg-slate-800 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-300"
            >
              Back To Dashboard
            </button>
          </section>
        )}

        {!isLoading && view === "vocabulary" && (
          <section className={`rounded-3xl border p-6 ${themeTokens.surfaceCard}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className={`text-sm font-semibold uppercase tracking-[0.2em] ${themeTokens.headingTag}`}>Vocabulary Browser</p>
                <h2 className="mt-1 text-2xl font-bold text-slate-900">Browse and Filter Words</h2>
              </div>
              <button
                type="button"
                onClick={handleReturnToDashboard}
                className={`inline-flex items-center justify-center rounded-xl border px-4 py-2 text-sm font-semibold ${themeTokens.secondaryButton}`}
              >
                Back To Dashboard
              </button>
            </div>

            <div className="mt-5 grid gap-3 lg:grid-cols-3">
              <label className="lg:col-span-2">
                <span className="mb-2 block text-sm font-semibold text-slate-700">Search</span>
                <input
                  type="search"
                  value={vocabularySearch}
                  onChange={(event) => setVocabularySearch(event.target.value)}
                  placeholder="Search by hanzi, pinyin, or meaning"
                  className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
                />
              </label>
              <label>
                <span className="mb-2 block text-sm font-semibold text-slate-700">Status Filter</span>
                <select
                  value={vocabularyFilter}
                  onChange={(event) => setVocabularyFilter(event.target.value)}
                  className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
                >
                  <option value="all">All</option>
                  <option value="mastered">Mastered</option>
                  <option value="not_mastered">Not Mastered</option>
                </select>
              </label>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-500">Filtered Results</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{filteredVocabulary.length}</p>
              </div>
              <div className="rounded-2xl bg-rose-50 p-4">
                <p className="text-sm font-medium text-rose-700">Not Mastered</p>
                <p className="mt-1 text-2xl font-bold text-rose-900">{counts.notMastered}</p>
              </div>
              <div className="rounded-2xl bg-emerald-50 p-4">
                <p className="text-sm font-medium text-emerald-700">Mastered</p>
                <p className="mt-1 text-2xl font-bold text-emerald-900">{counts.mastered}</p>
              </div>
            </div>

            <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200">
              <div className="max-h-[60vh] overflow-auto">
                <table className="min-w-full table-fixed divide-y divide-slate-200 text-left text-sm">
                  <thead className={`sticky top-0 ${themeTokens.tableHead}`}>
                    <tr>
                      <th className="w-14 px-4 py-3 font-semibold">#</th>
                      <th className="w-28 px-4 py-3 font-semibold">Hanzi</th>
                      <th className="w-36 px-4 py-3 font-semibold">Pinyin</th>
                      <th className="px-4 py-3 font-semibold">Meaning</th>
                      <th className="w-40 px-4 py-3 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {visibleVocabularyRows.map((word, index) => (
                      <tr key={`${word.id}-${word.hanzi}-${index}`} className="hover:bg-slate-50">
                        <td className="px-4 py-3 text-slate-500">{index + 1}</td>
                        <td className="px-4 py-3 text-lg font-semibold text-slate-900">{word.hanzi}</td>
                        <td className="px-4 py-3 text-slate-700">{word.pinyin}</td>
                        <td className="px-4 py-3 text-slate-700">{word.english}</td>
                        <td className="px-4 py-3">
                          <div className="inline-flex w-full overflow-hidden rounded-lg border border-slate-300">
                            <button
                              type="button"
                              onClick={() => handleSetVocabularyWordStatus(word.id, "not_mastered")}
                              className={`flex-1 px-2 py-1 text-xs font-semibold ${
                                word.masteryStatus === "not_mastered"
                                  ? "bg-rose-100 text-rose-800"
                                  : "bg-white text-slate-600 hover:bg-slate-50"
                              }`}
                            >
                              Not Mastered
                            </button>
                            <button
                              type="button"
                              onClick={() => handleSetVocabularyWordStatus(word.id, "mastered")}
                              className={`flex-1 border-l border-slate-300 px-2 py-1 text-xs font-semibold ${
                                word.masteryStatus === "mastered"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-white text-slate-600 hover:bg-slate-50"
                              }`}
                            >
                              Mastered
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {filteredVocabulary.length === 0 && (
              <p className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                No words match your current filters.
              </p>
            )}

            {remainingVocabularyRows > 0 && (
              <div className="mt-4 flex items-center justify-between gap-3">
                <p className="text-sm text-slate-600">
                  Showing {visibleVocabularyRows.length} of {filteredVocabulary.length}
                </p>
                <button
                  type="button"
                  onClick={handleLoadMoreVocabulary}
                  className={`inline-flex items-center justify-center rounded-xl border px-4 py-2 text-sm font-semibold ${themeTokens.secondaryButton}`}
                >
                  Load 120 More
                </button>
              </div>
            )}
          </section>
        )}

        {!isLoading && view === "backup" && (
          <section className={`rounded-3xl border p-6 ${themeTokens.surfaceCard}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className={`text-sm font-semibold uppercase tracking-[0.2em] ${themeTokens.headingTag}`}>Progress Backup</p>
                <h2 className="mt-1 text-2xl font-bold text-slate-900">Download or Restore Progress</h2>
              </div>
              <button
                type="button"
                onClick={handleReturnToDashboard}
                className={`inline-flex items-center justify-center rounded-xl border px-4 py-2 text-sm font-semibold ${themeTokens.secondaryButton}`}
              >
                Back To Dashboard
              </button>
            </div>

            <p className="mt-4 text-sm text-slate-600">
              Save a JSON backup on one device, then upload it on another device to continue with the same study
              progress.
            </p>

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleDownloadProgress}
                className={`inline-flex items-center justify-center rounded-xl border px-4 py-2 text-sm font-semibold ${themeTokens.secondaryButton}`}
              >
                Download Progress JSON
              </button>
              <button
                type="button"
                onClick={handleOpenProgressImport}
                className={`inline-flex items-center justify-center rounded-xl border px-4 py-2 text-sm font-semibold ${themeTokens.secondaryButton}`}
              >
                Upload Progress JSON
              </button>
              <input
                ref={progressImportRef}
                type="file"
                accept=".json,application/json"
                onChange={handleImportProgress}
                className="hidden"
              />
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
