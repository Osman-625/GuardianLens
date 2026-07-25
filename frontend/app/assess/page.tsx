"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, GuardianLensApiError } from "@/lib/api";

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

const categories = ["Electronics", "Phones and tablets", "Fashion", "Home and living", "Hobbies and games"];

export default function AssessPage() {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<{ message: string; field: string | null } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const stored = window.sessionStorage.getItem("guardianlens-draft");
    if (stored) {
      try {
        // Restoring a user-authored session draft is intentional here.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setDraft({ ...EMPTY_DRAFT, ...(JSON.parse(stored) as Partial<Draft>) });
      } catch {
        window.sessionStorage.removeItem("guardianlens-draft");
      }
    }
  }, []);

  useEffect(() => {
    window.sessionStorage.setItem("guardianlens-draft", JSON.stringify(draft));
  }, [draft]);

  const mandatoryValid = useMemo(
    () => Boolean(files.length && draft.title.trim() && draft.description.trim() && draft.price.trim() && draft.category),
    [draft, files.length],
  );

  function update(field: keyof Draft, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
    if (error?.field === field) setError(null);
  }

  function addFiles(selected: FileList | null) {
    if (!selected) return;
    setError(null);
    const incoming = Array.from(selected);
    const combined = [...files, ...incoming].slice(0, 3);
    setFiles(combined);
    if (files.length + incoming.length > 3) {
      setError({ message: "Add no more than 3 images in this first draft.", field: "images" });
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mandatoryValid || submitting) return;
    setSubmitting(true);
    setError(null);
    const body = new FormData();
    files.forEach((file) => body.append("images", file));
    body.append("platform", draft.platform);
    body.append("title", draft.title);
    body.append("description", draft.description);
    body.append("price", draft.price);
    body.append("category", draft.category);
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
        setError({ message: "The API could not be reached. Confirm that FastAPI is running on port 8000.", field: null });
      }
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <p className="eyebrow">Listing submission</p>
      <h1 className="page-title">Check a listing</h1>
      <p className="page-lead">Copy the details exactly as they appear. Seller information is optional.</p>

      <form className="form-stack" onSubmit={submit} noValidate>
        <section className="form-section">
          <h2>Listing photos</h2>
          <div className="uploader">
            <div>
              <strong>Add 1 to 3 photos</strong>
              <p className="helper">JPEG, PNG, or WebP. Maximum 5 MB each.</p>
              <input
                aria-label="Choose listing photos"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                onChange={(event) => addFiles(event.target.files)}
              />
            </div>
          </div>
          {files.length > 0 && (
            <ul className="file-list" aria-label="Selected files">
              {files.map((file, index) => (
                <li className="file-row" key={`${file.name}-${file.lastModified}`}>
                  <span className="file-name">{file.name} ({Math.ceil(file.size / 1024)} KB)</span>
                  <button className="button button-text" type="button" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}>
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
              <select id="platform" value={draft.platform} onChange={(event) => update("platform", event.target.value)}>
                <option value="carousell">Carousell</option>
                <option value="mudah">Mudah.my</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="category">Category</label>
              <select id="category" value={draft.category} onChange={(event) => update("category", event.target.value)} aria-describedby={error?.field === "category" ? "category-error" : undefined}>
                <option value="">Choose a category</option>
                {categories.map((category) => <option key={category}>{category}</option>)}
              </select>
              {error?.field === "category" && <span id="category-error" className="error-text">{error.message}</span>}
            </div>
          </div>
          <div className="field">
            <label htmlFor="title">Title</label>
            <input id="title" maxLength={180} value={draft.title} onChange={(event) => update("title", event.target.value)} placeholder="Copy the title exactly as shown" />
            <span className="char-count">{draft.title.length}/180</span>
            {error?.field === "title" && <span className="error-text">{error.message}</span>}
          </div>
          <div className="field">
            <label htmlFor="description">Description</label>
            <textarea id="description" maxLength={5000} value={draft.description} onChange={(event) => update("description", event.target.value)} placeholder="Paste the listing description" />
            <span className="char-count">{draft.description.length}/5000</span>
            {error?.field === "description" && <span className="error-text">{error.message}</span>}
          </div>
          <div className="field">
            <label htmlFor="price">Price</label>
            <input id="price" inputMode="decimal" value={draft.price} onChange={(event) => update("price", event.target.value)} placeholder="RM 1,250" />
            {error?.field === "price" && <span className="error-text">{error.message}</span>}
          </div>

          <details className="optional">
            <summary>Seller information (optional)</summary>
            <p className="helper">Leave fields blank when they are not visible. Missing details are treated as unknown, never as suspicious.</p>
            <div className="field-row">
              <div className="field">
                <label htmlFor="account-age">Account age in days</label>
                <input id="account-age" inputMode="numeric" value={draft.accountAgeDays} onChange={(event) => update("accountAgeDays", event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="rating">Rating out of 5</label>
                <input id="rating" inputMode="decimal" value={draft.rating} onChange={(event) => update("rating", event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="review-count">Review count</label>
                <input id="review-count" inputMode="numeric" value={draft.reviewCount} onChange={(event) => update("reviewCount", event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="active-listings">Active listing count</label>
                <input id="active-listings" inputMode="numeric" value={draft.activeListingCount} onChange={(event) => update("activeListingCount", event.target.value)} />
              </div>
            </div>
          </details>
        </section>

        <div className="submit-bar">
          <p className="retention">Raw uploaded text is scrubbed before storage. The exact retention period remains an open supervisor item and must be filled before the user study.</p>
          {error && !error.field && <p className="error-text" role="alert">{error.message}</p>}
          <button className="button button-primary button-full" type="submit" disabled={!mandatoryValid || submitting}>
            {submitting ? "Submitting…" : "Assess listing"}
          </button>
        </div>
      </form>
    </main>
  );
}
