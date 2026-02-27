type RuntimeConfig = Record<string, string>;

declare global {
  interface Window {
    __APP_CONFIG__?: RuntimeConfig;
  }
}

export function appEnv(name: string, fallback = ""): string {
  if (typeof window !== "undefined" && window.__APP_CONFIG__ && Object.prototype.hasOwnProperty.call(window.__APP_CONFIG__, name)) {
    const value = String(window.__APP_CONFIG__[name] ?? "").trim();
    if (value) return value;
    return String(fallback ?? "").trim();
  }

  const value = (import.meta.env[name] as string) ?? fallback;
  return String(value ?? fallback).trim();
}
