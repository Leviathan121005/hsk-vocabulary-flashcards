import { MASTERY_STATUS } from "../data/mockHsk5Words";

/**
 * Returns only words that are still NOT_MASTERED.
 * This is the pool we use to build a review session.
 */
export function getNotMasteredWords(words) {
  return words.filter((word) => word.masteryStatus === MASTERY_STATUS.NOT_MASTERED);
}

export function getMasteredWords(words) {
  return words.filter((word) => word.masteryStatus === MASTERY_STATUS.MASTERED);
}

export function getReviewPoolWords(words, reviewPool = "not_mastered") {
  if (reviewPool === "mastered") {
    return getMasteredWords(words);
  }

  if (reviewPool === "all") {
    return [...words];
  }

  return getNotMasteredWords(words);
}

/**
 * Fisher-Yates shuffle: a standard way to randomize an array fairly.
 * We clone first so the original array order is not modified.
 */
export function shuffleWords(words) {
  const copy = [...words];

  for (let i = copy.length - 1; i > 0; i -= 1) {
    const randomIndex = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[randomIndex]] = [copy[randomIndex], copy[i]];
  }

  return copy;
}

/**
 * Pull N random words from NOT_MASTERED words.
 * If N is bigger than the available pool, return the whole pool.
 */
export function pickSessionWords(words, requestedCount, reviewPool = "not_mastered") {
  const pool = getReviewPoolWords(words, reviewPool);
  const safeCount = Math.max(0, Number(requestedCount) || 0);
  const shuffled = shuffleWords(pool);

  return shuffled.slice(0, Math.min(safeCount, shuffled.length));
}

/**
 * Core immutable update helper.
 * Returns a new array where one word has a new mastery status.
 */
export function updateWordMasteryStatus(words, wordId, nextStatus) {
  return words.map((word) => {
    if (word.id !== wordId) return word;

    return {
      ...word,
      masteryStatus: nextStatus,
    };
  });
}

/**
 * Convenience wrapper: mark one word as MASTERED.
 */
export function markWordMastered(words, wordId) {
  return updateWordMasteryStatus(words, wordId, MASTERY_STATUS.MASTERED);
}

/**
 * Convenience wrapper: mark one word as NOT_MASTERED.
 */
export function markWordNotMastered(words, wordId) {
  return updateWordMasteryStatus(words, wordId, MASTERY_STATUS.NOT_MASTERED);
}

/**
 * Optional utility for summary cards or setup stats.
 */
export function countByMastery(words) {
  return words.reduce(
    (accumulator, word) => {
      if (word.masteryStatus === MASTERY_STATUS.MASTERED) {
        accumulator.mastered += 1;
      } else {
        accumulator.notMastered += 1;
      }
      return accumulator;
    },
    { mastered: 0, notMastered: 0 }
  );
}
