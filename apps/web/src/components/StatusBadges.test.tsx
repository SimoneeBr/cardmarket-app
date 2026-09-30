import { render, screen } from "@testing-library/react";

import { CONNECTION_STATUS, MESSAGE_STATUS, NOTIFICATION_TYPE, ORDER_STATUS } from "@/lib/labels";

import { MessageStatusBadge, OrderStatusBadge } from "./StatusBadges";

describe("status labels", () => {
  it("renders Italian labels", () => {
    render(<OrderStatusBadge status="PAID" />);
    expect(screen.getByText("Da spedire")).toBeInTheDocument();
    render(<MessageStatusBadge status="UNKNOWN" />);
    expect(screen.getByText("Esito da verificare")).toBeInTheDocument();
  });

  it("covers every backend enum value", () => {
    expect(Object.keys(ORDER_STATUS)).toHaveLength(6);
    expect(Object.keys(MESSAGE_STATUS)).toEqual(["PENDING", "SENT", "FAILED", "UNKNOWN"]);
    expect(Object.keys(CONNECTION_STATUS)).toHaveLength(6);
    expect(Object.keys(NOTIFICATION_TYPE)).toHaveLength(9);
  });
});
