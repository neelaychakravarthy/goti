// Stub auth for the hackathon demo — single cookie, no real session.
// Redirect target for unauthenticated users is /start (the product intro page).

export const GOTI_SESSION_COOKIE = "goti_demo_session";
export const GOTI_SESSION_VALUE = "1";
export const GOTI_SESSION_MAX_AGE = 60 * 60 * 24; // 24h
export const GOTI_UNAUTH_REDIRECT = "/start";
