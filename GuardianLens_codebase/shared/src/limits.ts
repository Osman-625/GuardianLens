// The API's input limits, kept in one place for the website form and the extension's Review step.
// They mirror the defaults in api/settings.py (title, description, category, max images); change
// both together. Text over a limit is reported to the buyer, never cut.
export const LIMITS = {
  title: 500,
  description: 5000,
  category: 80,
  photos: 10,
} as const;
