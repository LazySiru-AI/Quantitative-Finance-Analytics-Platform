/**
 * The full-screen sign-in gate.
 *
 * Rendered by `App` in place of the entire dashboard whenever the auth state is `anonymous`, so
 * there is no sidebar and no route here -- a signed-out user sees only this. On success it does not
 * navigate; it calls `onSignedIn`, which flips the provider to `authed` and lets `App` render the
 * real tree at whatever URL the browser is already on.
 *
 * The error copy is deliberately generic ("incorrect username or password") -- see
 * `backend/app/api/auth.py` on why login and unknown-user must be indistinguishable. The one
 * specific message is the lockout, which tells the user how long to wait rather than leaving them
 * guessing why a correct password stopped working.
 */

import { useState, type FormEvent } from "react";

import { LoginError, login } from "@/api/auth";
import LanguageToggle from "@/components/LanguageToggle";
import { useT } from "@/i18n";
import { useAuth } from "@/auth";

export default function Login() {
  const { t } = useT();
  const { onSignedIn, expired } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await login(username, password);
      onSignedIn(result.username);
    } catch (err) {
      if (err instanceof LoginError) {
        if (err.kind === "locked") {
          setError(t("auth.login.locked", { seconds: err.retryAfterSeconds ?? 0 }));
        } else if (err.kind === "invalid_credentials") {
          setError(t("auth.login.invalid"));
        } else {
          setError(t("auth.login.error"));
        }
      } else {
        setError(t("auth.login.error"));
      }
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-lang">
        <LanguageToggle />
      </div>
      <form className="login-card panel" onSubmit={onSubmit}>
        <div className="login-brand">{t("auth.login.subtitle")}</div>
        <h1 className="login-title">{t("auth.login.title")}</h1>

        {/* Only after a session that was signed in expired under the user (`@/auth`'s `expired`) --
            never on a first visit, where "you were signed out" would be a lie. `role="status"`, not
            `alert`: nothing failed and nothing needs correcting, so it should not interrupt the
            reader the way the credential error below deliberately does. */}
        {expired === true && (
          <p className="callout callout-warn login-expired" role="status">
            {t("auth.login.expired")}
          </p>
        )}

        <label className="login-field">
          <span>{t("auth.login.username")}</span>
          <input
            type="text"
            name="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>

        <label className="login-field">
          <span>{t("auth.login.password")}</span>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error !== null && (
          <p className="callout callout-danger login-error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="login-submit" disabled={busy}>
          {busy ? t("auth.login.submitting") : t("auth.login.submit")}
        </button>
      </form>
    </div>
  );
}
