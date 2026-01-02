import { createFileRoute } from "@tanstack/react-router";
import { ScreeningPage } from "../screens/ScreeningPage";

export const Route = createFileRoute("/")({
  component: ScreeningPage,
});
