/**
 * `UsersPanel`: lists users, creates one (`POST /api/users`), and gates Disable / Revoke sessions
 * behind a `ConfirmSheet`. `usersApi` is stubbed at the module boundary, matching every other page
 * test in this codebase's approach to its own API modules.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type { AdminUser, UserRole } from "@/api/users";

const listMock = vi.fn<() => Promise<{ users: AdminUser[] }>>();
const createMock = vi.fn<(username: string, password: string, role: UserRole) => Promise<AdminUser>>();
const disableMock = vi.fn<(username: string) => Promise<{ username: string; disabled: boolean }>>();
const enableMock = vi.fn<(username: string) => Promise<{ username: string; disabled: boolean }>>();
const revokeSessionsMock = vi.fn<(username: string) => Promise<{ revoked: number }>>();
const setPasswordMock = vi.fn<(username: string, password: string) => Promise<{ username: string }>>();
const setRoleMock = vi.fn<(username: string, role: UserRole) => Promise<AdminUser>>();

vi.mock("@/api/users", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/users")>();
  return {
    ...actual,
    usersApi: {
      ...actual.usersApi,
      list: () => listMock(),
      create: (username: string, password: string, role: UserRole) => createMock(username, password, role),
      disable: (username: string) => disableMock(username),
      enable: (username: string) => enableMock(username),
      revokeSessions: (username: string) => revokeSessionsMock(username),
      setPassword: (username: string, password: string) => setPasswordMock(username, password),
      setRole: (username: string, role: UserRole) => setRoleMock(username, role),
    },
  };
});

const { default: UsersPanel } = await import("./UsersPanel");

function adminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    username: "alice",
    role: "member",
    disabled: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("UsersPanel", () => {
  it("renders the user list once loaded", async () => {
    listMock.mockResolvedValue({
      users: [adminUser({ role: "owner" }), adminUser({ username: "bob", disabled: true })],
    });
    render(<UsersPanel onToast={vi.fn()} />);

    expect(await screen.findByText("alice")).toBeTruthy();
    expect(screen.getByText("bob")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
  });

  it("shows each user's role, and offers the opposite role as the row action", async () => {
    listMock.mockResolvedValue({
      users: [adminUser({ username: "alice", role: "owner" }), adminUser({ username: "bob", role: "member" })],
    });
    render(<UsersPanel onToast={vi.fn()} />);

    await screen.findByText("alice");
    const aliceRow = screen.getByText("alice").closest("tr");
    const bobRow = screen.getByText("bob").closest("tr");
    if (!aliceRow || !bobRow) throw new Error("expected both user rows to render");

    expect(within(aliceRow).getByText("Owner")).toBeTruthy();
    expect(within(aliceRow).getByRole("button", { name: "Make member" })).toBeTruthy();
    expect(within(bobRow).getByText("Member")).toBeTruthy();
    expect(within(bobRow).getByRole("button", { name: "Make owner" })).toBeTruthy();
  });

  it("promotes a member to owner via the row action", async () => {
    listMock.mockResolvedValue({ users: [adminUser({ username: "bob", role: "member" })] });
    setRoleMock.mockResolvedValue(adminUser({ username: "bob", role: "owner" }));
    const onToast = vi.fn();
    const user = userEvent.setup();
    render(<UsersPanel onToast={onToast} />);

    await screen.findByText("bob");
    await user.click(screen.getByRole("button", { name: "Make owner" }));

    await waitFor(() => expect(setRoleMock).toHaveBeenCalledWith("bob", "owner"));
    // Scoped to the table: the create form's own role `<select>` also has an "Owner" `<option>`.
    const table = screen.getByTestId("users-table");
    expect(await within(table).findByText("Owner")).toBeTruthy();
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(
        expect.objectContaining({ message: "bob is now an owner.", tone: "ok" }),
      ),
    );
  });

  it("renders the server's last_owner refusal as a readable message, not the generic one", async () => {
    listMock.mockResolvedValue({ users: [adminUser({ username: "alice", role: "owner" })] });
    setRoleMock.mockRejectedValue(new ApiRequestError(409, "last_owner"));
    const onToast = vi.fn();
    const user = userEvent.setup();
    render(<UsersPanel onToast={onToast} />);

    await screen.findByText("alice");
    await user.click(screen.getByRole("button", { name: "Make member" }));

    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Cannot change alice's role: at least one owner must remain.",
          tone: "bad",
        }),
      ),
    );
  });

  it("creates a member by default via the form and fires POST /api/users", async () => {
    listMock.mockResolvedValue({ users: [] });
    createMock.mockResolvedValue(adminUser({ username: "newuser" }));
    const onToast = vi.fn();
    const user = userEvent.setup();
    render(<UsersPanel onToast={onToast} />);

    await screen.findByText("No users yet.");
    await user.type(screen.getByLabelText("Username"), "newuser");
    await user.type(screen.getByLabelText("Password"), "hunter22");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledWith("newuser", "hunter22", "member"));
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(expect.objectContaining({ message: "newuser created.", tone: "ok" })),
    );
  });

  it("creates an owner when Owner is selected in the form", async () => {
    listMock.mockResolvedValue({ users: [] });
    createMock.mockResolvedValue(adminUser({ username: "newowner", role: "owner" }));
    const user = userEvent.setup();
    render(<UsersPanel onToast={vi.fn()} />);

    await screen.findByText("No users yet.");
    await user.type(screen.getByLabelText("Username"), "newowner");
    await user.type(screen.getByLabelText("Password"), "hunter22");
    await user.selectOptions(screen.getByLabelText("Role"), "owner");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledWith("newowner", "hunter22", "owner"));
  });

  it("requires confirmation before disabling a user", async () => {
    listMock.mockResolvedValue({ users: [adminUser()] });
    disableMock.mockResolvedValue({ username: "alice", disabled: true });
    const user = userEvent.setup();
    render(<UsersPanel onToast={vi.fn()} />);

    await screen.findByText("alice");
    await user.click(screen.getByRole("button", { name: "Disable" }));
    expect(disableMock).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("alice");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(disableMock).toHaveBeenCalledWith("alice"));
  });

  it("requires confirmation before revoking sessions, then reports the count", async () => {
    listMock.mockResolvedValue({ users: [adminUser()] });
    revokeSessionsMock.mockResolvedValue({ revoked: 3 });
    const onToast = vi.fn();
    const user = userEvent.setup();
    render(<UsersPanel onToast={onToast} />);

    await screen.findByText("alice");
    await user.click(screen.getByRole("button", { name: "Revoke sessions" }));
    expect(revokeSessionsMock).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(revokeSessionsMock).toHaveBeenCalledWith("alice"));
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(
        expect.objectContaining({ message: "3 sessions ended for alice.", tone: "ok" }),
      ),
    );
  });

  it("enabling a disabled user does not require confirmation", async () => {
    listMock.mockResolvedValue({ users: [adminUser({ disabled: true })] });
    enableMock.mockResolvedValue({ username: "alice", disabled: false });
    const user = userEvent.setup();
    render(<UsersPanel onToast={vi.fn()} />);

    await screen.findByText("alice");
    await user.click(screen.getByRole("button", { name: "Enable" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(enableMock).toHaveBeenCalledWith("alice"));
  });

  it("resets a password through the inline form", async () => {
    listMock.mockResolvedValue({ users: [adminUser()] });
    setPasswordMock.mockResolvedValue({ username: "alice" });
    const user = userEvent.setup();
    render(<UsersPanel onToast={vi.fn()} />);

    await screen.findByText("alice");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    await user.type(screen.getByLabelText("New password"), "new-secret1");
    await user.click(screen.getByRole("button", { name: "Set password" }));

    await waitFor(() => expect(setPasswordMock).toHaveBeenCalledWith("alice", "new-secret1"));
  });
});
