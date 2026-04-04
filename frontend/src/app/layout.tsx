import type { Metadata } from "next";
import { Orbitron, Rajdhani, Share_Tech_Mono } from "next/font/google";
import "./globals.css";

const orbitron = Orbitron({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["500", "700", "800"],
});

const rajdhani = Rajdhani({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const shareTechMono = Share_Tech_Mono({
  variable: "--font-mono-custom",
  subsets: ["latin"],
  weight: ["400"],
});

export const metadata: Metadata = {
  title: "AEGIS Command Center",
  description: "Adaptive cyber defense mission interface",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${orbitron.variable} ${rajdhani.variable} ${shareTechMono.variable} h-full antialiased`}
    >
      <body className="min-h-full font-sans">{children}</body>
    </html>
  );
}
