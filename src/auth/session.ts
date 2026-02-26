let accessToken: string | null = null;

export function setAccessToken(next: string | null | undefined): void {
  accessToken = next?.trim() || null;
}

export function getAccessToken(): string | null {
  return accessToken;
}

