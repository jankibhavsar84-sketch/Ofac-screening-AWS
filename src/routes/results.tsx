import React from "react";
import { createFileRoute } from "@tanstack/react-router";
import { ResultsPage } from "../screens/ResultsPage";

export const Route = createFileRoute("/results")({
  component: ResultsPage,
});
