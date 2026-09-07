import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JobFit",
  description: "Score and optimise your CV against a job description.",
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
