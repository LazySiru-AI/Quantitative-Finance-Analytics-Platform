/**
 * The account page: change your own password, or sign out.
 *
 * Routed at `/account` and reachable from the sidebar footer, but deliberately *not* in `nav.ts` --
 * it is not one of the dashboard's data pages and has no place in the section rail. Signing out
 * flips the provider to `anonymous`, at which point `App` swaps the whole tree for the login screen,
 * so there is nothing to navigate to here.
 */

import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ChangePasswordError, changePassword } from "@/api/auth";
import { useT } from "@/i18n";
import { useAuth } from "@/auth";

export default function Account() {
  const { t } = useT();
  const { username, authEnabled, signOut } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setDone(false);
    if (next !== confirm) {
      setError(t("auth.account.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      if (err instanceof ChangePasswordError && err.kind === "too_short") {
        setError(t("auth.account.tooShort"));
      } else if (err instanceof ChangePasswordError && err.kind === "invalid_credentials") {
        setError(t("auth.account.wrongCurrent"));
      } else {
        setError(t("auth.account.error"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="account-page">
      <h1>{t("shell.profile.label")}</h1>
      <p className="subtitle">{t("shell.profile.blurb")}</p>
      {username !== null && (
        <p className="subtitle">{t("auth.account.signedInAs", { username })}</p>
      )}

      {authEnabled && (
        <form className="panel account-form" onSubmit={onSubmit}>
          <h2 className="account-section-heading">{t("auth.account.changePassword")}</h2>

          <label className="login-field">
            <span>{t("auth.account.current")}</span>
            <input
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </label>
          <label className="login-field">
            <span>{t("auth.account.new")}</span>
            <input
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
          </label>
          <label className="login-field">
            <span>{t("auth.account.confirm")}</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </label>

          {error !== null && (
            <p className="callout callout-danger login-error" role="alert">
              {error}
            </p>
          )}
          {done && (
            <p className="callout account-saved" role="status">
              {t("auth.account.saved")}
            </p>
          )}

          <button type="submit" className="login-submit" disabled={busy}>
            {busy ? t("auth.account.saving") : t("auth.account.save")}
          </button>
        </form>
      )}

      <div className="account-actions">
        <button type="button" className="account-signout" onClick={() => void signOut()}>
          {t("auth.footer.signOut")}
        </button>
        <Link to="/overview" className="account-back">
          {t("auth.account.back")}
        </Link>
      </div>
    </div>
  );
}
