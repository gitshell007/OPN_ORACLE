import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderInlineEmphasis, stripInlineEmphasis } from "./inline-emphasis";

describe("inline-emphasis", () => {
  it("renderiza **negrita** como strong y strip quita asteriscos", () => {
    const { container } = render(<>{renderInlineEmphasis("propuesta **GO CONDICIONADO** ok")}</>);
    expect(container.textContent).toBe("propuesta GO CONDICIONADO ok");
    expect(container.querySelector("strong")?.textContent).toBe("GO CONDICIONADO");
    expect(stripInlineEmphasis("perfil **no** declara")).toBe("perfil no declara");
  });

  it("texto sin markdown se deja igual", () => {
    const { container } = render(<>{renderInlineEmphasis("sin énfasis")}</>);
    expect(container.textContent).toBe("sin énfasis");
    expect(container.querySelector("strong")).toBeNull();
  });
});
