/**
 * The account page: change-password form plus sign-out/back-to-dashboard actions. `@/api/auth`'s
 * `changePassword` is mocked (so no network), but its real `ChangePasswordError` class is kept,
 * because the page branches on `instanceof ChangePasswordError` and reads `err.kind` -- a plain
 * mock object would fail that check and always fall through to the generic error message.
 * `@/auth` is mocked wholesale since it is a context provider, not a module the component partially
 * needs; `signOut` is declared with `const` above the `vi.mock` call so the hoisted factory can
 * still close over it (`vi.mock` factories run before other top-level `const`s, but not before
 * `vi.mock` calls are hoisted as a block relative to each other and their own `const` deps -- this
 * is the exact shape Login.test.tsx already uses). `<Link to="/overview">` requires a router, so
 * every render is wrapped in `MemoryRouter`. No jest-dom matchers -- this project doesn't install
 * that package -- so assertions use `.textContent` / `.toBeNull()` / `.toBeTruthy()` instead of
 * `toBeInTheDocument()`.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Account from "@/pages/Account";
import * as authApi from "@/api/auth";

const signOut = vi.fn();

vi.mock("@/auth", () => ({
  useAuth: () => ({ username: "alice", authEnabled: true, signOut }),
}));

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return { ...actual, changePassword: vi.fn() };
});

const mockedChangePassword = vi.mocked(authApi.changePassword);

beforeEach(() => {
  signOut.mockReset();
  mockedChangePassword.mockReset();
});

function renderAccount() {
  return render(
    <MemoryRouter>
      <Account />
    </MemoryRouter>,
  );
}

async function fillAndSubmit(
  user: ReturnType<typeof userEvent.setup>,
  current: string,
  next: string,
  confirm: string,
) {
  await user.type(screen.getByLabelText("Current password"), current);
  await user.type(screen.getByLabelText("New password"), next);
  await user.type(screen.getByLabelText("Confirm new password"), confirm);
  await user.click(screen.getByRole("button", { name: "Update password" }));
}

describe("Account", () => {
  it("renders the heading and the signed-in subtitle", () => {
    renderAccount();

    expect(screen.getByRole("heading", { name: "Profile" }).textContent).toContain("Profile");
    expect(screen.getByText("Signed in as alice").textContent).toContain("alice");
  });

  it("changes the password and shows the success message", async () => {
    const user = userEvent.setup();
    mockedChangePassword.mockResolvedValue(undefined);
    renderAccount();

    await fillAndSubmit(user, "old-pass", "new-pass", "new-pass");

    expect(mockedChangePassword).toHaveBeenCalledWith("old-pass", "new-pass");
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("Password updated. Other sessions were signed out.");
  });

  it("rejects mismatched new/confirm passwords without calling changePassword", async () => {
    const user = userEvent.setup();
    renderAccount();

    await fillAndSubmit(user, "old-pass", "new-pass", "different");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The new passwords do not match.");
    expect(mockedChangePassword).not.toHaveBeenCalled();
  });

  it("shows the too-short message for a too_short error", async () => {
    const user = userEvent.setup();
    mockedChangePassword.mockRejectedValue(new authApi.ChangePasswordError("too_short"));
    renderAccount();

    await fillAndSubmit(user, "old-pass", "ab", "ab");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("New password must be at least 4 characters.");
  });

  it("shows the wrong-current message for an invalid_credentials error", async () => {
    const user = userEvent.setup();
    mockedChangePassword.mockRejectedValue(new authApi.ChangePasswordError("invalid_credentials"));
    renderAccount();

    await fillAndSubmit(user, "wrong-pass", "new-pass", "new-pass");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Current password is incorrect.");
  });

  it("shows the generic message for any other error", async () => {
    const user = userEvent.setup();
    mockedChangePassword.mockRejectedValue(new Error("boom"));
    renderAccount();

    await fillAndSubmit(user, "old-pass", "new-pass", "new-pass");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not update the password. Please try again.");
  });

  it("calls signOut when the sign-out button is clicked", async () => {
    const user = userEvent.setup();
    renderAccount();

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(signOut).toHaveBeenCalled();
  });
});
