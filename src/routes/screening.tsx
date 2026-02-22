import * as React from "react";
import { createFileRoute } from "@tanstack/react-router";
import { ScreeningDetailPage } from "../screens/ScreeningDetailPage";

export const Route = createFileRoute("/screening")({
  component: () => <ScreeningDetailPage />,
});