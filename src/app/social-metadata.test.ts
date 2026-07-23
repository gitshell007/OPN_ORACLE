import { describe, expect, it } from "vitest";
import { metadata as productMetadata } from "@/app/app/layout";
import { metadata as rootMetadata } from "@/app/layout";

describe("metadata social de Oracle", () => {
  it("publica una tarjeta horizontal y evita duplicar el nombre en la app", () => {
    expect(rootMetadata.metadataBase?.toString()).toBe("https://oracle.opnconsultoria.com/");
    expect(rootMetadata.openGraph).toMatchObject({
      title: "OPN Oracle",
      siteName: "OPN Oracle",
      images: [
        {
          url: "/brand/opn-oracle-social-card.png",
          width: 1200,
          height: 630,
          alt: "OPN Oracle, inteligencia estratégica trazable",
        },
      ],
    });
    expect(rootMetadata.twitter).toMatchObject({
      card: "summary_large_image",
      title: "OPN Oracle",
      images: ["/brand/opn-oracle-social-card.png"],
    });
    expect(productMetadata.title).toEqual({ absolute: "OPN Oracle" });
  });
});
