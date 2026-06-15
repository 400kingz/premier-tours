import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Shell } from "@/components/shell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "Premier Home Tours",
  description: "Cinematic AI drone flythroughs from listing photos.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} font-sans antialiased`}>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
