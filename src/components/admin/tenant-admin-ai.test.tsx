import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  aiPolicy: vi.fn(),
  updateAIPolicy: vi.fn(),
  testAI: vi.fn(),
  recentRun: vi.fn((action: () => Promise<unknown>) => action()),
  toastSuccess: vi.fn(),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    problem = { detail: this.message };
  }
  return {
    ApiError,
    api: {
      tenantAdmin: {
        aiPolicy: mocks.aiPolicy,
        updateAIPolicy: mocks.updateAIPolicy,
        testAI: mocks.testAI,
      },
    },
  };
});
vi.mock("@/components/auth/recent-auth", () => ({
  useRecentAuth: () => ({ run: mocks.recentRun }),
}));
vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess },
}));

import { TenantAIAdmin } from "./tenant-admin";

const policy = {
  enabled: false,
  provider: "mock",
  allowed_models: ["mock-oracle-v1"],
  kill_switch: true,
  max_classification: "public",
  limits: {
    daily_calls: 100,
    max_concurrency: 2,
    max_context_tokens: 8000,
    max_output_tokens: 6500,
    monthly_soft_budget_micros: 0,
    monthly_hard_budget_micros: 0,
  },
  routing_authority: "oracle",
  last_run: null,
  last_error: null,
};

describe("TenantAIAdmin policy controls", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.aiPolicy.mockResolvedValue(policy);
    mocks.updateAIPolicy.mockImplementation(async (input: {
      enabled?: boolean;
      kill_switch?: boolean;
    }) => ({
      ...policy,
      enabled: input.enabled ?? policy.enabled,
      kill_switch: input.kill_switch ?? policy.kill_switch,
    }));
  });

  it("activa la política y desactiva el kill switch desde la interfaz", async () => {
    render(<TenantAIAdmin />);
    expect(await screen.findByTestId("ai-policy-effective")).toHaveTextContent(
      /Desactivada/,
    );
    fireEvent.click(screen.getByTestId("ai-policy-enabled"));
    await waitFor(() =>
      expect(mocks.updateAIPolicy).toHaveBeenCalledWith({ enabled: true }),
    );
    fireEvent.click(screen.getByTestId("ai-policy-kill-switch"));
    await waitFor(() =>
      expect(mocks.updateAIPolicy).toHaveBeenCalledWith({ kill_switch: false }),
    );
    expect(mocks.recentRun).toHaveBeenCalled();
  });
});
