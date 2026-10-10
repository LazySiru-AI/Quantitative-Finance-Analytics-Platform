/**
 * Mount once near the app root, inside the router (`App.tsx` -- see the manager's wiring note in
 * `docs/AGENT-DESK-CONTRACT.md`-style handoffs for this feature). Renders nothing; its only job is
 * to call `useNavTelemetry`, which needs to live inside a component so it can use `useLocation`.
 */
import { useNavTelemetry } from "@/hooks/useNavTelemetry";

export default function NavTelemetry(): null {
  useNavTelemetry();
  return null;
}
