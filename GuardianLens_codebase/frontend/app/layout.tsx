// Root layout: loads the shared design styles first, then the website's own page styles, and wraps
// every page in the site header and footer. The shared stylesheet holds the design tokens and the
// styles of the shared components (also used by the browser extension's side panel).
import type { Metadata } from "next";
import "@guardianlens/shared/styles.css";
import { Header } from "@/components/Header";
import "./globals.css";

/** The page title and description that browsers and search engines show for the site. */
export const metadata: Metadata = {
  title: "GuardianLens",
  description: "Check a Mudah.my or Carousell listing for warning signs before you pay.",
};

/** Wraps every page in the HTML shell with the site header above and the footer below. */
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: browser extensions add attributes to <html> before React loads, which
    // would otherwise log a hydration mismatch in development. It applies to this one element only.
    <html lang="en" suppressHydrationWarning>
      <body>
        <Header />
        {children}
        <footer className="site-footer">
          <div className="header-inner">
            <span>GuardianLens · Risk checks for marketplace buyers</span>
            <span>Student research prototype</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
