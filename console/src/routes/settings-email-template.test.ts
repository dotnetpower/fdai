import { describe, expect, test } from "vitest";
import { decodeEmailTemplatePreview } from "./settings-email-template.model";

describe("email template preview model", () => {
  test("decodes the incident-opened production preview", () => {
    expect(decodeEmailTemplatePreview({
      key: "incident-opened",
      subject: "[SEV2] Incident opened",
      plain_text: "Incident details",
      html: "<!doctype html><html></html>",
    })).toEqual({
      key: "incident-opened",
      subject: "[SEV2] Incident opened",
      plainText: "Incident details",
      html: "<!doctype html><html></html>",
    });
  });

  test.each([
    null,
    {},
    { key: "other", subject: "Subject", plain_text: "Text", html: "<html></html>" },
    { key: "incident-opened", subject: "", plain_text: "Text", html: "<html></html>" },
  ])("rejects malformed preview %#", (value) => {
    expect(() => decodeEmailTemplatePreview(value)).toThrow();
  });
});
