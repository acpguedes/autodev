import type { Metadata } from "next";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "AutoDev Architect",
  description: "Chat interface for orchestrating LLM driven development",
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
