/* Tiny fetch wrapper for the bib API. */
"use strict";

export async function apiGet(path, params = {}) {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  const response = await fetch(url);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json();
}

export function apiUrl(path, params = {}) {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Decode a base64 uint8 payload into a Uint8Array. */
export function decodeB64U8(b64) {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/** Toast-ish error reporting: writes into an element if present, else console. */
export function reportError(err, hostId = "error-box") {
  const host = document.getElementById(hostId);
  console.error(err);
  if (host) {
    host.textContent = String(err.message || err);
    host.hidden = false;
    setTimeout(() => (host.hidden = true), 8000);
  }
}
