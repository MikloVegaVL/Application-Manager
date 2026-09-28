import { beforeEach, describe, expect, it } from "vitest";

import {
  DETECTION_SOURCE,
  accessibleLabel,
  detectField,
  detectFields,
  findField,
  normalizeText,
} from "../src/lib/detect.js";

function setup(html) {
  document.body.innerHTML = html;
  return document;
}

describe("detect.js", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("detects a text input by its <label for> (accessible-first)", () => {
    setup('<label for="email">E-Mail</label><input id="email" type="text" />');
    const found = findField(document, { label: "E-Mail" });
    expect(found).not.toBeNull();
    expect(found.source).toBe(DETECTION_SOURCE.LABEL);
    expect(found.element.id).toBe("email");
  });

  it("detects by aria-label and aria-labelledby before attributes", () => {
    setup(`
      <span id="lbl">Phone number</span>
      <input id="a" aria-labelledby="lbl" name="nope" />
      <input id="b" aria-label="Website" name="website" />
    `);
    expect(findField(document, { label: "Phone number" }).element.id).toBe("a");
    expect(findField(document, { label: "Website" }).element.id).toBe("b");
  });

  it("detects by placeholder, autocomplete and name as fallbacks", () => {
    setup(`
      <input id="p" placeholder="Enter your city" />
      <input id="ac" autocomplete="postal-code" />
      <input id="n" name="linkedin" />
    `);
    expect(findField(document, { placeholder: "Enter your city" }).source).toBe(
      DETECTION_SOURCE.PLACEHOLDER
    );
    expect(findField(document, { autocomplete: "postal-code" }).source).toBe(
      DETECTION_SOURCE.AUTOCOMPLETE
    );
    expect(findField(document, { name: "linkedin" }).source).toBe(DETECTION_SOURCE.NAME);
  });

  it("returns matched=false for an unknown field instead of guessing", () => {
    setup('<input id="email" name="email" />');
    const result = detectField(document, { label: "Favorite dinosaur" });
    expect(result.matched).toBe(false);
    expect(result.element).toBeNull();
    expect(result.confidence).toBe(0);
  });

  it("reports confidence per detected field", () => {
    setup('<label for="fn">Full name</label><input id="fn" />');
    const [result] = detectFields(document, [{ label: "Full name" }]);
    expect(result.matched).toBe(true);
    expect(result.confidence).toBeGreaterThan(0);
  });

  it("normalizes accents and case for matching", () => {
    setup('<label for="c">Land</label><select id="c"></select>');
    expect(normalizeText("Österreich")).toBe("osterreich");
    expect(findField(document, { label: "land" }).element.id).toBe("c");
    expect(accessibleLabel(document.getElementById("c"))).toBe("Land");
  });
});
