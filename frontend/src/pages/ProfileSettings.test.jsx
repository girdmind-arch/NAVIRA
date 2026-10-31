import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProfileSettings from "./ProfileSettings.jsx";

const api = vi.hoisted(() => ({
  profileGet: vi.fn(),
  profileUpdate: vi.fn(),
  contactsList: vi.fn(),
  contactsCreate: vi.fn(),
  contactsUpdate: vi.fn(),
  contactsRemove: vi.fn(),
  journeysHistory: vi.fn(),
}));

vi.mock("../services/api", () => ({
  authApi: { login: vi.fn(), register: vi.fn(), logout: vi.fn() },
  contactsApi: {
    list: api.contactsList,
    create: api.contactsCreate,
    update: api.contactsUpdate,
    remove: api.contactsRemove,
  },
  journeysApi: { history: api.journeysHistory },
  profileApi: { get: api.profileGet, update: api.profileUpdate },
  setToken: vi.fn(),
}));

function renderProfile() {
  return render(<ProfileSettings authenticated setAuthenticated={vi.fn()} onSignOut={vi.fn()}/>);
}

beforeEach(() => {
  api.profileGet.mockResolvedValue({ id: 1, email: "person@example.com", name: "Person", country_code: "IN" });
  api.profileUpdate.mockResolvedValue({ id: 1, email: "person@example.com", name: "Person" });
  api.contactsList.mockResolvedValue([]);
  api.contactsCreate.mockImplementation((contact) => Promise.resolve({ id: 2, ...contact }));
  api.contactsUpdate.mockImplementation((id, contact) => Promise.resolve({ id, ...contact }));
  api.contactsRemove.mockResolvedValue(null);
  api.journeysHistory.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("trusted contact phone numbers", () => {
  it("uses the profile country and updates the dialing code when another country is selected", async () => {
    renderProfile();
    const countrySelect = await screen.findByLabelText("Country and dialing code");
    await waitFor(() => expect(countrySelect).toHaveValue("IN"));
    expect(countrySelect.selectedOptions[0].textContent).toContain("🇮🇳");
    expect(countrySelect.selectedOptions[0].textContent).toContain("+91");

    fireEvent.change(countrySelect, { target: { value: "GB" } });
    expect(countrySelect.selectedOptions[0].textContent).toContain("🇬🇧");
    expect(countrySelect.selectedOptions[0].textContent).toContain("+44");
  });

  it("uses a non-India profile country instead of a fixed India default", async () => {
    api.profileGet.mockResolvedValueOnce({
      id: 1,
      email: "person@example.com",
      name: "Person",
      country_code: "US",
    });
    renderProfile();
    const countrySelect = await screen.findByLabelText("Country and dialing code");
    await waitFor(() => expect(countrySelect).toHaveValue("US"));
    expect(countrySelect.selectedOptions[0].textContent).toContain("🇺🇸");
    expect(countrySelect.selectedOptions[0].textContent).toContain("+1");
  });

  it("validates a country-specific number and sends it to the API in E.164 format", async () => {
    renderProfile();
    const countrySelect = await screen.findByLabelText("Country and dialing code");
    await waitFor(() => expect(countrySelect).toHaveValue("IN"));

    fireEvent.change(countrySelect, { target: { value: "GB" } });
    fireEvent.change(screen.getByLabelText("Name", { selector: "#contact-name" }), { target: { value: "A trusted person" } });
    fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "020 7946 0958" } });
    fireEvent.click(screen.getByRole("button", { name: "Add trusted contact" }));

    await waitFor(() => expect(api.contactsCreate).toHaveBeenCalledWith(expect.objectContaining({
      name: "A trusted person",
      phone: "+442079460958",
    })));
  });

  it("rejects incomplete numbers and duplicate trusted contacts", async () => {
    api.contactsList.mockResolvedValueOnce([{
      id: 1,
      name: "Existing contact",
      phone: "+919876543210",
      relationship_label: "Friend",
    }]);
    renderProfile();
    const countrySelect = await screen.findByLabelText("Country and dialing code");
    await waitFor(() => expect(countrySelect).toHaveValue("IN"));

    fireEvent.change(screen.getByLabelText("Name", { selector: "#contact-name" }), { target: { value: "Another person" } });
    fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Add trusted contact" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a valid India phone number.");
    expect(api.contactsCreate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "9876543210" } });
    fireEvent.click(screen.getByRole("button", { name: "Add trusted contact" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already saved as a trusted contact");
    expect(api.contactsCreate).not.toHaveBeenCalled();
  });

  it("prefills, edits, and removes an existing international trusted contact", async () => {
    api.contactsList.mockResolvedValueOnce([{
      id: 7,
      name: "Trusted person",
      phone: "+919876543210",
      relationship_label: "Friend",
    }]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderProfile();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(await screen.findByLabelText("Phone number")).toHaveValue("9876543210");
    expect(screen.getByLabelText("Country and dialing code")).toHaveValue("IN");
    fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "9876543211" } });
    fireEvent.click(screen.getByRole("button", { name: "Update contact" }));
    await waitFor(() => expect(api.contactsUpdate).toHaveBeenCalledWith(7, expect.objectContaining({
      phone: "+919876543211",
    })));

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.contactsRemove).toHaveBeenCalledWith(7));
  });
});
