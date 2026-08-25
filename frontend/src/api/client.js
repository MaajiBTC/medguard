// Thin fetch wrapper: base URL + auth header injection.
//
// Token lives in sessionStorage (not localStorage) to limit the XSS persistence
// window, per the plan's frontend capture wiring notes.

const API_BASE_URL = 'http://localhost:8000/api';
const TOKEN_STORAGE_KEY = 'medguard_token';

function getToken() {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

function setToken(token) {
  if (token) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

/**
 * @param {string} path - API path, e.g. "/access/login/"
 * @param {object} [options]
 * @param {string} [options.method]
 * @param {object} [options.body] - JSON-serializable request body
 * @param {boolean} [options.auth] - attach the Bearer token (default true)
 */
async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' };

  if (auth) {
    const token = getToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const message = (data && data.detail) || `Request failed with status ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

export { API_BASE_URL, getToken, setToken, request };
