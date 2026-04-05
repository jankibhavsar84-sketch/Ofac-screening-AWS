import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useAuth } from "react-oidc-context";

export const Route = createFileRoute("/signed-out")({
  component: SignedOutRoute,
});

function SignedOutRoute() {
  const auth = useAuth();
  if (auth.isAuthenticated) {
    return <Navigate to="/intro" />;
  }
  return null;
}

