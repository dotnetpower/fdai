import en from "./investigation.en.json";
import ko from "./investigation.ko.json";
import { scopedTranslator } from "./scoped-translator";

// Investigation-role strings load with the lazy Command Deck chunk instead of the entry catalog.
export const t = scopedTranslator({ en, ko }, "deck.investigation.");
