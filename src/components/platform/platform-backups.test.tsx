import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PlatformBackups } from "./platform-backups";

const mocks = vi.hoisted(() => ({
  backups: vi.fn(),
  createBackup: vi.fn(),
  restoreBackup: vi.fn(),
  recentRun: vi.fn((operation: () => unknown) => operation()),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", async () => {
  const original = await vi.importActual<typeof import("@oracle/api-client")>(
    "@oracle/api-client",
  );
  return {
    ...original,
    api: {
      platform: {
        backups: mocks.backups,
        createBackup: mocks.createBackup,
        restoreBackup: mocks.restoreBackup,
      },
    },
  };
});

vi.mock("@/components/auth/recent-auth", () => ({
  useRecentAuth: () => ({ run: mocks.recentRun }),
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));

const backup = {
  id: "backup-20260711",
  backup_name: "oracle-20260711.sql.gz",
  status: "available" as const,
  origin: "scheduled" as const,
  backup_created_at: "2026-07-11T02:00:00Z",
  verified_at: "2026-07-11T02:02:00Z",
  expires_at: "2026-08-10T02:00:00Z",
  size_bytes: 1_572_864,
  sha256: "a".repeat(64),
};

describe("PlatformBackups", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.recentRun.mockImplementation((operation: () => unknown) => operation());
    mocks.backups.mockResolvedValue({
      items: [backup],
      operations: [],
      retention_days: 30,
      storage_path: "/var/backups/opn-oracle/daily",
    });
    mocks.createBackup.mockResolvedValue({ operation_id: "operation-1", operation_type: "manual_backup", status: "queued", artifact_id: null, created_at: "2026-07-11T02:00:00Z", started_at: null, finished_at: null, error_code: null });
    mocks.restoreBackup.mockResolvedValue({
      operation_id: "operation-2", operation_type: "restore", status: "queued", artifact_id: backup.id, created_at: "2026-07-11T02:00:00Z", started_at: null, finished_at: null, error_code: null,
    });
  });

  it("muestra la política, ubicación y copias disponibles", async () => {
    render(<PlatformBackups />);

    expect(await screen.findByText("oracle-20260711.sql.gz")).toBeInTheDocument();
    expect(screen.getByText("/var/backups/opn-oracle/daily")).toBeInTheDocument();
    expect(screen.getByText("30 días")).toBeInTheDocument();
    expect(screen.getByText("Programada")).toBeInTheDocument();
    expect(screen.getByText("1,5 MB")).toBeInTheDocument();
  });

  it("crea una copia manual mediante autenticación reciente", async () => {
    render(<PlatformBackups />);
    await screen.findByText("oracle-20260711.sql.gz");

    fireEvent.click(screen.getByRole("button", { name: "Crear copia ahora" }));

    await waitFor(() => expect(mocks.createBackup).toHaveBeenCalledTimes(1));
    expect(mocks.recentRun).toHaveBeenCalledTimes(1);
    expect(mocks.success).toHaveBeenCalledWith("Copia de seguridad solicitada");
  });

  it("exige la frase exacta y solo solicita una recuperación", async () => {
    render(<PlatformBackups />);
    await screen.findByText("oracle-20260711.sql.gz");

    fireEvent.click(screen.getByRole("button", { name: "Recuperar" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "Un operador root deberá aprobarla",
    );
    const submit = screen.getByRole("button", { name: "Solicitar recuperación" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "RECUPERAR oracle-20260711.sql.gz" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() =>
      expect(mocks.restoreBackup).toHaveBeenCalledWith(
        "backup-20260711",
        "RECUPERAR oracle-20260711.sql.gz",
      ),
    );
    expect(mocks.recentRun).toHaveBeenCalledTimes(1);
  });
});
