import { createFileRoute } from "@tanstack/react-router";
import { AuditLogsPage } from "../screens/AuditLogsPage";

export const Route = createFileRoute("/audit-logs")({
  component: AuditLogsPage,
});
