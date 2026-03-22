import type { Metadata } from "next";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "AutoDev Architect",
  description: "Execution control center for configuring and orchestrating AutoDev Architect",
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
