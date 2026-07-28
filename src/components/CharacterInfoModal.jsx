import { useEffect, useMemo, useState } from "react";

const INITIAL_ITEM_LIMIT = 12;
const LOAD_MORE_COUNT = 12;
const TOOLTIP_MAX_WIDTH = 220;
const TOOLTIP_VIEWPORT_MARGIN = 12;

function resolveCharacterInfoPath() {
  const baseUrl = import.meta.env.BASE_URL || "/";
  return `${baseUrl}character_info.json`;
}

function resolvePinyinIndexPath() {
  const baseUrl = import.meta.env.BASE_URL || "/";
  return `${baseUrl}pinyin_to_characters.json`;
}

function resolveOtherUseCasesPath() {
  const baseUrl = import.meta.env.BASE_URL || "/";
  return `${baseUrl}other_use_cases.json`;
}

function pinyinBase(reading) {
  return reading.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace("ü", "v").toLowerCase();
}

function ItemLimitControls({ shown, total, onShowMore, onShowLess, lessClassName, moreClassName }) {
  if (total <= INITIAL_ITEM_LIMIT) return null;

  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {shown > INITIAL_ITEM_LIMIT && (
        <button
          type="button"
          onClick={onShowLess}
          className={lessClassName}
        >
          Show {Math.min(LOAD_MORE_COUNT, shown - INITIAL_ITEM_LIMIT)} less
        </button>
      )}
      {shown < total && (
        <button
          type="button"
          onClick={onShowMore}
          className={moreClassName}
        >
          Show {Math.min(LOAD_MORE_COUNT, total - shown)} more
        </button>
      )}
    </div>
  );
}

function CollapsibleSection({ title, count, isOpen, onToggle, children, sectionClassName, triggerClassName, titleClassName, countClassName, bodyClassName }) {
  return (
    <section className={sectionClassName}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        className={triggerClassName}
      >
        <span className={titleClassName}>{title}</span>
        <span className={countClassName}>
          {count}
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`h-4 w-4 transition-transform ${isOpen ? "rotate-180" : ""}`}
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </button>
      {isOpen && <div className={bodyClassName}>{children}</div>}
    </section>
  );
}

export function CharacterInfoModal({ isOpen, onClose, word, pinyin, meaning, theme = "classic" }) {
  const [characterInfo, setCharacterInfo] = useState(null);
  const [pinyinIndex, setPinyinIndex] = useState(null);
  const [otherUseCasesIndex, setOtherUseCasesIndex] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const characters = useMemo(() => Array.from(word || ""), [word]);
  const [selectedCharacter, setSelectedCharacter] = useState(characters[0] || "");
  const [visualLimit, setVisualLimit] = useState(INITIAL_ITEM_LIMIT);
  const [pinyinLimit, setPinyinLimit] = useState(INITIAL_ITEM_LIMIT);
  const [usecaseLimit, setUsecaseLimit] = useState(INITIAL_ITEM_LIMIT);
  const [openSections, setOpenSections] = useState({ visual: true, pinyin: true, usecases: true });
  const [hoverTooltip, setHoverTooltip] = useState(null);

  const themeClasses = useMemo(() => {
    if (theme === "dark") {
      return {
        shell: "border border-slate-700 bg-slate-900",
        header: "border-b border-slate-700 bg-slate-900",
        titleTag: "text-sky-300",
        title: "text-slate-100",
        closeButton:
          "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-600 bg-slate-800 text-slate-200 transition hover:bg-slate-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-500",
        body: "bg-slate-950",
        tabStrip: "border-b border-slate-700",
        tabActive: "border-sky-700 bg-slate-800 text-sky-100",
        tabInactive: "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800",
        loading: "py-10 text-center text-sm text-slate-300",
        noInfo: "mt-5 rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300",
        section: "rounded-lg border border-slate-700 bg-slate-900",
        sectionTrigger:
          "flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition hover:bg-slate-800 focus:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-slate-500 sm:px-5",
        sectionTitle: "font-bold text-slate-100",
        sectionCount: "flex items-center gap-3 text-sm text-slate-400",
        sectionBody: "border-t border-slate-700 px-4 py-4 sm:px-5",
        tile: "inline-flex min-w-0 flex-col items-center rounded-lg border border-sky-800 bg-slate-800 px-2 py-3 text-center text-2xl font-semibold text-sky-100",
        tileSub: "mt-1 text-[12px] leading-tight font-medium text-sky-200 whitespace-nowrap",
        tileBubble:
          "relative w-max max-w-[220px] rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-left text-xs font-medium leading-snug text-slate-100 shadow-xl",
        tileBubbleTail: "absolute -top-1 left-1/2 h-2.5 w-2.5 -translate-x-1/2 rotate-45 border-l border-t border-slate-600 bg-slate-800",
        emptyHint: "text-sm text-slate-400",
        lessButton:
          "rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm font-semibold text-slate-200 transition hover:bg-slate-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-500",
        moreButton:
          "rounded-lg border border-sky-700 bg-slate-800 px-3 py-2 text-sm font-semibold text-sky-200 transition hover:bg-slate-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-500",
        tableWrap: "overflow-x-auto rounded-lg border border-slate-700",
        tableHead: "bg-slate-800 text-slate-200",
        tableBody: "divide-y divide-slate-700 bg-slate-900",
        usecaseWord: "px-3 py-2.5 text-xl font-semibold text-slate-100",
        usecasePinyin: "px-3 py-2.5 text-sky-200",
        usecaseMeaning: "px-3 py-2.5 text-slate-300",
      };
    }

    if (theme === "paper") {
      return {
        shell: "border border-stone-300 bg-stone-50",
        header: "border-b border-stone-300 bg-stone-50",
        titleTag: "text-stone-700",
        title: "text-stone-900",
        closeButton:
          "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-stone-300 bg-stone-100 text-stone-700 transition hover:bg-stone-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-stone-300",
        body: "bg-stone-100",
        tabStrip: "border-b border-stone-300",
        tabActive: "border-stone-500 bg-stone-200 text-stone-900",
        tabInactive: "border-stone-300 bg-stone-50 text-stone-700 hover:bg-stone-100",
        loading: "py-10 text-center text-sm text-stone-600",
        noInfo: "mt-5 rounded-lg border border-stone-300 bg-stone-50 p-4 text-sm text-stone-700",
        section: "rounded-lg border border-stone-300 bg-stone-50",
        sectionTrigger:
          "flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition hover:bg-stone-100 focus:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-stone-300 sm:px-5",
        sectionTitle: "font-bold text-stone-900",
        sectionCount: "flex items-center gap-3 text-sm text-stone-500",
        sectionBody: "border-t border-stone-200 px-4 py-4 sm:px-5",
        tile: "inline-flex min-w-0 flex-col items-center rounded-lg border border-amber-200 bg-amber-50 px-2 py-3 text-center text-2xl font-semibold text-amber-900",
        tileSub: "mt-1 text-[12px] leading-tight font-medium text-amber-800 whitespace-nowrap",
        tileBubble:
          "relative w-max max-w-[220px] rounded-md border border-stone-300 bg-stone-50 px-3 py-2 text-left text-xs font-medium leading-snug text-stone-800 shadow-lg",
        tileBubbleTail: "absolute -top-1 left-1/2 h-2.5 w-2.5 -translate-x-1/2 rotate-45 border-l border-t border-stone-300 bg-stone-50",
        emptyHint: "text-sm text-stone-500",
        lessButton:
          "rounded-lg border border-stone-300 bg-stone-50 px-3 py-2 text-sm font-semibold text-stone-700 transition hover:bg-stone-100 focus:outline-none focus-visible:ring-4 focus-visible:ring-stone-300",
        moreButton:
          "rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-100 focus:outline-none focus-visible:ring-4 focus-visible:ring-amber-200",
        tableWrap: "overflow-x-auto rounded-lg border border-stone-300",
        tableHead: "bg-stone-200 text-stone-700",
        tableBody: "divide-y divide-stone-200 bg-stone-50",
        usecaseWord: "px-3 py-2.5 text-xl font-semibold text-stone-900",
        usecasePinyin: "px-3 py-2.5 text-amber-900",
        usecaseMeaning: "px-3 py-2.5 text-stone-700",
      };
    }

    return {
      shell: "bg-slate-50",
      header: "border-b border-slate-200 bg-white",
      titleTag: "text-sky-700",
      title: "text-slate-900",
      closeButton:
        "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-200",
      body: "bg-slate-50",
      tabStrip: "border-b border-slate-200",
      tabActive: "border-sky-300 bg-sky-100 text-sky-900",
      tabInactive: "border-slate-200 bg-white text-slate-600 hover:bg-slate-100",
      loading: "py-10 text-center text-sm text-slate-600",
      noInfo: "mt-5 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600",
      section: "rounded-lg border border-slate-200 bg-white",
      sectionTrigger:
        "flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition hover:bg-slate-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-sky-200 sm:px-5",
      sectionTitle: "font-bold text-slate-900",
      sectionCount: "flex items-center gap-3 text-sm text-slate-500",
      sectionBody: "border-t border-slate-100 px-4 py-4 sm:px-5",
      tile: "inline-flex min-w-0 flex-col items-center rounded-lg border border-sky-100 bg-sky-50 px-2 py-3 text-center text-2xl font-semibold text-sky-900",
      tileSub: "mt-1 text-[12px] leading-tight font-medium text-sky-700 whitespace-nowrap",
      tileBubble:
        "relative w-max max-w-[220px] rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-xs font-medium leading-snug text-slate-700 shadow-lg",
      tileBubbleTail: "absolute -top-1 left-1/2 h-2.5 w-2.5 -translate-x-1/2 rotate-45 border-l border-t border-slate-200 bg-white",
      emptyHint: "text-sm text-slate-500",
      lessButton:
        "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-200",
      moreButton:
        "rounded-lg border border-sky-200 bg-white px-3 py-2 text-sm font-semibold text-sky-700 transition hover:bg-sky-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-200",
      tableWrap: "overflow-x-auto rounded-lg border border-slate-200",
      tableHead: "bg-slate-100 text-slate-700",
      tableBody: "divide-y divide-slate-100 bg-white",
      usecaseWord: "px-3 py-2.5 text-xl font-semibold text-slate-900",
      usecasePinyin: "px-3 py-2.5 text-sky-700",
      usecaseMeaning: "px-3 py-2.5 text-slate-600",
    };
  }, [theme]);

  useEffect(() => {
    setSelectedCharacter(characters[0] || "");
    setVisualLimit(INITIAL_ITEM_LIMIT);
    setPinyinLimit(INITIAL_ITEM_LIMIT);
    setUsecaseLimit(INITIAL_ITEM_LIMIT);
    setOpenSections({ visual: true, pinyin: true, usecases: true });
  }, [characters]);

  useEffect(() => {
    if (!isOpen || characterInfo) return undefined;

    let isCurrent = true;
    setIsLoading(true);
    setLoadError("");

    fetch(resolveCharacterInfoPath())
      .then((response) => {
        if (!response.ok) throw new Error("Character information is unavailable.");
        return response.json();
      })
      .then((data) => {
        if (isCurrent) setCharacterInfo(data);
      })
      .catch(() => {
        if (isCurrent) setLoadError("Character information could not be loaded.");
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false);
      });

    return () => {
      isCurrent = false;
    };
  }, [characterInfo, isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;

    let isCurrent = true;
    fetch(resolvePinyinIndexPath())
      .then((response) => {
        if (!response.ok) throw new Error("Pinyin index is unavailable.");
        return response.json();
      })
      .then((data) => {
        if (isCurrent) setPinyinIndex(data);
      })
      .catch(() => {
        if (isCurrent) setLoadError("Character information could not be loaded.");
      });

    return () => {
      isCurrent = false;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;

    let isCurrent = true;
    fetch(resolveOtherUseCasesPath())
      .then((response) => {
        if (!response.ok) throw new Error("Other use cases index is unavailable.");
        return response.json();
      })
      .then((data) => {
        if (isCurrent) setOtherUseCasesIndex(data);
      })
      .catch(() => {
        if (isCurrent) setLoadError("Character information could not be loaded.");
      });

    return () => {
      isCurrent = false;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;

    function handleKeyDown(event) {
      if (event.key === "Escape") onClose?.();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const selectedInfo = characterInfo?.[selectedCharacter];
  const visualGroups = selectedInfo?.similar_visual_chars || [];
  const visualMatches = visualGroups.flatMap((group) =>
    group.characters.map((characterReference) => ({
      ...characterReference,
      components: characterReference.matching_components || group.components || [],
    }))
  );
  const similarPinyinMatches = Array.from(
    new Set([selectedInfo?.sample_pinyin, ...(selectedInfo?.other_pinyins || [])].filter(Boolean).map(pinyinBase))
  ).flatMap((pinyin) =>
    Object.entries(pinyinIndex?.[pinyin] || {}).flatMap(([tone, matchingCharacters]) =>
      matchingCharacters
        .filter((character) => character !== selectedCharacter)
        .map((character) => ({ character, pinyin, tone }))
    )
  ).reduce((matches, { character, pinyin, tone }) => {
    const existing = matches.get(character) || { character, matchingPinyin: pinyin, pinyins: [] };
    if (!existing.pinyins.includes(tone)) existing.pinyins.push(tone);
    matches.set(character, existing);
    return matches;
  }, new Map());
  const similarPinyinCharacters = Array.from(similarPinyinMatches.values()).sort((left, right) =>
    left.character.localeCompare(right.character, "zh-Hans")
  );
  const selectedUsecaseIndexes = otherUseCasesIndex?.by_character?.[selectedCharacter] || [];
  const allUseCaseEntries = otherUseCasesIndex?.entries || [];

  const usecases = selectedUsecaseIndexes
    .map((index) => allUseCaseEntries[index])
    .filter(Boolean)
    .filter((usecase) => usecase.word !== word);

  function selectCharacter(character) {
    setSelectedCharacter(character);
    setVisualLimit(INITIAL_ITEM_LIMIT);
    setPinyinLimit(INITIAL_ITEM_LIMIT);
    setUsecaseLimit(INITIAL_ITEM_LIMIT);
  }

  function toggleSection(section) {
    setOpenSections((previous) => ({ ...previous, [section]: !previous[section] }));
  }

  function showMeaningTooltip(event, tooltipText) {
    const text = (tooltipText || "").trim();
    if (!text) return;

    const rect = event.currentTarget.getBoundingClientRect();
    const margin = TOOLTIP_VIEWPORT_MARGIN;
    const halfTooltipWidth = TOOLTIP_MAX_WIDTH / 2;
    const centerX = rect.left + rect.width / 2;
    const clampedX = Math.min(
      window.innerWidth - margin - halfTooltipWidth,
      Math.max(margin + halfTooltipWidth, centerX)
    );
    const y = rect.bottom + 10;

    setHoverTooltip({ text, x: clampedX, y });
  }

  function hideMeaningTooltip() {
    setHoverTooltip(null);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex touch-none items-end justify-center bg-slate-950/45 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="character-info-title"
        className={`flex max-h-[95vh] w-full max-w-3xl flex-col overflow-hidden rounded-t-2xl shadow-2xl sm:rounded-2xl ${themeClasses.shell}`}
      >
        <header className={`flex items-start justify-between gap-4 px-5 py-4 sm:px-6 ${themeClasses.header}`}>
          <div>
            <p className={`text-xs font-semibold uppercase tracking-[0.16em] ${themeClasses.titleTag}`}>Character Notes</p>
            <h2 id="character-info-title" className={`mt-2 text-xl font-bold ${themeClasses.title}`}>
              {word || "Character information"}
              {pinyin && <span className="ml-2 text-base font-medium text-slate-500">{pinyin}</span>}
            </h2>
            {meaning && <p className="mt-1 max-w-[30ch] truncate text-sm text-slate-600">{meaning}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close character information"
            className={themeClasses.closeButton}
          >
            <span aria-hidden="true" className="text-2xl leading-none">×</span>
          </button>
        </header>

        <div className={`min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain px-5 pb-7 pt-5 sm:px-6 ${themeClasses.body}`}>
          <div className={`flex gap-2 overflow-x-auto pb-3 ${themeClasses.tabStrip}`} role="tablist" aria-label="Characters in word">
            {characters.map((character, index) => (
              <button
                key={`${character}-${index}`}
                type="button"
                role="tab"
                aria-selected={selectedCharacter === character}
                onClick={() => selectCharacter(character)}
                className={`min-w-12 rounded-lg border px-4 py-2 text-lg font-bold transition focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-200 ${
                  selectedCharacter === character
                    ? themeClasses.tabActive
                    : themeClasses.tabInactive
                }`}
              >
                {character}
              </button>
            ))}
          </div>

          {isLoading && <p className={themeClasses.loading}>Loading character information...</p>}
          {loadError && <p className="mt-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{loadError}</p>}
          {!isLoading && !loadError && !selectedInfo && (
            <p className={themeClasses.noInfo}>
              No HSK character information is available for {selectedCharacter || "this character"}.
            </p>
          )}

          {!isLoading && selectedInfo && (
            <div className="mt-5 space-y-4">
              <CollapsibleSection
                title="Visually Similar Characters"
                count={visualMatches.length}
                isOpen={openSections.visual}
                onToggle={() => toggleSection("visual")}
                sectionClassName={themeClasses.section}
                triggerClassName={themeClasses.sectionTrigger}
                titleClassName={themeClasses.sectionTitle}
                countClassName={themeClasses.sectionCount}
                bodyClassName={themeClasses.sectionBody}
              >
                {visualMatches.length > 0 ? (
                  <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(64px, max-content))" }}>
                    {visualMatches.slice(0, visualLimit).map(({ character, pinyins, score, meaning: entryMeaning }, index) => {
                      const tileMeaning = (entryMeaning || characterInfo?.[character]?.meaning || "").trim();
                      return (
                      <span
                        key={`${character}-${index}`}
                        className={`group relative ${themeClasses.tile}`}
                        onMouseEnter={(event) => showMeaningTooltip(event, tileMeaning)}
                        onMouseLeave={hideMeaningTooltip}
                      >
                        {character}
                        <span className={themeClasses.tileSub}>{pinyins.join(" / ")}</span>
                      </span>
                    )})}
                  </div>
                ) : (
                  <p className={themeClasses.emptyHint}>No shared structural components were found in this HSK set.</p>
                )}
                <ItemLimitControls
                  shown={visualLimit}
                  total={visualMatches.length}
                  onShowMore={() => setVisualLimit((value) => Math.min(visualMatches.length, value + LOAD_MORE_COUNT))}
                  onShowLess={() => setVisualLimit((value) => Math.max(INITIAL_ITEM_LIMIT, value - LOAD_MORE_COUNT))}
                  lessClassName={themeClasses.lessButton}
                  moreClassName={themeClasses.moreButton}
                />
              </CollapsibleSection>

              <CollapsibleSection
                title="Similar Pinyin Characters"
                count={similarPinyinCharacters.length}
                isOpen={openSections.pinyin}
                onToggle={() => toggleSection("pinyin")}
                sectionClassName={themeClasses.section}
                triggerClassName={themeClasses.sectionTrigger}
                titleClassName={themeClasses.sectionTitle}
                countClassName={themeClasses.sectionCount}
                bodyClassName={themeClasses.sectionBody}
              >
                {similarPinyinCharacters.length > 0 ? (
                  <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(64px, max-content))" }}>
                    {similarPinyinCharacters.slice(0, pinyinLimit).map(({ character, pinyins, matchingPinyin }) => {
                      const tileMeaning = (characterInfo?.[character]?.meaning || "").trim();
                      return (
                      <span
                        key={character}
                        className={`group relative ${themeClasses.tile}`}
                        onMouseEnter={(event) => showMeaningTooltip(event, tileMeaning)}
                        onMouseLeave={hideMeaningTooltip}
                      >
                        {character}
                        <span className={themeClasses.tileSub}>{pinyins.join(" / ") || matchingPinyin}</span>
                      </span>
                    )})}
                  </div>
                ) : (
                  <p className={themeClasses.emptyHint}>No same-sound HSK characters were found.</p>
                )}
                <ItemLimitControls
                  shown={pinyinLimit}
                  total={similarPinyinCharacters.length}
                  onShowMore={() => setPinyinLimit((value) => Math.min(similarPinyinCharacters.length, value + LOAD_MORE_COUNT))}
                  onShowLess={() => setPinyinLimit((value) => Math.max(INITIAL_ITEM_LIMIT, value - LOAD_MORE_COUNT))}
                  lessClassName={themeClasses.lessButton}
                  moreClassName={themeClasses.moreButton}
                />
              </CollapsibleSection>

              <CollapsibleSection
                title="Other HSK Use Cases"
                count={usecases.length}
                isOpen={openSections.usecases}
                onToggle={() => toggleSection("usecases")}
                sectionClassName={themeClasses.section}
                triggerClassName={themeClasses.sectionTrigger}
                titleClassName={themeClasses.sectionTitle}
                countClassName={themeClasses.sectionCount}
                bodyClassName={themeClasses.sectionBody}
              >
                {usecases.length > 0 ? (
                  <div className={themeClasses.tableWrap}>
                    <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                      <thead className={themeClasses.tableHead}>
                        <tr>
                          <th className="w-20 px-3 py-2.5 font-semibold">Hanzi</th>
                          <th className="px-3 py-2.5 font-semibold">Pinyin</th>
                          <th className="px-3 py-2.5 font-semibold">Meaning</th>
                        </tr>
                      </thead>
                      <tbody className={themeClasses.tableBody}>
                        {usecases.slice(0, usecaseLimit).map((usecase, index) => (
                          <tr key={`${usecase.word}-${usecase.pinyin}-${index}`}>
                            <td className={`${themeClasses.usecaseWord} w-20 whitespace-nowrap`}>{usecase.word}</td>
                            <td className={themeClasses.usecasePinyin}>{usecase.pinyin}</td>
                            <td className={themeClasses.usecaseMeaning}>{usecase.meaning}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className={themeClasses.emptyHint}>No additional HSK use cases were found.</p>
                )}
                <ItemLimitControls
                  shown={usecaseLimit}
                  total={usecases.length}
                  onShowMore={() => setUsecaseLimit((value) => Math.min(usecases.length, value + LOAD_MORE_COUNT))}
                  onShowLess={() => setUsecaseLimit((value) => Math.max(INITIAL_ITEM_LIMIT, value - LOAD_MORE_COUNT))}
                  lessClassName={themeClasses.lessButton}
                  moreClassName={themeClasses.moreButton}
                />
              </CollapsibleSection>
            </div>
          )}
        </div>
      </section>
      {hoverTooltip && (
        <div
          className="pointer-events-none fixed z-[80] -translate-x-1/2"
          style={{ left: `${hoverTooltip.x}px`, top: `${hoverTooltip.y}px` }}
        >
          <div className={themeClasses.tileBubble} style={{ opacity: 1, transform: "none" }}>
            <span className={themeClasses.tileBubbleTail} aria-hidden="true" />
            {hoverTooltip.text}
          </div>
        </div>
      )}
    </div>
  );
}