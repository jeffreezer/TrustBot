import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TrustBot",
  description: "Evidence-backed AI security questionnaire responder",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
