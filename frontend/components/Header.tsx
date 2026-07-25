import Link from "next/link";

export function Header() {
  return (
    <header className="site-header">
      <div className="header-inner">
        <Link className="wordmark" href="/" aria-label="GuardianLens home">
          <span className="lens-mark" aria-hidden="true" />
          GuardianLens
        </Link>
        <nav aria-label="Primary navigation">
          <Link href="/history">This session</Link>
        </nav>
      </div>
    </header>
  );
}
