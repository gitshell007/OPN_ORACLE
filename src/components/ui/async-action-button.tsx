"use client";

import {
  type ButtonHTMLAttributes,
  forwardRef,
  type ReactNode,
  useSyncExternalStore,
} from "react";

type AsyncActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean;
  loadingLabel?: ReactNode;
  hydrationLabel?: ReactNode;
};

function subscribeToHydration() {
  return () => undefined;
}

function getClientHydrationSnapshot() {
  return true;
}

function getServerHydrationSnapshot() {
  return false;
}

export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribeToHydration,
    getClientHydrationSnapshot,
    getServerHydrationSnapshot,
  );
}

export const HydratedActionButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement>
>(function HydratedActionButton(
  {
    disabled,
    children,
    className = "vector-primary",
    type = "button",
    ...props
  },
  ref,
) {
  const hydrated = useHydrated();
  const blocked = disabled || !hydrated;

  return (
    <button
      ref={ref}
      {...props}
      type={type}
      className={className}
      disabled={blocked}
      aria-disabled={blocked}
      data-action-ready={!blocked}
      data-hydrated={hydrated}
    >
      {children}
    </button>
  );
});

export function AsyncActionButton({
  loading = false,
  loadingLabel,
  hydrationLabel = "Cargando…",
  disabled,
  children,
  className = "vector-primary",
  type = "button",
  ...props
}: AsyncActionButtonProps) {
  const hydrated = useHydrated();
  const busy = loading || !hydrated;
  const blocked = disabled || busy;
  const label = !hydrated ? hydrationLabel : loading ? loadingLabel ?? children : children;

  return (
    <button
      {...props}
      type={type}
      className={className}
      disabled={blocked}
      aria-disabled={blocked}
      aria-busy={busy}
      data-action-ready={!blocked}
      data-hydrated={hydrated}
    >
      {label}
    </button>
  );
}
