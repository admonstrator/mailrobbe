// Whether the welcome note of the first start was shown: kept in this browser, so it appears once.

const STORAGE_KEY = "mailrobbe.welcome";

let fallback = false; // when the browser keeps no storage

export function welcomeSeen(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== null;
  } catch {
    return fallback;
  }
}

export function markWelcomeSeen(): void {
  fallback = true;
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // kept in memory for this page only
  }
}
