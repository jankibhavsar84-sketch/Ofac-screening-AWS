import { createFileRoute } from "@tanstack/react-router";
import { DailyScheduleAdminPage } from "../screens/DailyScheduleAdminPage";

export const Route = createFileRoute("/daily-schedules")({
  component: DailyScheduleAdminPage,
});

