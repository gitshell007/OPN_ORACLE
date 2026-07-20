import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    retryAfter?: number;

    constructor(
      public status: number,
      public problem: {
        code: string;
        detail: string;
        request_id?: string;
      },
      retryAfter?: number,
    ) {
      super(problem.detail);
      this.retryAfter = retryAfter;
    }
  }
  return { ApiError, api: { auth: {} } };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams("next=%2Fapp"),
}));

vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    login: mocks.login,
  }),
}));

import { ApiError } from "@oracle/api-client";
import { LoginPage } from "./auth-pages";

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(cleanup);

  it("no muestra referencias técnicas en errores de acceso", async () => {
    mocks.login.mockRejectedValueOnce(
      new ApiError(401, {
        code: "invalid_credentials",
        detail: "Credenciales no válidas.",
        instance: "/api/v1/auth/login",
        request_id: "request-visible-only-in-logs",
        status: 401,
        title: "Credenciales no válidas.",
        type: "about:blank",
      }),
    );
    const { container } = render(<LoginPage />);
    const email = container.querySelector<HTMLInputElement>('input[type="email"]');
    const password = container.querySelector<HTMLInputElement>('input[type="password"]');
    expect(email).not.toBeNull();
    expect(password).not.toBeNull();

    fireEvent.change(email!, { target: { value: "persona@example.test" } });
    fireEvent.change(password!, { target: { value: "clave segura" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar en Oracle" }));

    await screen.findByText("Credenciales no válidas.");
    expect(screen.queryByText(/Referencia:/)).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.login).toHaveBeenCalledTimes(1));
  });
});
