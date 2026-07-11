import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ reauthenticate: vi.fn() }));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public problem: { code: string },
    ) {
      super("Confirma tu identidad");
    }
  }
  return { ApiError, api: { auth: { reauthenticate: mocks.reauthenticate } } };
});

import { ApiError } from "@oracle/api-client";
import { RecentAuthProvider, useRecentAuth } from "./recent-auth";

function Harness({ action }: { action: () => Promise<string> }) {
  const recent = useRecentAuth();
  return (
    <button onClick={() => void recent.run(action)}>Acción sensible</button>
  );
}

describe("RecentAuthProvider", () => {
  it("confirma contraseña y reintenta una acción recent-auth", async () => {
    mocks.reauthenticate.mockResolvedValueOnce({ status: "fresh" });
    const action = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(401, { code: "recent_auth_required" } as never),
      )
      .mockResolvedValueOnce("completada");
    render(
      <RecentAuthProvider>
        <Harness action={action} />
      </RecentAuthProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Acción sensible" }));
    expect(
      await screen.findByRole("dialog", { name: "Confirma tu identidad" }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "frase segura" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Confirmar y continuar" }),
    );
    await waitFor(() => expect(action).toHaveBeenCalledTimes(2));
    expect(mocks.reauthenticate).toHaveBeenCalledWith("frase segura");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
