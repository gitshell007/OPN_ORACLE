/**
 * SV2-UI-E2E: unit coverage of grouped dossier navigation.
 * Protects the 6-group + subnav contract (data-testid, defaults, active group,
 * subnav visibility, single aria-current="page").
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pathname: "/app/dossiers/dossier-1",
  permissions: [
    "dossier.read",
    "signal.read",
    "opportunity.read",
    "risk.read",
    "actor.read",
    "meeting.read",
    "task.read",
    "documents.read",
    "report.read",
    "report.generate",
    "ai.execute",
  ] as string[],
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: { permissions: mocks.permissions },
  }),
}));

import {
  DossierNavigation,
  DossierSubnav,
} from "./product-navigation";

const DOSSIER_ID = "dossier-1";
const BASE = `/app/dossiers/${DOSSIER_ID}`;

const GROUP_DEFAULTS: Record<string, string> = {
  summary: BASE,
  surveillance: `${BASE}/signals`,
  analysis: `${BASE}/actors`,
  decision: `${BASE}/decisions`,
  deliverables: `${BASE}/reports`,
  activity: `${BASE}/activity`,
};

const GROUPS_WITH_SUBNAV = [
  "surveillance",
  "analysis",
  "decision",
  "deliverables",
] as const;

function renderNav(pathname: string) {
  mocks.pathname = pathname;
  return render(
    <>
      <DossierNavigation dossierId={DOSSIER_ID} />
      <DossierSubnav dossierId={DOSSIER_ID} />
    </>,
  );
}

describe("DossierNavigation + DossierSubnav (grouped nav)", () => {
  beforeEach(() => {
    mocks.pathname = BASE;
    mocks.permissions = [
      "dossier.read",
      "signal.read",
      "opportunity.read",
      "risk.read",
      "actor.read",
      "meeting.read",
      "task.read",
      "documents.read",
      "report.read",
      "report.generate",
      "ai.execute",
    ];
  });

  afterEach(cleanup);

  it("pinta los 6 grupos con destino por defecto estable", () => {
    renderNav(BASE);

    for (const [groupId, href] of Object.entries(GROUP_DEFAULTS)) {
      const link = screen.getByTestId(`dossier-nav-${groupId}`);
      expect(link).toHaveAttribute("href", href);
    }
    expect(screen.getByTestId("dossier-nav-summary")).toHaveTextContent(
      "Resumen",
    );
    expect(screen.getByTestId("dossier-nav-surveillance")).toHaveTextContent(
      "Vigilancia",
    );
    expect(screen.getByTestId("dossier-nav-analysis")).toHaveTextContent(
      "Análisis",
    );
    expect(screen.getByTestId("dossier-nav-decision")).toHaveTextContent(
      "Decisión",
    );
    expect(screen.getByTestId("dossier-nav-deliverables")).toHaveTextContent(
      "Entregables",
    );
    expect(screen.getByTestId("dossier-nav-activity")).toHaveTextContent(
      "Actividad",
    );
  });

  it("marca data-active en Vigilancia (no Resumen) en /procurement", () => {
    renderNav(`${BASE}/procurement`);

    expect(screen.getByTestId("dossier-nav-surveillance")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("dossier-nav-summary")).not.toHaveAttribute(
      "data-active",
    );
    for (const id of [
      "analysis",
      "decision",
      "deliverables",
      "activity",
    ] as const) {
      expect(screen.getByTestId(`dossier-nav-${id}`)).not.toHaveAttribute(
        "data-active",
      );
    }
  });

  it("muestra subnav solo en grupos con hermanos", () => {
    // Vigilancia: sí
    const { unmount: u1 } = renderNav(`${BASE}/signals`);
    const subnavSurveillance = screen.getByRole("navigation", {
      name: /Subsecciones de Vigilancia/,
    });
    expect(
      within(subnavSurveillance).getByTestId("dossier-subnav-signals"),
    ).toBeVisible();
    expect(
      within(subnavSurveillance).getByTestId("dossier-subnav-procurement"),
    ).toBeVisible();
    u1();
    cleanup();

    // Resumen: no
    const { unmount: u2 } = renderNav(BASE);
    expect(
      screen.queryByRole("navigation", { name: /Subsecciones/ }),
    ).not.toBeInTheDocument();
    u2();
    cleanup();

    // Actividad: no
    renderNav(`${BASE}/activity`);
    expect(
      screen.queryByRole("navigation", { name: /Subsecciones/ }),
    ).not.toBeInTheDocument();
  });

  it("expone subnav en Análisis, Decisión y Entregables", () => {
    for (const [path, label] of [
      [`${BASE}/actors`, "Análisis"],
      [`${BASE}/decisions`, "Decisión"],
      [`${BASE}/reports`, "Entregables"],
    ] as const) {
      cleanup();
      renderNav(path);
      expect(
        screen.getByRole("navigation", {
          name: `Subsecciones de ${label}`,
        }),
      ).toBeVisible();
    }
  });

  it('mantiene exactamente un aria-current="page" en destino por defecto de grupo multi', () => {
    // Regresión: el href del grupo coincide con el subnav → no debe duplicarse.
    renderNav(`${BASE}/signals`);
    const currents = document.querySelectorAll('[aria-current="page"]');
    expect(currents).toHaveLength(1);
    expect(currents[0]).toHaveAttribute("data-testid", "dossier-subnav-signals");
    // El grupo sigue activo visualmente
    expect(screen.getByTestId("dossier-nav-surveillance")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("dossier-nav-surveillance")).not.toHaveAttribute(
      "aria-current",
    );
  });

  it('mantiene exactamente un aria-current="page" en hijo no-default y en leaf groups', () => {
    cleanup();
    renderNav(`${BASE}/procurement`);
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(
      screen.getByTestId("dossier-subnav-procurement"),
    ).toHaveAttribute("aria-current", "page");

    cleanup();
    renderNav(BASE);
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(screen.getByTestId("dossier-nav-summary")).toHaveAttribute(
      "aria-current",
      "page",
    );

    cleanup();
    renderNav(`${BASE}/activity`);
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(screen.getByTestId("dossier-nav-activity")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("oculta grupos sin permisos y ajusta el default al primer hijo permitido", () => {
    mocks.permissions = [
      "dossier.read",
      "opportunity.read", // no signal.read → default vigilancia = opportunities
      "actor.read",
      "task.read",
      "report.read",
    ];
    renderNav(BASE);

    expect(screen.getByTestId("dossier-nav-surveillance")).toHaveAttribute(
      "href",
      `${BASE}/opportunities`,
    );
    // analysis needs actors (ok) or investigations (dossier.read) or ask
    expect(screen.getByTestId("dossier-nav-analysis")).toBeInTheDocument();
    // without meeting/task for decision? task.read covers decisions
    expect(screen.getByTestId("dossier-nav-decision")).toHaveAttribute(
      "href",
      `${BASE}/decisions`,
    );
  });

  it("documenta los testids de grupos con subnav (contrato estable)", () => {
    renderNav(`${BASE}/signals`);
    for (const id of GROUPS_WITH_SUBNAV) {
      expect(screen.getByTestId(`dossier-nav-${id}`)).toBeInTheDocument();
    }
  });
});
