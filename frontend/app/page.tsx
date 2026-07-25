import Link from "next/link";
import { DevBanner } from "@/components/DevBanner";

export default function HomePage() {
  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">Pre-purchase decision support</p>
        <h1>Check a marketplace listing before you pay.</h1>
        <p>
          GuardianLens reviews listing photos, wording, and visible seller details, then explains
          the warning signs it found and what you should verify yourself.
        </p>
        <DevBanner />
        <div className="hero-actions">
          <Link className="button button-primary" href="/assess">Check a listing</Link>
          <a className="button button-secondary" href="#how-it-works">How it works</a>
        </div>
      </section>

      <section id="how-it-works" className="explainer-grid" aria-label="How GuardianLens works">
        <article className="explainer-card">
          <h2>What it checks</h2>
          <p>Photos, listing text, and the seller details that are visible to you.</p>
        </article>
        <article className="explainer-card">
          <h2>What it cannot guarantee</h2>
          <p>A score is a second opinion. It cannot confirm that a seller or listing is safe.</p>
        </article>
        <article className="explainer-card">
          <h2>How data is handled</h2>
          <p>Raw text is scrubbed for contact details before storage. The retention period is still awaiting approval.</p>
        </article>
      </section>

      <Link className="button button-primary button-full" href="/assess">Check a listing</Link>
      <p className="footer-note">Designed for Mudah.my and Carousell product listings in English, Malay, or mixed text.</p>
    </main>
  );
}
