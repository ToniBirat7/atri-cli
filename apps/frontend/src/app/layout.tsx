import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kanoon Box Chat",
  description: "Chat with Gemma 4 via llama.cpp",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
