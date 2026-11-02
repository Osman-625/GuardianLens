// Manual listing form: the fallback and study entry for a listing that cannot be captured by the
// browser extension (a saved or stored listing, a changed page layout, or a browser the extension
// does not support). It sends `source=manual` so research records can tell the two paths apart.
// Category is FREE TEXT: the 12 categories the models were trained on are only suggestions.
"use client";

import { DragEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, GuardianLensApiError } from "@/lib/api";
import { DRAFT_KEY } from "@/lib/draft";
import { CategoryField, Icon, LIMITS, RETENTION_NOTICE } from "@guardianlens/shared";

// The most photos one check can include (the API setting GUARDIANLENS_MAX_IMAGES).
const MAX_PHOTOS = LIMITS.photos;

// The photo types the API accepts, so a dropped file of any other type can be refused up front.
const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];

/** "a photo", "a photo and a title", "a photo, a title and a price". */
function joinList(items: string[]): string {
  return items.length < 2
    ? items.join("")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** A small preview of a chosen photo, so the buyer can see which file is which. */
function Thumb({ file }: { file: File }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    // Not every environment can make an object URL (the jsdom test one cannot): no preview then.
    if (typeof URL.createObjectURL !== "function") return;
    const url = URL.createObjectURL(file);
    // The URL only exists after render, so it is set here and released when the row goes away.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img className="file-thumb" src={src} alt="" /> : <span className="file-thumb" />;
}

// The seller fields have no message of their own beside them, so their errors are shown next to
// the submit button, led by the field's name.
const SELLER_FIELD_LABELS: Record<string, string> = {
  account_age_days: "Account age in days",
  rating: "Rating",
  review_count: "Review count",
  active_listing_count: "Active listing count",
};

/** True when the form already shows a server error for this field right beside the field. */
function shownBesideField(field: string | null): boolean {
  if (field === null) return false;
  return (
    field.startsWith("images") || ["title", "description", "price", "category"].includes(field)
  );
}

/** The form's values, all held as text exactly as the buyer typed them. */
interface Draft {
  platform: string;
  title: string;
  description: string;
  price: string;
  category: string;
  accountAgeDays: string;
  rating: string;
  reviewCount: string;
  activeListingCount: string;
}

// The form's starting values: Carousell preselected and every other field empty.
const EMPTY_DRAFT: Draft = {
  platform: "carousell",
  title: "",
  description: "",
  price: "",
  category: "",
  accountAgeDays: "",
  rating: "",
  reviewCount: "",
  activeListingCount: "",
};

/** Renders the manual form, keeps its draft, and submits it to the API as a manual check. */
export default function AssessPage() {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<{
    message: string;
    field: string | null;
  } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // True while a file is being dragged over the photo box, so the box can say it will take it.
  const [dragging, setDragging] = useState(false);

  // On first render, bring back the draft saved in this tab's session storage (if it is readable).
  useEffect(() => {
    const stored = window.sessionStorage.getItem(DRAFT_KEY);
    if (stored) {
      try {
        // Restoring a user-authored session draft is intentional here.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setDraft({ ...EMPTY_DRAFT, ...(JSON.parse(stored) as Partial<Draft>) });
      } catch {
        window.sessionStorage.removeItem(DRAFT_KEY);
      }
    }
  }, []);

  // Save the draft after every change, so a reload or a return from the processing page keeps it.
  useEffect(() => {
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [draft]);

  // True when the required parts are present: a photo, a title, a description, a price, a category.
  const mandatoryValid = useMemo(
    () =>
      Boolean(
        files.length &&
        draft.title.trim() &&
        draft.description.trim() &&
        draft.price.trim() &&
        draft.category.trim(),
      ),
    [draft, files.length],
  );
  // Text over an API limit is shown in red and blocks the button, instead of failing after the upload.
  const titleOver = draft.title.trim().length > LIMITS.title;
  const descriptionOver = draft.description.trim().length > LIMITS.description;
  const canSubmit = mandatoryValid && !titleOver && !descriptionOver;
  // What the button is waiting for, said in words next to it (Design Brief 3.4: a disabled button
  // explains why).
  const missing = [
    !files.length && "a photo",
    !draft.title.trim() && "a title",
    !draft.description.trim() && "a description",
    !draft.price.trim() && "a price",
    !draft.category.trim() && "a category",
  ].filter((item): item is string => Boolean(item));

  // Stores one edited field and clears the server error that was shown for that field.
  function update(field: keyof Draft, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
    if (error?.field === field) setError(null);
  }

  // Adds newly chosen or dropped photos to the list, keeping the first MAX_PHOTOS and saying so if
  // some were left out. Files that are not JPEG, PNG or WebP are refused here, not after the upload.
  function addFiles(selected: FileList | null) {
    if (!selected) return;
    setError(null);
    const dropped = Array.from(selected);
    const incoming = dropped.filter((file) => PHOTO_TYPES.includes(file.type));
    const combined = [...files, ...incoming].slice(0, MAX_PHOTOS);
    setFiles(combined);
    if (files.length + incoming.length > MAX_PHOTOS) {
      setError({
        message: `Add no more than ${MAX_PHOTOS} images.`,
        field: "images",
      });
    } else if (incoming.length < dropped.length) {
      setError({ message: "Only JPEG, PNG, or WebP photos can be added.", field: "images" });
    }
  }

  // Lets the whole photo box take a dropped file, not only the file button inside it.
  function dropFiles(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  }

  // Sends the form as multipart data; on success opens the processing page, on failure shows the
  // API's message beside the field it names (or a general message when the API cannot be reached).
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    setError(null);
    const body = new FormData();
    files.forEach((file) => body.append("images", file));
    body.append("platform", draft.platform);
    body.append("title", draft.title);
    body.append("description", draft.description);
    body.append("price", draft.price);
    body.append("category", draft.category.trim());
    // Tells the API that this listing was typed in, not captured.
    body.append("source", "manual");
    body.append("account_age_days", draft.accountAgeDays);
    body.append("rating", draft.rating);
    body.append("review_count", draft.reviewCount);
    body.append("active_listing_count", draft.activeListingCount);

    try {
      const accepted = await apiFetch<{ assessment_id: string }>("/api/v1/assess", {
        method: "POST",
        body,
      });
      router.push(`/assess/${accepted.assessment_id}/processing`);
    } catch (caught) {
      if (caught instanceof GuardianLensApiError) {
        setError({ message: caught.message, field: caught.field });
      } else {
        setError({
          message:
            "The GuardianLens service could not be reached. Try again, or ask the researcher.",
          field: null,
        });
      }
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <h1 className="page-title">Check a listing</h1>
      <p className="page-lead">
        Copy the details exactly as they appear. Photos, title, description, price and category are
        required.
      </p>

      <form className="form-stack" onSubmit={submit} noValidate>
        <section className="form-section">
          <h2>Listing photos</h2>
          {/* A label around the file input makes the whole box a tap target. The input itself is
              visually hidden but stays focusable, so the box shows the focus ring (styles). */}
          <label
            className={dragging ? "uploader is-dragging" : "uploader"}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={dropFiles}
          >
            <input
              className="visually-hidden"
              aria-label="Choose listing photos"
              type="file"
              accept={PHOTO_TYPES.join(",")}
              multiple
              onChange={(event) => {
                addFiles(event.target.files);
                // Cleared so choosing the same photo again, after removing it, still registers.
                event.target.value = "";
              }}
            />
            <span className="uploader-icon">
              <Icon name="upload" />
            </span>
            <strong>Add 1 to {MAX_PHOTOS} photos</strong>
            <span className="helper">
              Drop photos here, or tap to choose. JPEG, PNG, or WebP, up to 5 MB each.
            </span>
          </label>
          {files.length > 0 && (
            <ul className="file-list" aria-label="Selected files">
              {files.map((file, index) => (
                <li className="file-row" key={`${file.name}-${file.lastModified}-${index}`}>
                  <Thumb file={file} />
                  <span className="file-name">
                    <span className="file-title">{file.name}</span>
                    <span className="file-size">{Math.ceil(file.size / 1024)} KB</span>
                  </span>
                  <button
                    className="button button-text"
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    onClick={() =>
                      setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))
                    }
                  >
                    <Icon name="x" />
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          {error?.field?.startsWith("images") && <p className="error-text">{error.message}</p>}
        </section>

        <section className="form-section">
          <h2>Listing details</h2>
          <div className="field-row">
            <div className="field">
              <label htmlFor="platform">Marketplace</label>
              <select
                id="platform"
                value={draft.platform}
                onChange={(event) => update("platform", event.target.value)}
              >
                <option value="carousell">Carousell</option>
                <option value="mudah">Mudah.my</option>
              </select>
            </div>
            <CategoryField
              id="category"
              value={draft.category}
              onChange={(value) => update("category", value)}
              error={error?.field === "category" ? error.message : null}
            />
          </div>
          <div className="field">
            <label htmlFor="title">Title</label>
            <input
              id="title"
              value={draft.title}
              onChange={(event) => update("title", event.target.value)}
              placeholder="Copy the title exactly as shown"
            />
            <span className={`char-count ${titleOver ? "error-text" : ""}`.trim()}>
              {draft.title.trim().length}/{LIMITS.title}
            </span>
            {titleOver && (
              <span className="error-text">Use {LIMITS.title} characters or fewer.</span>
            )}
            {error?.field === "title" && <span className="error-text">{error.message}</span>}
          </div>
          <div className="field">
            <label htmlFor="description">Description</label>
            <textarea
              id="description"
              value={draft.description}
              onChange={(event) => update("description", event.target.value)}
              placeholder="Paste the listing description"
            />
            <span className={`char-count ${descriptionOver ? "error-text" : ""}`.trim()}>
              {draft.description.trim().length}/{LIMITS.description}
            </span>
            {descriptionOver && (
              <span className="error-text">Use {LIMITS.description} characters or fewer.</span>
            )}
            {error?.field === "description" && <span className="error-text">{error.message}</span>}
          </div>
          <div className="field">
            <label htmlFor="price">Price</label>
            <input
              id="price"
              inputMode="decimal"
              value={draft.price}
              onChange={(event) => update("price", event.target.value)}
              placeholder="RM 1,250"
            />
            {error?.field === "price" && <span className="error-text">{error.message}</span>}
          </div>

          {/* Open by default: the behavioural signal is built from these details, so they are
              recommended. They still never block the check. */}
          <details className="optional" open>
            <summary>Seller details (recommended)</summary>
            <p className="helper">
              Copy what the seller&apos;s profile shows. Leave the rest blank: missing details count
              as unknown, not as suspicious.
            </p>
            <div className="field-row">
              <div className="field">
                <label htmlFor="account-age">Account age in days</label>
                <input
                  id="account-age"
                  inputMode="numeric"
                  value={draft.accountAgeDays}
                  onChange={(event) => update("accountAgeDays", event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="rating">Rating out of 5</label>
                <input
                  id="rating"
                  inputMode="decimal"
                  value={draft.rating}
                  onChange={(event) => update("rating", event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="review-count">Review count</label>
                <input
                  id="review-count"
                  inputMode="numeric"
                  value={draft.reviewCount}
                  onChange={(event) => update("reviewCount", event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="active-listings">Active listing count</label>
                <input
                  id="active-listings"
                  inputMode="numeric"
                  value={draft.activeListingCount}
                  onChange={(event) => update("activeListingCount", event.target.value)}
                />
              </div>
            </div>
          </details>
        </section>

        <div className="submit-bar">
          <p className="retention">{RETENTION_NOTICE}</p>
          {!canSubmit && !error && (
            <p className="helper submit-help" id="submit-help">
              {missing.length > 0
                ? `Still needed: ${joinList(missing)}.`
                : "Shorten the text marked in red to continue."}
            </p>
          )}
          {error && !shownBesideField(error.field) && (
            <p className="error-text" role="alert">
              {error.field && SELLER_FIELD_LABELS[error.field]
                ? `${SELLER_FIELD_LABELS[error.field]}: ${error.message}`
                : error.message}
            </p>
          )}
          <button
            className="button button-primary button-full"
            type="submit"
            disabled={!canSubmit || submitting}
            aria-describedby={!canSubmit && !error ? "submit-help" : undefined}
          >
            {submitting ? "Checking…" : "Check listing"}
          </button>
        </div>
      </form>
    </main>
  );
}
