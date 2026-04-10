let accessToken: string | null = null;

export function setAccessToken(next: string | null | undefined): void {
  accessToken = next?.trim() || null;
}

function readAccessTokenFromStorage(): string | null {
  if (typeof window === "undefined") return null;
  const stores = [window.sessionStorage, window.localStorage];

  for (const store of stores) {
    try {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i) ?? "";
        if (!key.startsWith("oidc.user:")) continue;
        const raw = store.getItem(key);
        if (!raw) continue;
        const parsed = JSON.parse(raw) as { access_token?: unknown } | null;
        const token = typeof parsed?.access_token === "string" ? parsed.access_token.trim() : "";
        if (token) return token;
      }
    } catch {
      // Ignore storage and parsing errors and continue.
    }
  }

  return null;
}

export function getAccessToken(): string | null {
  if (!accessToken) {
    accessToken = readAccessTokenFromStorage();
  }
  return accessToken;
}
