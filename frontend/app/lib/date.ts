/**
 * SQLite writes ISO timestamps without a timezone suffix (UTC by convention).
 * The browser's Date constructor treats those as local time, which drifts the
 * displayed value from what the server actually recorded. Append 'Z' to force
 * a UTC parse.
 */
export function formatDate(iso: string, includeTime = false): string {
  const normalised = iso.endsWith("Z") ? iso : `${iso}Z`;
  const date = new Date(normalised);
  if (Number.isNaN(date.getTime())) return iso;
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
  };
  if (includeTime) {
    options.hour = "2-digit";
    options.minute = "2-digit";
  }
  return date.toLocaleString(undefined, options);
}
