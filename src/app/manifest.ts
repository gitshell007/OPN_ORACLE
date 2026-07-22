import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "OPN Oracle",
    short_name: "Oracle",
    description: "Inteligencia estratégica trazable para decidir el siguiente movimiento.",
    start_url: "/app",
    display: "standalone",
    background_color: "#0C1440",
    theme_color: "#1C2F8F",
    icons: [
      {
        src: "/brand/opn-oracle-app-icon.png",
        sizes: "1024x1024",
        type: "image/png",
      },
    ],
  };
}
