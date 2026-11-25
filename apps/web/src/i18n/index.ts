import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import es from "./locales/es.json";
import en from "./locales/en.json";

export const STORAGE_LANG_KEY = "kallicode_admin_lang";
export const SUPPORTED_LANGUAGES = ["es", "en"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export function normalizeLanguage(raw?: string | null): SupportedLanguage {
  if (!raw) return "es";
  const lower = raw.toLowerCase();
  if (lower.startsWith("en")) return "en";
  return "es";
}

function detectInitialLanguage(): SupportedLanguage {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const saved = window.localStorage.getItem(STORAGE_LANG_KEY);
      if (saved === "es" || saved === "en") {
        return saved;
      }
    }
  } catch {
    // Ignore storage access failures in restricted environments
  }
  return "es";
}

function syncDocumentLanguage(lang: string): void {
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.lang = normalizeLanguage(lang);
  }
}

const initialLanguage = detectInitialLanguage();

void i18n.use(initReactI18next).init({
  resources: {
    es: { translation: es },
    en: { translation: en },
  },
  lng: initialLanguage,
  fallbackLng: "es",
  supportedLngs: [...SUPPORTED_LANGUAGES],
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
});

syncDocumentLanguage(i18n.resolvedLanguage || i18n.language || initialLanguage);

i18n.on("languageChanged", (lng: string) => {
  const normalized = normalizeLanguage(lng);
  syncDocumentLanguage(normalized);
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(STORAGE_LANG_KEY, normalized);
    }
  } catch {
    // Ignore storage access failures
  }
});

export async function changeAppLanguage(lang: SupportedLanguage): Promise<void> {
  const normalized = normalizeLanguage(lang);
  await i18n.changeLanguage(normalized);
}

export default i18n;
