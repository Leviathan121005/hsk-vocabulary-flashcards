import { MASTERY_STATUS } from "../data/mockHsk5Words";

function parseCsvLine(line) {
  const cells = [];
  let current = "";
  let insideQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];

    if (char === '"') {
      const isEscapedQuote = insideQuotes && line[i + 1] === '"';
      if (isEscapedQuote) {
        current += '"';
        i += 1;
      } else {
        insideQuotes = !insideQuotes;
      }
      continue;
    }

    if (char === "," && !insideQuotes) {
      cells.push(current.trim());
      current = "";
      continue;
    }

    current += char;
  }

  cells.push(current.trim());
  return cells;
}

function hasLikelyHeader(firstRow) {
  const lowered = firstRow.map((cell) => cell.toLowerCase());
  return lowered.some((cell) =>
    ["id", "no", "word", "hanzi", "pinyin", "meaning", "english", "translation"].includes(cell)
  );
}

function resolveHeaderMap(headerRow) {
  const indexByHeader = new Map();

  headerRow.forEach((cell, index) => {
    indexByHeader.set(cell.toLowerCase(), index);
  });

  const read = (...aliases) => {
    for (const alias of aliases) {
      if (indexByHeader.has(alias)) return indexByHeader.get(alias);
    }
    return -1;
  };

  return {
    id: read("id", "no"),
    hanzi: read("hanzi", "word"),
    pinyin: read("pinyin"),
    meaning: read("meaning", "english", "translation"),
    partOfSpeech: read("part_of_speech", "partofspeech", "pos"),
  };
}

function isAllHanzi(text) {
  const compact = (text || "").replace(/\s+/g, "");
  if (!compact) return false;

  for (const char of compact) {
    if (!/\p{Script=Han}/u.test(char)) {
      return false;
    }
  }

  return true;
}

function normalizeWord({ row, headerMap, fallbackId }) {
  const readByHeader = (index) => (index >= 0 ? row[index] || "" : "");

  let rawId = "";
  let hanzi = "";
  let pinyin = "";
  let partOfSpeech = "";
  let english = "";

  if (headerMap) {
    rawId = readByHeader(headerMap.id);
    hanzi = readByHeader(headerMap.hanzi);
    pinyin = readByHeader(headerMap.pinyin);
    english = readByHeader(headerMap.meaning);
    partOfSpeech = readByHeader(headerMap.partOfSpeech);
  } else if (row.length >= 5) {
    [rawId, hanzi, pinyin, partOfSpeech, english] = row;
  } else if (row.length >= 4) {
    [rawId, hanzi, pinyin, english] = row;
  } else {
    [hanzi, pinyin, english] = row;
  }

  const id = Number(rawId) || fallbackId;

  return {
    id,
    hanzi: (hanzi || "").trim(),
    pinyin: (pinyin || "").trim(),
    english: (english || "").trim(),
    partOfSpeech: (partOfSpeech || "").trim(),
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  };
}

export function parseVocabularyCsv(rawCsv, sourceName = "uploaded.csv") {
  const lines = (rawCsv || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length === 0) {
    return {
      words: [],
      errors: [`${sourceName}: CSV is empty.`],
      warnings: [],
    };
  }

  const parsedRows = lines.map(parseCsvLine);
  const hasHeader = hasLikelyHeader(parsedRows[0]);
  const dataRows = hasHeader ? parsedRows.slice(1) : parsedRows;
  const headerMap = hasHeader ? resolveHeaderMap(parsedRows[0]) : null;

  const words = [];
  const errors = [];
  const warnings = [];

  dataRows.forEach((row, index) => {
    const lineNumber = index + (hasHeader ? 2 : 1);
    const normalized = normalizeWord({ row, headerMap, fallbackId: index + 1 });

    if (!normalized.hanzi || !normalized.pinyin || !normalized.english) {
      errors.push(`Line ${lineNumber}: missing hanzi, pinyin, or meaning.`);
      return;
    }

    if (!isAllHanzi(normalized.hanzi)) {
      errors.push(`Line ${lineNumber}: hanzi field contains non-Hanzi characters.`);
      return;
    }

    words.push(normalized);
  });

  if (!hasHeader) {
    warnings.push(
      "No CSV header detected. Parsed by column order: id,hanzi,pinyin,meaning (or hanzi,pinyin,meaning)."
    );
  }

  if (words.length === 0 && errors.length === 0) {
    errors.push(`${sourceName}: no valid data rows found.`);
  }

  return { words, errors, warnings };
}

export async function loadWordsFromCsv(csvUrl) {
  const response = await fetch(csvUrl);
  if (!response.ok) {
    throw new Error(`Unable to load CSV file: ${csvUrl}`);
  }

  const rawCsv = await response.text();
  const lines = rawCsv
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length <= 1) {
    return [];
  }

  const parsed = parseVocabularyCsv(rawCsv, csvUrl);
  if (parsed.words.length === 0 && parsed.errors.length > 0) {
    throw new Error(parsed.errors[0]);
  }

  if (parsed.errors.length > 0) {
    console.warn(`Skipped ${parsed.errors.length} invalid row(s) while loading ${csvUrl}.`);
  }

  return parsed.words;
}
