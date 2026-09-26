// @ts-check
// Interface strings. Content direction is decided per message by dir="auto";
// this only controls the interface language and page direction.

/** @type {Record<string, Record<string, string>>} */
const STRINGS = {
  en: {
    appName: "Workspace",
    newChat: "New chat",
    conversations: "Conversations",
    noConversations: "No conversations yet.",
    loading: "Loading…",
    loadFailed: "Could not load. Is the server running?",
    retry: "Retry",
    rename: "Rename",
    delete: "Delete",
    save: "Save",
    cancel: "Cancel",
    confirmDelete: "Delete this conversation? This cannot be undone.",
    untitled: "New conversation",
    placeholder: "Message…",
    inputHint: "Message. Enter to send, Shift+Enter for a new line.",
    send: "Send",
    stop: "Stop",
    emptyTitle: "Start a conversation",
    emptyBody: "Ask a question, draft text or paste code. Hebrew and English are both supported.",
    demoBanner: "Demo mode — replies are simulated, not live AI. Add an API key to aiworkspace/.env to go live.",
    liveBadge: "Live",
    demoBadge: "Demo",
    simulated: "Simulated",
    stopped: "Stopped by you — incomplete",
    truncated: "Incomplete — hit the output token limit",
    refused: "Incomplete — the model declined",
    incomplete: "Incomplete",
    partial: "Partial reply — incomplete",
    tokensIn: "in",
    tokensOut: "out tokens",
    interrupted: "Interrupted",
    thinking: "Generating…",
    tooLong: "Message is too long",
    busyElsewhere: "Wait for the current reply to finish, or stop it.",
    copy: "Copy",
    copied: "Copied",
    menu: "Conversations menu",
    language: "עברית",
    languageLabel: "Switch interface to Hebrew",
    you: "You",
    assistant: "Assistant",
    networkError: "Connection to the server failed.",
    notFound: "This conversation no longer exists.",
    localOnly: "Local prototype · single user",
  },
  he: {
    appName: "סביבת עבודה",
    newChat: "שיחה חדשה",
    conversations: "שיחות",
    noConversations: "אין עדיין שיחות.",
    loading: "טוען…",
    loadFailed: "הטעינה נכשלה. האם השרת פועל?",
    retry: "נסו שוב",
    rename: "שינוי שם",
    delete: "מחיקה",
    save: "שמירה",
    cancel: "ביטול",
    confirmDelete: "למחוק את השיחה? לא ניתן לבטל פעולה זו.",
    untitled: "שיחה חדשה",
    placeholder: "הודעה…",
    inputHint: "הודעה. Enter לשליחה, Shift+Enter לשורה חדשה.",
    send: "שליחה",
    stop: "עצירה",
    emptyTitle: "התחילו שיחה",
    emptyBody: "שאלו שאלה, נסחו טקסט או הדביקו קוד. עברית ואנגלית נתמכות.",
    demoBanner: "מצב הדגמה — התשובות מדומות ואינן בינה מלאכותית אמיתית. הוסיפו מפתח API לקובץ aiworkspace/.env כדי לעבור למצב חי.",
    liveBadge: "חי",
    demoBadge: "הדגמה",
    simulated: "מדומה",
    stopped: "נעצר על ידך — לא הושלם",
    truncated: "לא הושלם — הגיע למגבלת הטוקנים",
    refused: "לא הושלם — המודל סירב",
    incomplete: "לא הושלם",
    partial: "תשובה חלקית — לא הושלמה",
    tokensIn: "קלט",
    tokensOut: "טוקני פלט",
    interrupted: "הופסק",
    thinking: "מייצר תשובה…",
    tooLong: "ההודעה ארוכה מדי",
    busyElsewhere: "המתינו לסיום התשובה הנוכחית או עצרו אותה.",
    copy: "העתקה",
    copied: "הועתק",
    menu: "תפריט שיחות",
    language: "English",
    languageLabel: "Switch interface to English",
    you: "את/ה",
    assistant: "עוזר",
    networkError: "החיבור לשרת נכשל.",
    notFound: "השיחה הזו כבר לא קיימת.",
    localOnly: "אב-טיפוס מקומי · משתמש יחיד",
  },
};

let lang = "en";
try {
  const saved = localStorage.getItem("aiws.lang");
  if (saved && saved in STRINGS) lang = saved;
} catch {
  /* storage unavailable */
}

/** @param {string} key */
export function t(key) {
  return STRINGS[lang][key] ?? STRINGS.en[key] ?? key;
}

export function getLang() {
  return lang;
}

/** @param {string} next */
export function setLang(next) {
  if (!(next in STRINGS)) return;
  lang = next;
  try {
    localStorage.setItem("aiws.lang", next);
  } catch {
    /* storage unavailable */
  }
  applyLang();
}

export function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
}
