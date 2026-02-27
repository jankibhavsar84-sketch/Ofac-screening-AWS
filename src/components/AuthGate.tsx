import type { ReactNode } from "react";
import { useEffect, useMemo, useRef } from "react";
import { useAuth } from "react-oidc-context";
import { oidcAuthEnabled, oidcIdleTimeoutMs } from "../auth/oidc";

export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  if (!oidcAuthEnabled) return <>{children}</>;
  const idleTimeoutMs = useMemo(() => oidcIdleTimeoutMs, []);
  const idleTimerRef = useRef<number | null>(null);
  const loggingOutRef = useRef(false);

  useEffect(() => {
    if (!auth.isAuthenticated || idleTimeoutMs <= 0) {
      if (idleTimerRef.current) {
        window.clearTimeout(idleTimerRef.current);
        idleTimerRef.current = null;
      }
      return;
    }

    const clearIdleTimer = () => {
      if (idleTimerRef.current) {
        window.clearTimeout(idleTimerRef.current);
        idleTimerRef.current = null;
      }
    };

    const logoutForIdle = async () => {
      if (loggingOutRef.current) return;
      loggingOutRef.current = true;
      try {
        await auth.removeUser();
        try {
          await auth.signoutRedirect();
        } catch {
          // Some IdPs may not support RP initiated logout for local setup.
        }
      } finally {
        loggingOutRef.current = false;
      }
    };

    const resetIdleTimer = () => {
      clearIdleTimer();
      idleTimerRef.current = window.setTimeout(() => {
        void logoutForIdle();
      }, idleTimeoutMs);
    };

    const events: Array<keyof WindowEventMap> = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"];
    events.forEach((eventName) => window.addEventListener(eventName, resetIdleTimer, { passive: true }));
    document.addEventListener("visibilitychange", resetIdleTimer);

    resetIdleTimer();

    return () => {
      events.forEach((eventName) => window.removeEventListener(eventName, resetIdleTimer));
      document.removeEventListener("visibilitychange", resetIdleTimer);
      clearIdleTimer();
    };
  }, [auth, auth.isAuthenticated, idleTimeoutMs]);

  if (auth.isLoading) {
    return (
      <div className="authGate">
        <div className="authGateCard">
          <h2>Loading authentication...</h2>
          <p>Please wait while we verify your session.</p>
        </div>
      </div>
    );
  }

  if (auth.error) {
    return (
      <div className="authGate">
        <div className="authGateCard">
          <h2>Authentication Error</h2>
          <p>{auth.error.message}</p>
          <button type="button" className="btnPrimary" onClick={() => void auth.signinRedirect()}>
            Retry Sign In
          </button>
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="authGate">
        <div className="authGateCard">
          <h2>Sign in required</h2>
          <p>Use your OIDC identity provider account to access the screening platform.</p>
          <button type="button" className="btnPrimary" onClick={() => void auth.signinRedirect()}>
            Sign In
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
