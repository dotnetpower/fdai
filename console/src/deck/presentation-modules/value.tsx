import { Tooltip } from "../../components/tooltip";
import { getLocale, t } from "../../i18n";
import {
  presentationActivity,
  presentationActor,
  presentationActors,
  presentationSeverity,
  presentationTimestamp,
} from "../presentation-value";

export function PresentationValue({
  value,
  columnKey = "",
  label = "",
}: {
  readonly value: string;
  readonly columnKey?: string;
  readonly label?: string;
}) {
  const timestamp = presentationTimestamp(value, getLocale() === "ko" ? "ko-KR" : "en-US");
  if (timestamp) {
    return (
      <Tooltip content={t("deck.presentation.recordedValue", { value })}>
        <time class="deck-presentation-timestamp" dateTime={timestamp.dateTime}>
          <span>{timestamp.date}</span>
          <span>{timestamp.time}</span>
        </time>
      </Tooltip>
    );
  }
  if (isActorField(columnKey, label)) {
    const actors = presentationActors(value);
    return (
      <Tooltip content={value}>
        <span class="deck-presentation-actors">
          {actors.visible.map((actor) => <span key={actor}>{presentationActor(actor)}</span>)}
          {actors.hiddenCount > 0 ? (
            <span class="deck-presentation-more">
              +{actors.hiddenCount}
              <span class="sr-only"> {t("deck.presentation.moreActors", {
                count: actors.hiddenCount,
              })}</span>
            </span>
          ) : null}
        </span>
      </Tooltip>
    );
  }
  if (isSeverityField(columnKey, label)) {
    return <Tooltip content={value}><span>{presentationSeverity(value)}</span></Tooltip>;
  }
  if (isCanonicalTokenField(columnKey, label)) {
    return (
      <Tooltip content={value}>
        <span class="deck-presentation-token">{presentationActivity(value)}</span>
      </Tooltip>
    );
  }
  if (isReferenceField(columnKey, label)) {
    return <code class="deck-presentation-ref">{value}</code>;
  }
  return <span>{value}</span>;
}

export function presentationValueKind(label: string, value: string): string {
  if (presentationTimestamp(value)) return "timestamp";
  if (isActorField("", label)) return "actors";
  if (isCanonicalTokenField("", label)) return "token";
  return "text";
}

function isActorField(key: string, label: string): boolean {
  return /actor/i.test(key) || /actor|주체|행위자/i.test(label);
}

function isCanonicalTokenField(key: string, label: string): boolean {
  return /^(activity|mode|status|kind|tier)$/i.test(key) ||
    /^(activity|mode|status|kind|tier|활동|모드|상태|종류|티어)$/i.test(label);
}

function isSeverityField(key: string, label: string): boolean {
  return /^severity$/i.test(key) || /^(severity|심각도)$/i.test(label);
}

function isReferenceField(key: string, label: string): boolean {
  return /(?:ref|reference)$/i.test(key) || /reference|참조/i.test(label);
}
