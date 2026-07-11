"use client";

import { ApiError, api, type SessionIdentity } from "@oracle/api-client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export type AuthStatus =
  | "initializing"
  | "anonymous"
  | "authenticated"
  | "session_expired"
  | "forbidden"
  | "tenant_suspended"
  | "error";

interface AuthValue {
  status: AuthStatus;
  identity: SessionIdentity | null;
  error: ApiError | null;
  can(permission: string): boolean;
  login(
    email: string,
    password: string,
    tenantId?: string,
  ): Promise<SessionIdentity>;
  logout(): Promise<void>;
  refresh(): Promise<void>;
  switchTenant(tenantId: string): Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

function statusFor(error: unknown, hadIdentity: boolean): AuthStatus {
  if (!(error instanceof ApiError)) return "error";
  if (error.status === 401)
    return hadIdentity ? "session_expired" : "anonymous";
  if (["tenant_suspended", "membership_suspended"].includes(error.problem.code))
    return "tenant_suspended";
  if (error.status === 403) return "forbidden";
  return "error";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("initializing");
  const [identity, setIdentity] = useState<SessionIdentity | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const identityRef = useRef<SessionIdentity | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await api.auth.me(signal);
      identityRef.current = next;
      setIdentity(next);
      setError(null);
      setStatus("authenticated");
      window.dispatchEvent(
        new CustomEvent("oracle:tenant-changed", {
          detail: { tenantId: next.active_tenant_id },
        }),
      );
    } catch (reason) {
      if (signal?.aborted) return;
      const apiError = reason instanceof ApiError ? reason : null;
      setError(apiError);
      setStatus(statusFor(reason, Boolean(identityRef.current)));
      if (reason instanceof ApiError && reason.status === 401) {
        identityRef.current = null;
        setIdentity(null);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const kickoff = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      window.clearTimeout(kickoff);
      controller.abort();
    };
  }, [load]);

  useEffect(() => {
    const onAuthError = (event: Event) => {
      const reason = (event as CustomEvent<ApiError>).detail;
      setError(reason);
      setStatus(statusFor(reason, Boolean(identityRef.current)));
      if (reason.status === 401) {
        identityRef.current = null;
        setIdentity(null);
      }
    };
    window.addEventListener("oracle:auth-error", onAuthError);
    return () => window.removeEventListener("oracle:auth-error", onAuthError);
  }, []);

  const login = useCallback(
    async (email: string, password: string, tenantId?: string) => {
      await api.auth.login({ email, password, tenant_id: tenantId });
      const next = await api.auth.me();
      identityRef.current = next;
      setIdentity(next);
      setError(null);
      setStatus("authenticated");
      window.dispatchEvent(
        new CustomEvent("oracle:tenant-changed", {
          detail: { tenantId: next.active_tenant_id },
        }),
      );
      return next;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
      identityRef.current = null;
      setIdentity(null);
      setError(null);
      setStatus("anonymous");
    } catch (reason) {
      const fatal =
        reason instanceof ApiError &&
        ["authentication_required", "session_expired"].includes(
          reason.problem.code,
        );
      if (!fatal) {
        setError(reason instanceof ApiError ? reason : null);
        await load();
      }
      throw reason;
    }
  }, [load]);

  const switchTenant = useCallback(
    async (tenantId: string) => {
      setStatus("initializing");
      setError(null);
      try {
        await api.auth.switchTenant(tenantId);
        await load();
      } catch (reason) {
        setError(reason instanceof ApiError ? reason : null);
        await load();
        throw reason;
      }
    },
    [load],
  );

  const value = useMemo<AuthValue>(
    () => ({
      status,
      identity,
      error,
      login,
      logout,
      refresh: load,
      switchTenant,
      can: (permission) => Boolean(identity?.permissions.includes(permission)),
    }),
    [status, identity, error, login, logout, load, switchTenant],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth requiere AuthProvider");
  return value;
}
