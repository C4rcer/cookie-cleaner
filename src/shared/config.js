// Limits, defaults and the few words shared by the background, the popup and the dashboard.

export const ORIGINS = ["*://*/*"];

export const DEFAULTS = {
  enabled: false,        // automatic cleaning; off until the setup has been finished
  setupDone: false,
  graceSec: 30,          // wait this long after a site's last tab closed
  onNavigate: false,     // also clean a site when its tab moves on to another site
  cleanOpenAtQuit: false, // at Firefox start, clean sites that were open when Firefox closed
};

// What the settings page offers. The background accepts any whole number of
// seconds from 1 to 3600, so the tests can use a short wait.
export const GRACE_CHOICES = [10, 30, 60, 300];
export const GRACE_MIN = 1;
export const GRACE_MAX = 3600;

// After Firefox starts, nothing is cleaned for this long: session restore gets
// time to bring tabs back, and the user can cancel in the popup.
export const STARTUP_DELAY_MS = 60000;

// Deleted cookies are kept in storage.session (memory only) for a restore.
export const RESTORE_MS = 15 * 60000;
export const RESTORE_MAX_BYTES = 4 * 1024 * 1024;
export const RESTORE_MAX_ENTRIES = 500;

export const LOG_MAX = 300;
export const STORES_MAX = 100;   // remembered container cookie stores
export const VISITED_MAX = 300;  // sites remembered per tab

export const KEEP_ALWAYS = "always";
export const KEEP_SESSION = "session";

export function graceLabel(sec) {
  if (sec < 60) return `${sec} seconds`;
  const min = Math.round(sec / 60);
  return min === 1 ? "1 minute" : `${min} minutes`;
}
