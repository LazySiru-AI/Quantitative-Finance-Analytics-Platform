/**
 * Shared prop shape for the four Data-page panels that mutate something (Sectors, Inception,
 * Users) -- a callback into the single `useToasts()` queue `Data.tsx` owns, so a save on any tab
 * lands in the one toast stack rather than each panel growing its own.
 */
import type { ToastSpec } from "@/components/Toast";

export type ToastPusher = (spec: Omit<ToastSpec, "id">) => string;
