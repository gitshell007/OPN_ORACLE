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
    await waitFor(() =>
      expect(mocks.login).toHaveBeenCalledWith(
        "persona@example.test",
        "clave segura",
        undefined,
        false,
      ),
    );
  });

  it("envía remember=true al marcar recordar sesión", async () => {
    mocks.login.mockResolvedValueOnce({
      active_tenant_id: "tenant-1",
      memberships: [],
      permissions: [],
      roles: [],
      user: { id: "user-1", email: "persona@example.test", display_name: "Persona" },
    });
    const { container } = render(<LoginPage />);
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="email"]')!, {
      target: { value: "persona@example.test" },
    });
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="password"]')!, {
      target: { value: "clave segura" },
    });
    fireEvent.click(screen.getByLabelText(/Recordar sesión en este dispositivo/i));
    fireEvent.click(screen.getByRole("button", { name: "Entrar en Oracle" }));
    await waitFor(() =>
      expect(mocks.login).toHaveBeenCalledWith(
        "persona@example.test",
        "clave segura",
        undefined,
        true,
      ),
    );
  });

  it.each([
    [
      "bloqueo por credenciales",
      "login_temporarily_locked",
      37,
      "El acceso está bloqueado temporalmente tras varios intentos con credenciales no válidas. Vuelve a probar en 37 segundos.",
    ],
    [
      "límite de diez por minuto",
      "too_many_requests",
      12,
      "Has alcanzado el límite de 10 intentos de acceso por minuto. Vuelve a probar en 12 segundos.",
    ],
    [
      "límite sin cuenta atrás",
      "too_many_requests",
      undefined,
      "Has alcanzado el límite de 10 intentos de acceso por minuto. Vuelve a probar más tarde.",
    ],
    [
      "cuenta atrás a cero",
      "login_temporarily_locked",
      0,
      "El acceso está bloqueado temporalmente tras varios intentos con credenciales no válidas. Vuelve a probar en 0 segundos.",
    ],
  ])(
    "distingue el 429 de %s",
    async (_case, code, retryAfter, expectedMessage) => {
      mocks.login.mockRejectedValueOnce(
        new ApiError(
          429,
          {
            code,
            detail: "Demasiados intentos.",
            instance: "/api/v1/auth/login",
            request_id: "request-rate-limited",
            status: 429,
            title: "Too Many Requests",
            type: "about:blank",
          },
          retryAfter,
        ),
      );
      const { container } = render(<LoginPage />);
      fireEvent.change(
        container.querySelector<HTMLInputElement>('input[type="email"]')!,
        { target: { value: "persona@example.test" } },
      );
      fireEvent.change(
        container.querySelector<HTMLInputElement>('input[type="password"]')!,
        { target: { value: "clave segura" } },
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Entrar en Oracle" }),
      );

      expect(await screen.findByText(expectedMessage)).toBeVisible();
    },
  );
});
