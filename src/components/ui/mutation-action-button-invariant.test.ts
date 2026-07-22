import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const PROJECT_ROOT = process.cwd();
const SOURCE_ROOT = join(PROJECT_ROOT, "src");

const MUTATING_ONCLICK_HANDLERS = [
  "actOnMonitor",
  "archive",
  "beginPromotion",
  "createBackup",
  "createBriefing",
  "createDraft",
  "deleteHypothesis",
  "deleteSelected",
  "linkEvidence",
  "monitorAction",
  "mutate",
  "patchSearch",
  "performConfirmedAction",
  "publish",
  "reconcileConnection",
  "refreshDigest",
  "reinforceActorRelevance",
  "remove",
  "removeSearch",
  "retry",
  "retryJob",
  "revoke",
  "revokeOthers",
  "reviewStatus",
  "runRound",
  "runSearch",
  "sendFeedback",
  "testConnection",
];

const MUTATING_SUBMIT_HANDLERS = [
  "changePassword",
  "confirmIdentity",
  "create",
  "createConnection",
  "createMonitor",
  "importCandidate",
  "invite",
  "promote",
  "rotate",
  "runRound",
  "save",
  "saveHypothesis",
  "saveSearch",
  "submitLogin",
  "submitNewPassword",
  "submitRestore",
  "requestPasswordReset",
];

const INLINE_MUTATION_CALL = /api\.[\w.]+\.(?:action|archive|cancel|complete|create|createBackup|createDocumentReport|createEvidence|createMonitor|deleteSearch|dismiss|feedback|generate|importCandidate|inviteOwner|patchSearch|pin|promote|publish|read|readAll|reconcile|refreshDigest|remove|restoreBackup|retry|review|rotate|runSearch|setRoles|setStatus|startReport|test|update|updatePreference)\b/;

const PURE_INTERFACE_MARKUP = [
  `<button type="button" onClick={header.column.getToggleSortingHandler()}>Ordenar</button>`,
  `<button className="icon-button bordered" disabled={page <= 1} aria-label="Pagina anterior" onClick={() => setPage((value) => value - 1)}>Anterior</button>`,
  `<button className="vector-secondary" type="button" onClick={() => setConfirmDelete(true)}>Eliminar</button>`,
];

type RawButton = {
  line: number;
  markup: string;
};

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (path.includes(`${join("src", "components", "ui")}${join("", "")}`) && path.endsWith(".test.ts")) {
      return [];
    }
    if (statSync(path).isDirectory()) return tsxFiles(path);
    return path.endsWith(".tsx") ? [path] : [];
  });
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split("\n").length;
}

function rawButtons(source: string): RawButton[] {
  const matches: RawButton[] = [];
  let index = 0;
  while ((index = source.indexOf("<button", index)) !== -1) {
    if (!/\s|>|\/|$/.test(source[index + "<button".length] ?? "")) {
      index += "<button".length;
      continue;
    }
    let quote: '"' | "'" | "`" | null = null;
    let jsxDepth = 0;
    for (let cursor = index + "<button".length; cursor < source.length; cursor += 1) {
      const char = source[cursor];
      if (quote) {
        if (char === quote && source[cursor - 1] !== "\\") quote = null;
        continue;
      }
      if (char === '"' || char === "'" || char === "`") {
        quote = char;
        continue;
      }
      if (char === "{") {
        jsxDepth += 1;
        continue;
      }
      if (char === "}") {
        jsxDepth = Math.max(0, jsxDepth - 1);
        continue;
      }
      if (char === ">" && jsxDepth === 0) {
        matches.push({ line: lineOf(source, index), markup: source.slice(index, cursor + 1) });
        index = cursor + 1;
        break;
      }
    }
    index += 1;
  }
  return matches;
}

function handlerCallPattern(handlers: readonly string[]) {
  return new RegExp(`\\b(?:${handlers.join("|")})\\s*\\(`);
}

function isSubmitForMutatingForm(markup: string, source: string, line: number): boolean {
  const explicitButton = /\btype=["']button["']/.test(markup);
  if (explicitButton) return false;
  const isSubmit = !/\btype=/.test(markup) || /\btype=["']submit["']/.test(markup);
  if (!isSubmit) return false;
  const before = source.split("\n").slice(0, line).join("\n");
  const lastForm = before.lastIndexOf("<form");
  const lastFormClose = before.lastIndexOf("</form>");
  if (lastForm <= lastFormClose) return false;
  return handlerCallPattern(MUTATING_SUBMIT_HANDLERS).test(before.slice(lastForm));
}

function isMutatingRawButton(markup: string, source = "", line = 1): boolean {
  if (INLINE_MUTATION_CALL.test(markup)) return true;
  if (handlerCallPattern(MUTATING_ONCLICK_HANDLERS).test(markup)) return true;
  return isSubmitForMutatingForm(markup, source, line);
}

describe("mutation action button invariant", () => {
  it("exige puerta de hidratacion en botones que disparan mutaciones de backend", () => {
    const offenders = tsxFiles(SOURCE_ROOT).flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return rawButtons(source)
        .filter((button) => isMutatingRawButton(button.markup, source, button.line))
        .map((button) => `${relative(PROJECT_ROOT, file)}:${button.line}`);
    });

    expect(offenders).toEqual([]);
  });

  it("falla si una accion mutante vuelve a button nativo", () => {
    expect(
      isMutatingRawButton(
        `<button className="vector-danger" onClick={() => void deleteSelected()}>Eliminar definitivamente</button>`,
      ),
    ).toBe(true);
  });

  it("no exige puerta en botones de interfaz pura", () => {
    expect(PURE_INTERFACE_MARKUP.map((markup) => isMutatingRawButton(markup))).toEqual([
      false,
      false,
      false,
    ]);
  });
});
