import type { Template } from "@cmc/types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Composer } from "./Composer";

const templates: Template[] = [
  { id: 1, key: "tracking", label: "Tracking", icon: "🚚", body: "", position: 0, active: true },
];

describe("Composer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("inserts a rendered template and blocks sending with unresolved variables", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ text: "Ciao mario, tracking {{tracking_number}}", missing_variables: ["tracking_number"] })),
      ),
    );
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<Composer conversationId={7} templates={templates} onSend={onSend} />);
    fireEvent.click(screen.getByText(/Tracking/));
    const box = await screen.findByDisplayValue(/Ciao mario/);
    expect(screen.getByText(/Completa prima di inviare/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invia" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "Ciao mario, tracking RR1IT" } });
    fireEvent.click(screen.getByRole("button", { name: "Invia" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith("Ciao mario, tracking RR1IT"));
    expect(screen.getByLabelText("Messaggio")).toHaveValue("");
  });

  it("keeps the text when sending fails", async () => {
    const onSend = vi.fn().mockRejectedValue(new Error("boom"));
    render(<Composer conversationId={7} templates={[]} onSend={onSend} />);
    fireEvent.change(screen.getByLabelText("Messaggio"), { target: { value: "ciao" } });
    fireEvent.click(screen.getByRole("button", { name: "Invia" }));
    await waitFor(() => expect(onSend).toHaveBeenCalled());
    expect(screen.getByLabelText("Messaggio")).toHaveValue("ciao");
  });
});
