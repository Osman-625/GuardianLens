// Display formatting shared by the website and the side panel, so both show the same text.

// Malaysian day-first format in Malaysian time. The fixed locale and time zone make every viewer,
// and the server and client renders, agree ("15 Oct 2026, 4:52 am").
const CHECKED_AT = new Intl.DateTimeFormat("en-MY", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kuala_Lumpur",
});

/** Formats an ISO timestamp for display, day first, in Malaysian time, without seconds. */
export function formatDateTime(iso: string): string {
  return CHECKED_AT.format(new Date(iso));
}

/** Upper-cases the first letter only ("main factor: raises risk" -> "Main factor: raises risk"). */
export function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
