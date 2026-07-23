import type { Metadata } from "next";
import { Toaster } from "sonner";
import { AuthProvider } from "@/components/auth/auth-provider";
import { RecentAuthProvider } from "@/components/auth/recent-auth";
import "./globals.css";
import "@/styles/auth.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://oracle.opnconsultoria.com"),
  title: {
    default: "OPN Oracle",
    template: "%s · OPN Oracle",
  },
  description: "Inteligencia estratégica trazable para decidir el siguiente movimiento.",
  openGraph: {
    type: "website",
    locale: "es_ES",
    url: "/",
    siteName: "OPN Oracle",
    title: "OPN Oracle",
    description: "Inteligencia estratégica trazable para decidir el siguiente movimiento.",
    images: [
      {
        url: "/brand/opn-oracle-social-card.png",
        width: 1200,
        height: 630,
        alt: "OPN Oracle, inteligencia estratégica trazable",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "OPN Oracle",
    description: "Inteligencia estratégica trazable para decidir el siguiente movimiento.",
    images: ["/brand/opn-oracle-social-card.png"],
  },
  icons: {
    icon: "/brand/opn-oracle-favicon.png",
    apple: "/brand/opn-oracle-app-icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" data-scroll-behavior="smooth">
      <body>
        <AuthProvider>
          <RecentAuthProvider>
            {children}
          </RecentAuthProvider>
        </AuthProvider>
        <Toaster position="bottom-right" richColors closeButton />
      </body>
    </html>
  );
}
