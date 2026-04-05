import { createFileRoute } from "@tanstack/react-router";
import { ManageUsersPage } from "../screens/ManageUsersPage";

export const Route = createFileRoute("/manage-users")({
  component: ManageUsersPage,
});
