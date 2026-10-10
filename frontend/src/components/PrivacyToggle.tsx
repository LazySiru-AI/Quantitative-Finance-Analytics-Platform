/**
 * The "hide amounts" switch, in the sidebar beside the language toggle.
 *
 * Every page in this app renders the owner's real money: balances on Overview, positions and cash on
 * Account, realised gains on Tax, disallowed losses on Wash Sales. There was no way to put any of it
 * away for a screen share, a support call, or a desk someone can walk past. This is that switch.
 *
 * **One button with `aria-pressed`, not two.** The state has exactly two values and the control is
 * the state -- the same reading the favourite stars and the language options already give assistive
 * tech. The visible words name the action about to happen ("Hide amounts" while amounts are showing)
 * because a toggle that reads out its own current value leaves "what happens if I click" to be
 * guessed; `aria-pressed` carries the state alongside it.
 *
 * **It writes an attribute, not a prop.** The store sets `data-redact` on `<html>` and `styles.css`
 * blurs from there, so no page has to know this component exists. See `@/privacy` for why the blur
 * lives in CSS and for what that cannot reach.
 *
 * `type="button"` is not decoration: a bare `<button>` defaults to `type="submit"`, and this
 * component is generic enough to end up inside a form eventually.
 */
import { useT } from "@/i18n/useT";
import { usePrivacy } from "@/privacy";

export default function PrivacyToggle() {
  const { t } = useT();
  const { redacted, toggle } = usePrivacy();
  const label = redacted ? t("shell.privacy.off") : t("shell.privacy.on");

  return (
    <div className="privacy-toggle">
      <button
        type="button"
        className={redacted ? "privacy-option is-active" : "privacy-option"}
        aria-pressed={redacted}
        title={label}
        onClick={toggle}
      >
        {label}
      </button>
    </div>
  );
}
