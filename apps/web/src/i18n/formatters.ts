import i18n, { normalizeLanguage } from "./index";

export type IntlLocaleTag = "es-ES" | "en-US";

export function resolveIntlLocale(lang?: string): IntlLocaleTag {
  const active = normalizeLanguage(lang ?? i18n.resolvedLanguage ?? i18n.language);
  return active === "en" ? "en-US" : "es-ES";
}

export function formatNumber(
  value: number | null | undefined,
  options?: Intl.NumberFormatOptions,
  lang?: string
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "0";
  }
  return new Intl.NumberFormat(resolveIntlLocale(lang), options).format(value);
}

export function formatDecimal(
  value: number | null | undefined,
  decimals = 1,
  lang?: string
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat(resolveIntlLocale(lang), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatTokens(
  value: number | null | undefined,
  options?: { compact?: boolean; lang?: string }
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const locale = resolveIntlLocale(options?.lang);
  if (options?.compact) {
    return new Intl.NumberFormat(locale, {
      notation: "compact",
      minimumFractionDigits: value >= 1_000 ? 1 : 0,
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat(locale).format(value);
}

export function formatPercent(
  value: number | null | undefined,
  options?: { decimals?: number; includeSign?: boolean; lang?: string }
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "0%";
  }
  const decimals = options?.decimals ?? 1;
  return new Intl.NumberFormat(resolveIntlLocale(options?.lang), {
    style: "percent",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    signDisplay: options?.includeSign ? "exceptZero" : "auto",
  }).format(value / 100);
}

export function formatCurrencyEUR(
  value: number | null | undefined,
  currency = "EUR",
  lang?: string
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return new Intl.NumberFormat(resolveIntlLocale(lang), {
      style: "currency",
      currency: currency || "EUR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(0);
  }
  try {
    return new Intl.NumberFormat(resolveIntlLocale(lang), {
      style: "currency",
      currency: currency || "EUR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${formatDecimal(value, 2, lang)} ${currency}`;
  }
}

export function formatDate(
  iso: string | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
  },
  lang?: string
): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(resolveIntlLocale(lang), options).format(date);
}

export function formatDateTime(
  iso: string | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    dateStyle: "short",
    timeStyle: "short",
  },
  lang?: string
): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(resolveIntlLocale(lang), options).format(date);
}

export function formatTime(
  iso: string | null | undefined,
  lang?: string
): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(resolveIntlLocale(lang), {
    timeStyle: "medium",
  }).format(date);
}

export function formatRelativeTime(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  lang?: string
): string {
  return new Intl.RelativeTimeFormat(resolveIntlLocale(lang), {
    numeric: "auto",
  }).format(value, unit);
}
