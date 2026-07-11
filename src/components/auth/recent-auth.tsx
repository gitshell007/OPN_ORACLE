"use client";

import { ApiError, api } from "@oracle/api-client";
import * as Dialog from "@radix-ui/react-dialog";
import {
  createContext,
  FormEvent,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";

interface PendingAction {
  action: () => Promise<unknown>;
  resolve(value: unknown): void;
  reject(reason?: unknown): void;
}

const RecentAuthContext = createContext<{
  run<T>(action: () => Promise<T>): Promise<T>;
} | null>(null);

export function RecentAuthProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<PendingAction | null>(null);
  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T> => {
    try {
      return await action();
    } catch (reason) {
      if (
        !(reason instanceof ApiError) ||
        reason.problem.code !== "recent_auth_required"
      )
        throw reason;
      return await new Promise<T>((resolve, reject) => {
        pending.current = {
          action,
          resolve: (value) => resolve(value as T),
          reject,
        };
        setPassword("");
        setError(null);
        setOpen(true);
      });
    }
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!pending.current) return;
    setBusy(true);
    setError(null);
    try {
      await api.auth.reauthenticate(password);
      const value = await pending.current.action();
      pending.current.resolve(value);
      pending.current = null;
      setOpen(false);
      setPassword("");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo confirmar la identidad.",
      );
    } finally {
      setBusy(false);
    }
  }
  function cancel() {
    pending.current?.reject(new Error("Reautenticación cancelada"));
    pending.current = null;
    setOpen(false);
    setPassword("");
  }
  return (
    <RecentAuthContext.Provider value={{ run }}>
      {children}
      <Dialog.Root
        open={open}
        onOpenChange={(next) => {
          if (!next && open) cancel();
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="reauth-overlay" />
          <Dialog.Content className="reauth-dialog">
            <Dialog.Title>Confirma tu identidad</Dialog.Title>
            <Dialog.Description>
              Esta acción afecta a la seguridad o al acceso de otras personas.
            </Dialog.Description>
            <form onSubmit={submit}>
              <label className="field">
                <span>Contraseña</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <div>
                <button
                  type="button"
                  className="vector-secondary"
                  onClick={cancel}
                >
                  Cancelar
                </button>
                <button className="vector-primary" disabled={busy}>
                  {busy ? "Confirmando…" : "Confirmar y continuar"}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </RecentAuthContext.Provider>
  );
}

export function useRecentAuth() {
  const value = useContext(RecentAuthContext);
  if (!value) throw new Error("useRecentAuth requiere RecentAuthProvider");
  return value;
}
