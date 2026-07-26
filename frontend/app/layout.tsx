import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Decision Council",
  description: "A multi-model AI council for high-quality decisions",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="container">
          <div className="topbar">
            <h1>
              <Link href="/">Decision Council</Link>
            </h1>
            <span className="tagline">Independent advisors. One accountable decision.</span>
          </div>
          {children}
        </div>
      </body>
    </html>
  );
}
