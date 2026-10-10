/**
 * The login screen: a successful sign-in hands the username to the provider, and each failure kind
 * surfaces its own message. `@/api/auth`'s `login` is mocked (so no network), but its real
 * `LoginError` class is kept, because the page branches on `instanceof LoginError`.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Login from "@/pages/Login";
import * as authApi from "@/api/auth";

const onSignedIn = vi.fn();
// `expired` is what the provider sets when a 401 arrives on a session that *was* signed in (see
// `@/auth`). Mutable here so one test can render the expired case without a second module mock.
let expired = false;

vi.mock("@/auth", () => ({
  useAuth: () => ({ onSignedIn, expired }),
}));

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return { ...actual, login: vi.fn() };
});

const mockedLogin = vi.mocked(authApi.login);

beforeEach(() => {
  onSignedIn.mockReset();
  mockedLogin.mockReset();
  expired = false;
});

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Username"), "alice");
  await user.type(screen.getByLabelText("Password"), "correct-horse-staple");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("Login", () => {
  it("signs in and hands the username to the provider", async () => {
    const user = userEvent.setup();
    mockedLogin.mockResolvedValue({ username: "alice" });
    render(<Login />);

    await fillAndSubmit(user);

    expect(mockedLogin).toHaveBeenCalledWith("alice", "correct-horse-staple");
    expect(onSignedIn).toHaveBeenCalledWith("alice");
  });

  it("shows a generic message on invalid credentials", async () => {
    const user = userEvent.setup();
    mockedLogin.mockRejectedValue(new authApi.LoginError("invalid_credentials"));
    render(<Login />);

    await fillAndSubmit(user);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Incorrect username or password.");
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("shows the lockout countdown when rate-limited", async () => {
    const user = userEvent.setup();
    mockedLogin.mockRejectedValue(new authApi.LoginError("locked", 42));
    render(<Login />);

    await fillAndSubmit(user);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("42 seconds");
  });

  it("says nothing about an expiry on a first visit", () => {
    render(<Login />);
    expect(screen.queryByText("You were signed out. Sign in again to continue.")).toBeNull();
  });

  it("explains an expired session above the form", () => {
    // The whole defect: without this the app swaps the open page for a bare sign-in form and never
    // says why, which reads as a crash that lost the work.
    expired = true;
    render(<Login />);

    const notice = screen.getByRole("status");
    expect(notice.textContent).toBe("You were signed out. Sign in again to continue.");
    // Above the fields, not below the button -- a notice under the submit control is read after the
    // decision it was meant to inform.
    const form = notice.closest("form");
    expect(form).not.toBeNull();
    const username = screen.getByLabelText("Username");
    expect(notice.compareDocumentPosition(username) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
