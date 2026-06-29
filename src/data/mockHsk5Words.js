// Mastery status values are plain strings so they are easy to save in LocalStorage.
export const MASTERY_STATUS = {
  MASTERED: "mastered",
  NOT_MASTERED: "not_mastered",
};

// Small starter dataset (10 words) for early development and testing.
// Every word starts as NOT_MASTERED.
export const mockHsk5Words = [
  {
    id: 1,
    hanzi: "爱",
    pinyin: "ài",
    english: "to love",
    partOfSpeech: "verb",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 2,
    hanzi: "安全",
    pinyin: "ānquán",
    english: "safe; safety",
    partOfSpeech: "adjective",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 3,
    hanzi: "帮助",
    pinyin: "bāngzhù",
    english: "to help; help",
    partOfSpeech: "verb",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 4,
    hanzi: "必须",
    pinyin: "bìxū",
    english: "must; have to",
    partOfSpeech: "auxiliary",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 5,
    hanzi: "参加",
    pinyin: "cānjiā",
    english: "to participate",
    partOfSpeech: "verb",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 6,
    hanzi: "成功",
    pinyin: "chénggōng",
    english: "success; to succeed",
    partOfSpeech: "noun",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 7,
    hanzi: "打算",
    pinyin: "dǎsuàn",
    english: "plan; to intend",
    partOfSpeech: "verb",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 8,
    hanzi: "地方",
    pinyin: "dìfang",
    english: "place",
    partOfSpeech: "noun",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 9,
    hanzi: "发现",
    pinyin: "fāxiàn",
    english: "to discover",
    partOfSpeech: "verb",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
  {
    id: 10,
    hanzi: "方法",
    pinyin: "fāngfǎ",
    english: "method; way",
    partOfSpeech: "noun",
    masteryStatus: MASTERY_STATUS.NOT_MASTERED,
  },
];
