import en from "./conversation-layer.en.json";
import ko from "./conversation-layer.ko.json";
import { scopedTranslator } from "./scoped-translator";

// Conversation-layer role strings keep their `deck.*` keys but load with the lazy Command Deck
// chunk instead of the entry catalog.
export const t = scopedTranslator({ en, ko }, "deck.");
