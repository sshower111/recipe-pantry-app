import type { Metadata, Viewport } from "next";
import { DM_Sans, EB_Garamond } from "next/font/google";
import "./globals.css";

const garamond = EB_Garamond({ variable: "--font-garamond", subsets: ["latin"] });
const dmSans = DM_Sans({ variable: "--font-dm-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Cookbook",
  description: "Recipes saved from your cooking reels",
};

export const viewport: Viewport = {
  themeColor: "#faf8f5",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${garamond.variable} ${dmSans.variable}`}>
      <body className="font-sans">{children}</body>
    </html>
  );
}
