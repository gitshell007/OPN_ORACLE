"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { useAuth } from "@/components/auth/auth-provider";
import { visibleGlobalRoutes } from "@/lib/app-routes";
import { useOracle } from "./oracle-provider";
import { ApiError, api, type GlobalSearchResult } from "@oracle/api-client";
export function CommandPalette({
  concept,
  onCreate,
}: {
  concept: "a" | "b";
  onCreate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const router = useRouter();
  const { dossiers } = useOracle();
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, []);
  const actions = useMemo(
    () => {
      return [
        {
          label: "Ir a la cartera",
          detail: "Navegación",
          run: () => router.push(`/concept-${concept}/portfolio`),
        },
        {
          label: "Abrir ajustes",
          detail: "Preferencias",
          run: () => router.push(`/concept-${concept}/settings`),
        },
        { label: "Crear expediente", detail: "Acción", run: onCreate },
        {
          label: `Cambiar a ${concept === "a" ? "Horizon" : "Vector"}`,
          detail: "Comparación",
          run: () =>
            router.push(`/concept-${concept === "a" ? "b" : "a"}/portfolio`),
        },
        ...dossiers.slice(0, 8).map((d) => ({
          label: d.title,
          detail: "Expediente",
          run: () => router.push(`/concept-${concept}/dossiers/${d.id}`),
        })),
      ].filter((a) => a.label.toLowerCase().includes(query.toLowerCase()));
    },
    [concept, dossiers, onCreate, query, router],
  );
  const choose = (run: () => void) => {
    setOpen(false);
    setQuery("");
    run();
  };
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          className="command-trigger"
          aria-label="Abrir búsqueda global"
        >
          <Search size={16} />
          <span>Buscar o ir a…</span>
          <kbd>⌘ K</kbd>
        </button>
      </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content command-content">
            <Dialog.Title className="sr-only">Búsqueda global</Dialog.Title>
            <Dialog.Description className="sr-only">
              Busca expedientes o ejecuta una acción.
            </Dialog.Description>
            <Dialog.Close className="dialog-close" aria-label="Cerrar">
              <X size={18} />
            </Dialog.Close>
            <input
              className="command-input"
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar expedientes o acciones…"
              aria-label="Buscar"
            />
            <div className="command-list">
              {actions.length ? (
                actions.map((a) => (
                  <button
                    key={a.label}
                    className="command-item"
                    onClick={() => choose(a.run)}
                  >
                    <span>{a.label}</span>
                    <small>{a.detail}</small>
                  </button>
                ))
              ) : (
                <p style={{ padding: 12, color: "#6c7887" }}>
                  No hay resultados para «{query}».
                </p>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ProductCommandPalette({ onCreate }: { onCreate(): void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const router = useRouter();
  const auth = useAuth();
  const [results, setResults] = useState<GlobalSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);
  useEffect(() => {
    if (!open || query.trim().length < 2) {
      const reset = window.setTimeout(() => {
        setSearching(false);
        setSearchError(null);
        setResults([]);
      }, 0);
      return () => window.clearTimeout(reset);
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      setSearchError(null);
      void api.search
        .query(query, { limit: 5, signal: controller.signal })
        .then((response) => setResults(response.items))
        .catch((reason) => {
          if (controller.signal.aborted) return;
          setSearchError(
            reason instanceof ApiError
              ? reason.problem.detail
              : "Búsqueda temporalmente no disponible.",
          );
          setResults([]);
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearching(false);
        });
    }, 240);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, query]);
  const actions = useMemo(() => {
    const navigation = visibleGlobalRoutes(auth.identity?.permissions ?? []).map(
      (route) => ({
        label: `Ir a ${route.label}`,
        detail: "Navegación",
        run: () => router.push(route.href),
      }),
    );
    const productActions = auth.can("dossier.write")
      ? [{ label: "Crear expediente", detail: "Acción", run: onCreate }]
      : [];
    const commands = [...productActions, ...navigation].filter((action) =>
      action.label.toLowerCase().includes(query.toLowerCase()),
    );
    const searchResults = (query.trim().length >= 2 ? results : []).map((result) => ({
      label: result.title,
      detail: `${result.kind} · ${result.dossier_title || result.subtitle}`,
      run: () => router.push(result.href),
    }));
    return [...commands, ...searchResults];
  }, [auth, onCreate, query, results, router]);
  const choose = (run: () => void) => {
    setOpen(false);
    setQuery("");
    run();
  };
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          className="command-trigger"
          aria-label="Abrir búsqueda global"
        >
          <Search size={16} />
          <span>Buscar o ir a…</span>
          <kbd>⌘ K</kbd>
        </button>
      </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content command-content">
            <Dialog.Title className="sr-only">Comandos de Oracle</Dialog.Title>
            <Dialog.Description className="sr-only">
              Navega por el producto o ejecuta una acción autorizada.
            </Dialog.Description>
            <Dialog.Close className="dialog-close" aria-label="Cerrar">
              <X size={18} />
            </Dialog.Close>
            <input
              className="command-input"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Buscar rutas o acciones…"
              aria-label="Buscar"
            />
            <div className="command-list">
              {searching && <p className="command-status" role="status">Buscando en Oracle…</p>}
              {searchError && <p className="command-error" role="alert">{searchError}</p>}
              {actions.length ? (
                actions.map((action) => (
                  <button
                    key={action.label}
                    className="command-item"
                    onClick={() => choose(action.run)}
                  >
                    <span>{action.label}</span>
                    <small>{action.detail}</small>
                  </button>
                ))
              ) : (
                <p style={{ padding: 12, color: "#6c7887" }}>
                  No hay resultados para «{query}».
                </p>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
    </Dialog.Root>
  );
}
