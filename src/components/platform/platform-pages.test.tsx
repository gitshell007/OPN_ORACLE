import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PlatformTenantDetail } from "./platform-pages";

const mocks = vi.hoisted(() => ({
  tenant: vi.fn(),
  inviteOwner: vi.fn(),
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
        tenant: mocks.tenant,
        inviteOwner: mocks.inviteOwner,
      },
    },
  };
});

vi.mock("@/components/auth/recent-auth", () => ({
  useRecentAuth: () => ({ run: mocks.recentRun }),
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));

describe("PlatformTenantDetail", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.recentRun.mockImplementation((operation: () => unknown) => operation());
    mocks.tenant.mockResolvedValue({
      id: "efb2bca1-187e-41ea-a0d1-1d22ffd17d26",
      name: "OPN Consultoría",
      slug: "opn-consultoria",
      status: "active",
      plan: "enterprise",
    });
    mocks.inviteOwner.mockResolvedValue({ membership_id: "membership-1" });
  });

  it("envía únicamente los campos admitidos por invite-owner", async () => {
    render(
      <PlatformTenantDetail id="efb2bca1-187e-41ea-a0d1-1d22ffd17d26" />,
    );

    await screen.findByRole("heading", { name: "OPN Consultoría" });
    fireEvent.change(screen.getByRole("textbox", { name: "Correo" }), {
      target: { value: "mburgos@iacell.com" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Nombre" }), {
      target: { value: "Miguel Burgos" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar invitación" }));

    await waitFor(() =>
      expect(mocks.inviteOwner).toHaveBeenCalledWith(
        "efb2bca1-187e-41ea-a0d1-1d22ffd17d26",
        { email: "mburgos@iacell.com", name: "Miguel Burgos" },
      ),
    );
    expect(mocks.success).toHaveBeenCalledWith("Propietario invitado");
  });
});
