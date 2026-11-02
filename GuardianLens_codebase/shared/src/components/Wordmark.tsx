// The product mark: a lens ring with one arc filled, the same shape as the score dial, then the
// name with "Lens" in the accent colour. Both the website header and the side panel header render
// it, so the brand reads the same.

/** Renders the ring and the name. The caller supplies the wrapping link or element. */
export function Wordmark() {
  return (
    <>
      <svg
        className="logo-mark"
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="16" cy="16" r="12" stroke="currentColor" strokeWidth="3" opacity="0.18" />
        <path
          d="M16 4a12 12 0 0 1 12 12"
          stroke="var(--color-primary)"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          d="M28 16a12 12 0 0 1-12 12"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <circle cx="16" cy="16" r="3.5" fill="currentColor" />
      </svg>
      <span>
        Guardian<span className="wordmark-lens">Lens</span>
      </span>
    </>
  );
}
