import { useEffect, useState } from "react";

/**
 * A tiny React hook that behaves like useState, but also saves to LocalStorage.
 *
 * Example:
 * const [words, setWords] = useLocalStorage("flashcards.v1.words", []);
 */
export function useLocalStorage(key, defaultValue) {
  // Read from LocalStorage once, when the hook is first used.
  const [storedValue, setStoredValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return defaultValue;

      return JSON.parse(raw);
    } catch (_error) {
      // If data is corrupted or blocked, fall back safely.
      return defaultValue;
    }
  });

  // Save every time key or state changes.
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(storedValue));
    } catch (_error) {
      // Silent fail keeps UI usable in restricted environments.
    }
  }, [key, storedValue]);

  return [storedValue, setStoredValue];
}
