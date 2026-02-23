import { atom } from "recoil";

export type UserRole = "Admin" | "Compliance Officer" | "Analyst" | "Viewer";

export type SystemUser = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  createdAt: string;
};

const STORAGE_KEY = "tapan_ofac_users_v1";

function safeString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeRole(value: string): UserRole {
  const role = value.trim().toLowerCase();
  if (role === "admin") return "Admin";
  if (role === "compliance officer") return "Compliance Officer";
  if (role === "viewer") return "Viewer";
  return "Analyst";
}

function toTitleCase(input: string): string {
  return input
    .split(" ")
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1).toLowerCase() : ""))
    .join(" ")
    .trim();
}

function deriveNameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  const normalized = local.replace(/[._-]+/g, " ").trim();
  return toTitleCase(normalized || "Team Member");
}

function normalizeUser(value: unknown): SystemUser | null {
  if (!isRecord(value)) return null;

  const email = safeString(value.email).toLowerCase();
  if (!email) return null;

  const firstName = safeString(value.firstName);
  const lastName = safeString(value.lastName);
  const legacyName = [firstName, lastName].filter(Boolean).join(" ");
  const name = safeString(value.name) || legacyName || deriveNameFromEmail(email);

  return {
    id: safeString(value.id) || `${Date.now()}_${Math.random().toString(16).slice(2)}`,
    name,
    email,
    role: normalizeRole(safeString(value.role)),
    createdAt: safeString(value.createdAt) || new Date().toISOString(),
  };
}

function loadInitial(): SystemUser[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => normalizeUser(item))
      .filter((item): item is SystemUser => item !== null);
  } catch {
    return [];
  }
}

export const usersState = atom<SystemUser[]>({
  key: "usersState",
  default: loadInitial(),
  effects: [
    ({ onSet }) => {
      onSet((newValue) => {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(newValue));
        } catch {
          // ignore storage errors
        }
      });
    },
  ],
});
