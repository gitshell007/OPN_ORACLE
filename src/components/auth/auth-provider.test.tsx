import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  me: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  switchTenant: vi.fn(),
}));
vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public problem: { code: string },
    ) {
      super(problem.code);
    }
  }
  return { ApiError, api: { auth: mocks } };
});

import { ApiError } from "@oracle/api-client";
import { AuthProvider, useAuth } from "./auth-provider";

const identity = {
  user: {
    id: "u1",
    email: "owner@example.test",
    display_name: "Owner",
    platform_role: null,
  },
  active_tenant_id: "t1",
  memberships: [
    {
      membership_id: "m1",
      tenant_id: "t1",
      tenant_slug: "uno",
      tenant_name: "Uno",
      membership_status: "active",
    },
  ],
  roles: ["owner"],
  permissions: ["tenant.users.manage"],
};
function problem(status: number, code: string) {
  return new ApiError(status, {
    type: "about:blank",
    title: code,
    status,
    detail: code,
    instance: "",
    code,
    request_id: "",
  });
}
function Harness() {
  const auth = useAuth();
  return (
    <>
      <output>
        {auth.status}:{auth.identity?.active_tenant_id ?? "none"}
      </output>
      <button onClick={() => void auth.logout().catch(() => undefined)}>
        Logout
      </button>
      <button
        onClick={() => void auth.switchTenant("t2").catch(() => undefined)}
      >
        Switch
      </button>
    </>
  );
}

describe("AuthProvider recovery", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.me.mockResolvedValue(identity);
  });

  it("conserva identidad cuando logout falla de forma transitoria", async () => {
    mocks.logout.mockRejectedValueOnce(problem(503, "service_unavailable"));
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );
    await screen.findByText("authenticated:t1");
    fireEvent.click(screen.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(mocks.me).toHaveBeenCalledTimes(2));
    expect(screen.getByText("authenticated:t1")).toBeVisible();
  });

  it("sale de initializing y recupera tenant previo si switch falla", async () => {
    mocks.switchTenant.mockRejectedValueOnce(
      problem(409, "membership_unavailable"),
    );
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );
    await screen.findByText("authenticated:t1");
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    await waitFor(() => expect(mocks.me).toHaveBeenCalledTimes(2));
    expect(screen.getByText("authenticated:t1")).toBeVisible();
  });
});
