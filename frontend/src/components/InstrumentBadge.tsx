/**
 * A small badge flagging that an instrument is not a plain equity.
 *
 * Plain equities are the unremarkable default across every persona surface, so badging them would
 * be noise on every single row -- `equity` renders nothing. Everything else (ETF, index, future,
 * crypto, FX, or an instrument kind the backend has not classified) gets a `StatusPill`, because
 * none of those are directly tradeable by the strategy layer the way a plain equity position is;
 * the pill's `detail` says so explicitly rather than leaving a reader to infer it from the label.
 *
 * `InstrumentKindLike` is declared locally, structurally compatible with whatever
 * `@/api/personas` exports, rather than imported from it -- that module is being rewritten
 * concurrently elsewhere.
 */
import { useT } from "@/i18n/useT";

import { StatusPill, type PillTone } from "@/components/StatusPill";

export type InstrumentKindLike = "equity" | "etf" | "index" | "future" | "crypto" | "fx" | "unknown";

export interface InstrumentBadgeProps {
  instrument: InstrumentKindLike;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

const TONE_BY_KIND: Readonly<Record<Exclude<InstrumentKindLike, "equity">, PillTone>> = {
  etf: "info",
  index: "info",
  future: "special",
  crypto: "special",
  fx: "special",
  unknown: "neutral",
};

export function InstrumentBadge({ instrument, className, "data-testid": dataTestId }: InstrumentBadgeProps) {
  const { t } = useT();

  if (instrument === "equity") return null;

  const label = t(
    (
      {
        etf: "personaAtoms.instrumentBadge.etf",
        index: "personaAtoms.instrumentBadge.index",
        future: "personaAtoms.instrumentBadge.future",
        crypto: "personaAtoms.instrumentBadge.crypto",
        fx: "personaAtoms.instrumentBadge.fx",
        unknown: "personaAtoms.instrumentBadge.unknown",
      } as const
    )[instrument],
  );

  return (
    <StatusPill
      tone={TONE_BY_KIND[instrument]}
      label={label}
      detail={t("personaAtoms.instrumentBadge.detail")}
      className={className}
      data-testid={dataTestId}
    />
  );
}

export default InstrumentBadge;
