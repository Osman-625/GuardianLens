// Landing page (S1): leads with the browser extension, the main way to use the product, and says
// what GuardianLens checks, what it cannot guarantee, and how data is handled. The manual form
// stays available as the secondary action. It shows no example score: every number on this site
// comes from a real check, so a made-up one would be a false claim.
//
// Install steps describe loading the extension unpacked, because this is a research prototype that
// is not published on a web store. The zip is built with the site (frontend's prebuild script).
import Link from "next/link";
import { Icon, LooksAt } from "@guardianlens/shared";
import { InferenceStatus } from "@/components/InferenceStatus";

// The three steps of using the product, shown under the hero.
const STEPS: ReadonlyArray<{ title: string; text: string }> = [
  {
    title: "Click the icon on a listing",
    text: "GuardianLens reads that one page and shows what it captured. Fix anything that looks wrong.",
  },
  {
    title: "Read the result",
    text: "A score from 0 to 100, where higher is better, with the main factor behind each check.",
  },
  {
    title: "Open the full explanation",
    text: "See every reason, and the steps to take before you pay.",
  },
];

/** Renders the landing page: the pitch, the extension download and install steps, and the notes. */
export default function HomePage() {
  return (
    <main className="page page-wide">
      <section className="hero">
        <div className="hero-copy">
          <h1>Check the listing where you find it.</h1>
          <p className="hero-lead">
            GuardianLens reviews a listing&apos;s photos, wording and seller details, explains any
            warning signs, and tells you what to check before you pay.
          </p>
          <InferenceStatus />
          <div className="hero-actions">
            <a
              className="button button-primary"
              href="/downloads/guardianlens-extension.zip"
              download
            >
              Get the extension
              <Icon name="arrow-right" />
            </a>
            <Link className="button button-secondary" href="/assess">
              Check a listing manually
            </Link>
          </div>
          <p className="hero-note">
            <Icon name="lock" /> No account needed
          </p>
        </div>

        <aside className="card hero-panel" aria-labelledby="looks-heading">
          <h2 id="looks-heading">What it looks at</h2>
          <LooksAt />
          <p className="helper">
            Anything it cannot check is shown as unknown, never as suspicious.
          </p>
        </aside>
      </section>

      <section className="process" aria-labelledby="process-heading">
        <h2 id="process-heading" className="section-title">
          From listing page to result
        </h2>
        {/* role="list" keeps list semantics in Safari, which drops them when list-style is none. */}
        <ol className="steps" role="list">
          {STEPS.map(({ title, text }) => (
            <li key={title}>
              <h3>{title}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="card install-card" aria-labelledby="install-heading">
        <div>
          <h2 id="install-heading">Install the extension</h2>
          <p className="helper">
            It reads a page only when you click its icon, and only that page. This prototype is not
            on a web store, so it is loaded unpacked.
          </p>
        </div>
        <ol className="install-steps">
          <li>Download the zip and unzip it.</li>
          <li>
            Open <code>chrome://extensions</code> (or <code>edge://extensions</code>) and turn on
            Developer mode.
          </li>
          <li>Choose Load unpacked and select the unzipped folder.</li>
          <li>Open a Mudah.my or Carousell listing and click the GuardianLens icon.</li>
        </ol>
      </section>

      <section className="notice scope-banner" aria-label="What GuardianLens cannot do">
        <Icon name="info" />
        <div>
          <strong>What GuardianLens cannot do</strong>
          <p>
            It estimates risk from the signals it can see. It cannot verify who a seller is, confirm
            a sale is genuine, or promise a listing is safe.
          </p>
          <p>
            Contact details are removed from text before it is stored. How long results are kept has
            not been decided yet.
          </p>
        </div>
      </section>

      <p className="footer-note">
        Works on Mudah.my and Carousell product listings in English, Malay or a mix.
      </p>
    </main>
  );
}
