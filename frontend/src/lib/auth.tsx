"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { authApi, loadUser, logout as apiLogout, saveAuth } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (
    name: string,
    email: string,
    password: string,
    role: string
  ) => Promise<User>;
  logout: () => void;
  updateUser: (partial: Partial<User>) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedUser = loadUser();
    setUser(storedUser);
    setToken(typeof window !== "undefined" ? window.localStorage.getItem("foodai_access_token") : null);
    setLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await authApi.login(email, password);
    saveAuth(data);
    setUser(data.user);
    setToken(data.access_token);
    return data.user;
  }, []);

  const register = useCallback(
    async (name: string, email: string, password: string, role: string) => {
      const data = await authApi.register(name, email, password, role);
      saveAuth(data);
      setUser(data.user);
      setToken(data.access_token);
      return data.user;
    },
    []
  );

  const logout = useCallback(() => {
    apiLogout();
    setUser(null);
    setToken(null);
  }, []);

  const updateUser = useCallback(
    (partial: Partial<User>) => {
      if (!user) return;
      const merged = { ...user, ...partial };
      setUser(merged);
      // Same key and JSON shape saveAuth uses to persist the user (api.ts).
      window.localStorage.setItem("foodai_user", JSON.stringify(merged));
    },
    [user]
  );

  const value = useMemo(
    () => ({ user, token, loading, login, register, logout, updateUser }),
    [user, token, loading, login, register, logout, updateUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
