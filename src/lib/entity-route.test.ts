import { describe, expect, it } from "vitest";
import { decodeEntityPathName, entityRoute } from "./entity-route";

describe("entityRoute", () => {
  it("puts the entity name in the query string", () => {
    expect(entityRoute("company", "MAGTEL GLOBAL SL")).toBe(
      "/app/actors/entity/company?name=MAGTEL+GLOBAL+SL",
    );
  });

  it("preserves tab and tool extras", () => {
    expect(
      entityRoute("company", "MAGTEL GLOBAL SL", { tab: "patents", tool: "report" }),
    ).toBe("/app/actors/entity/company?name=MAGTEL+GLOBAL+SL&tab=patents&tool=report");
  });
});

describe("decodeEntityPathName", () => {
  it("decodes percent-encoded legacy segments", () => {
    expect(decodeEntityPathName("MAGTEL%20GLOBAL%20SL")).toBe("MAGTEL GLOBAL SL");
  });

  it("rejoins split path parts from proxies that unescaped spaces", () => {
    expect(decodeEntityPathName(["MAGTEL", "GLOBAL", "SL"])).toBe("MAGTEL GLOBAL SL");
  });

  it("accepts plus as space in path segments", () => {
    expect(decodeEntityPathName("MAGTEL+GLOBAL+SL")).toBe("MAGTEL GLOBAL SL");
  });
});
