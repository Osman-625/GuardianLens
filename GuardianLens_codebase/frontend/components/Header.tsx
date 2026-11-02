// The site header shown on every page: the GuardianLens wordmark (links home), the primary
// navigation with the current page marked, and one call to action. It is a client component only
// so it can read the current path for aria-current.
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, Wordmark } from "@guardianlens/shared";

/** The primary navigation. "Overview" is hidden on narrow screens, where the wordmark is home. */
const LINKS = [
  { href: "/", label: "Overview", narrowHidden: true },
  { href: "/history", label: "This session", narrowHidden: false },
] as const;

/** Renders the site header with the home link and the primary navigation. */
export function Header() {
  const pathname = usePathname();
  return (
    <header className="site-header">
      <div className="header-inner">
        <Link className="wordmark" href="/" aria-label="GuardianLens home">
          <Wordmark />
        </Link>
        <nav aria-label="Primary navigation">
          {LINKS.map(({ href, label, narrowHidden }) => (
            <Link
              key={href}
              href={href}
              className={narrowHidden ? "nav-wide-only" : undefined}
              aria-current={pathname === href ? "page" : undefined}
            >
              {label}
            </Link>
          ))}
        </nav>
        <Link className="button button-dark header-cta" href="/assess">
          Check a listing
          <Icon name="arrow-right" />
        </Link>
      </div>
    </header>
  );
}
