import { atom } from "recoil";

export type UserRole = "Admin" | "Analyst" | "Reviewer";
export type UserStatus = "Active" | "Inactive";

export type SystemUser = {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  createdAt: string;
};

const STORAGE_KEY = "tapan_ofac_users_v1";

function loadInitial(): SystemUser[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as SystemUser[];
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
