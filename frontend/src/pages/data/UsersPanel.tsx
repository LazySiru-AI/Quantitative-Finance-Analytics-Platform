/**
 * User administration: list, create, disable/enable, reset password, revoke sessions, change role.
 *
 * Talks to `usersApi` (`@/api/users`), the client for the pinned `/api/users*` contract. Entering a
 * password here is the operator's own deliberate action on this admin surface -- not a case of this
 * app asking a user to type someone else's secret into a form it does not own, which is what the
 * "never enter credentials" rule in this project's tool-safety policy actually guards against.
 *
 * `ConfirmSheet` gates Disable and Revoke sessions -- the two actions that end someone's access
 * without asking them first. Enable and Reset password do not: enabling only restores a state the
 * operator already chose once, and a reset already requires typing a whole new password, which is
 * confirmation enough of intent. Make owner/Make member (`doSetRole`) also skip it, for the same
 * reason Enable does -- a role change does not end anyone's access -- but the server can still
 * refuse one (409 `last_owner`, demoting the application's only owner), which is rendered as its own
 * readable toast rather than the generic action-failed one.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiRequestError, describeError } from "@/api/client";
import { usersApi, type AdminUser, type UserRole } from "@/api/users";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import StatusPill from "@/components/StatusPill";
import { useT } from "@/i18n";

import type { ToastPusher } from "./types";

type Phase = "loading" | "ready" | "error";
type Confirming = { kind: "disable" | "revoke"; username: string } | null;

export default function UsersPanel({ onToast }: { onToast: ToastPusher }) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [busyUser, setBusyUser] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Confirming>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("member");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [resetTarget, setResetTarget] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) => {
      usersApi
        .list(signal)
        .then((result) => {
          setUsers(result.users);
          setPhase("ready");
        })
        .catch((error: unknown) => {
          if (signal?.aborted) return;
          setMessage(describeError(error, t("data.users.error.generic")));
          setPhase("error");
        });
    },
    [t],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function submitCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      const created = await usersApi.create(newUsername.trim(), newPassword, newRole);
      setUsers((prev) => [...prev, created]);
      setNewUsername("");
      setNewPassword("");
      setNewRole("member");
      onToast({ message: t("data.users.create.successToast", { username: created.username }), tone: "ok" });
    } catch (error: unknown) {
      setCreateError(describeError(error, t("data.users.create.error.generic")));
    } finally {
      setCreating(false);
    }
  }

  /**
   * Promotes or demotes `username`. The one action-error case worth its own copy: the server
   * refuses to demote the application's last owner (409 `{"detail": "last_owner"}`), and that
   * refusal is reachable from a normal click, not a broken state -- so it gets a specific, readable
   * toast rather than "that action did not go through".
   */
  async function doSetRole(username: string, role: UserRole) {
    setBusyUser(username);
    try {
      const result = await usersApi.setRole(username, role);
      setUsers((prev) => prev.map((u) => (u.username === username ? { ...u, role: result.role } : u)));
      onToast({
        message: t(role === "owner" ? "data.users.role.makeOwnerToast" : "data.users.role.makeMemberToast", {
          username,
        }),
        tone: "ok",
      });
    } catch (error: unknown) {
      const message =
        error instanceof ApiRequestError && error.message === "last_owner"
          ? t("data.users.role.lastOwnerError", { username })
          : describeError(error, t("data.users.action.error.generic"));
      onToast({ message, tone: "bad" });
    } finally {
      setBusyUser(null);
    }
  }

  async function doEnable(username: string) {
    setBusyUser(username);
    try {
      const result = await usersApi.enable(username);
      setUsers((prev) => prev.map((u) => (u.username === username ? { ...u, disabled: result.disabled } : u)));
      onToast({ message: t("data.users.action.enabledToast", { username }), tone: "ok" });
    } catch (error: unknown) {
      onToast({ message: describeError(error, t("data.users.action.error.generic")), tone: "bad" });
    } finally {
      setBusyUser(null);
    }
  }

  async function runConfirmed() {
    if (!confirming) return;
    const { kind, username } = confirming;
    setConfirmBusy(true);
    try {
      if (kind === "disable") {
        const result = await usersApi.disable(username);
        setUsers((prev) => prev.map((u) => (u.username === username ? { ...u, disabled: result.disabled } : u)));
        onToast({ message: t("data.users.action.disabledToast", { username }), tone: "ok" });
      } else {
        const result = await usersApi.revokeSessions(username);
        onToast({
          message: t(
            result.revoked === 1 ? "data.users.action.revokedToast_one" : "data.users.action.revokedToast_other",
            { count: result.revoked, username },
          ),
          tone: "ok",
        });
      }
    } catch (error: unknown) {
      onToast({ message: describeError(error, t("data.users.action.error.generic")), tone: "bad" });
    } finally {
      setConfirmBusy(false);
      setConfirming(null);
    }
  }

  function openResetPassword(username: string) {
    setResetTarget(username);
    setResetPassword("");
    setResetError(null);
  }

  async function submitResetPassword(event: FormEvent) {
    event.preventDefault();
    if (!resetTarget) return;
    setResetting(true);
    setResetError(null);
    try {
      await usersApi.setPassword(resetTarget, resetPassword);
      onToast({ message: t("data.users.resetPassword.successToast", { username: resetTarget }), tone: "ok" });
      setResetTarget(null);
      setResetPassword("");
    } catch (error: unknown) {
      setResetError(describeError(error, t("data.users.resetPassword.error.generic")));
    } finally {
      setResetting(false);
    }
  }

  return (
    <section className="panel">
      <h2>{t("data.users.heading")}</h2>
      <p className="subtitle">{t("data.users.subtitle")}</p>

      {phase === "loading" && <div className="placeholder">{t("data.users.loading")}</div>}
      {phase === "error" && <div className="placeholder">{message}</div>}

      {phase === "ready" && (
        <>
          {users.length === 0 ? (
            <div className="placeholder">{t("data.users.empty")}</div>
          ) : (
            <div className="table-wrap">
              <table className="data-table" data-testid="users-table">
                <thead>
                  <tr>
                    <th scope="col">{t("data.users.table.username")}</th>
                    <th scope="col">{t("data.users.table.role")}</th>
                    <th scope="col">{t("common.status")}</th>
                    <th scope="col">{t("data.users.table.created")}</th>
                    <th scope="col">{t("common.action")}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => {
                    const rowBusy = busyUser === user.username;
                    return (
                      <tr key={user.username}>
                        <td>{user.username}</td>
                        <td>
                          {user.role === "owner" ? t("data.users.role.owner") : t("data.users.role.member")}
                        </td>
                        <td>
                          <StatusPill
                            tone={user.disabled ? "warn" : "ok"}
                            label={user.disabled ? t("data.users.status.disabled") : t("data.users.status.active")}
                          />
                        </td>
                        <td className="muted">{user.created_at}</td>
                        <td>
                          {user.disabled ? (
                            <button type="button" disabled={rowBusy} onClick={() => void doEnable(user.username)}>
                              {t("data.users.action.enable")}
                            </button>
                          ) : (
                            <button
                              type="button"
                              disabled={rowBusy}
                              onClick={() => setConfirming({ kind: "disable", username: user.username })}
                            >
                              {t("data.users.action.disable")}
                            </button>
                          )}{" "}
                          <button type="button" disabled={rowBusy} onClick={() => openResetPassword(user.username)}>
                            {t("data.users.action.resetPassword")}
                          </button>{" "}
                          <button
                            type="button"
                            disabled={rowBusy}
                            onClick={() => setConfirming({ kind: "revoke", username: user.username })}
                          >
                            {t("data.users.action.revokeSessions")}
                          </button>{" "}
                          {user.role === "owner" ? (
                            <button
                              type="button"
                              disabled={rowBusy}
                              onClick={() => void doSetRole(user.username, "member")}
                            >
                              {t("data.users.role.makeMember")}
                            </button>
                          ) : (
                            <button
                              type="button"
                              disabled={rowBusy}
                              onClick={() => void doSetRole(user.username, "owner")}
                            >
                              {t("data.users.role.makeOwner")}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {resetTarget && (
            <form className="panel" onSubmit={(e) => void submitResetPassword(e)}>
              <h3>{t("data.users.resetPassword.heading", { username: resetTarget })}</h3>
              <label>
                {t("data.users.resetPassword.passwordLabel")}
                <input
                  type="password"
                  value={resetPassword}
                  disabled={resetting}
                  onChange={(e) => setResetPassword(e.target.value)}
                  required
                />
              </label>
              <div className="import-actions">
                <button type="submit" className="symbol-submit" disabled={resetting || !resetPassword}>
                  {resetting ? t("data.users.resetPassword.submitting") : t("data.users.resetPassword.submit")}
                </button>
                <button type="button" disabled={resetting} onClick={() => setResetTarget(null)}>
                  {t("data.users.resetPassword.cancel")}
                </button>
              </div>
              {resetError && <div className="callout callout-danger panel">{resetError}</div>}
            </form>
          )}

          <form className="panel" onSubmit={(e) => void submitCreate(e)}>
            <h3>{t("data.users.create.heading")}</h3>
            <label>
              {t("data.users.create.usernameLabel")}
              <input
                type="text"
                value={newUsername}
                disabled={creating}
                onChange={(e) => setNewUsername(e.target.value)}
                required
              />
            </label>
            <label>
              {t("data.users.create.passwordLabel")}
              <input
                type="password"
                value={newPassword}
                disabled={creating}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </label>
            <label>
              {t("data.users.create.roleLabel")}
              <select
                value={newRole}
                disabled={creating}
                onChange={(e) => setNewRole(e.target.value === "owner" ? "owner" : "member")}
              >
                <option value="member">{t("data.users.role.member")}</option>
                <option value="owner">{t("data.users.role.owner")}</option>
              </select>
            </label>
            <div className="import-actions">
              <button type="submit" className="symbol-submit" disabled={creating || !newUsername || !newPassword}>
                {creating ? t("data.users.create.submitting") : t("data.users.create.submit")}
              </button>
            </div>
            {createError && <div className="callout callout-danger panel">{createError}</div>}
          </form>
        </>
      )}

      <ConfirmSheet
        open={confirming !== null}
        question={
          confirming?.kind === "disable"
            ? t("data.users.disable.confirmQuestion", { username: confirming.username })
            : t("data.users.revoke.confirmQuestion", { username: confirming?.username ?? "" })
        }
        preview={
          confirming?.kind === "disable"
            ? t("data.users.disable.confirmPreview", { username: confirming.username })
            : confirming
              ? t("data.users.revoke.confirmPreview", { username: confirming.username })
              : undefined
        }
        busy={confirmBusy}
        tone="bad"
        onConfirm={() => void runConfirmed()}
        onCancel={() => setConfirming(null)}
      />
    </section>
  );
}
