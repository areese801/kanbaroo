import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const AUTH_STORAGE_KEY = 'kanbaroo.token';

export type AuthState = {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      setToken: (token: string) => set({ token }),
      clearToken: () => set({ token: null }),
    }),
    {
      name: AUTH_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
    },
  ),
);
