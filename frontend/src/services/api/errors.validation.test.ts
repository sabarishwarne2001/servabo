/** A person is never shown Pydantic's wording: validation issues are written in plain words. */
import { describe, expect, it } from "vitest";

import { parseErrorEnvelope } from "./errors";

const messageOf = (issues: Array<{ loc: Array<string | number>; msg: string }>): string =>
  parseErrorEnvelope({ detail: issues.map((issue) => ({ type: "x", ...issue })) }, 422, "fallback").message;

describe("validation messages in plain words", () => {
  it.each([
    [{ loc: ["body", "target_value"], msg: "Input should be greater than or equal to 0" }, "Target value must be at least 0"],
    [{ loc: ["body", "name"], msg: "String should have at most 150 characters" }, "Name must be at most 150 characters"],
    [{ loc: ["body", "name"], msg: "String should have at least 1 character" }, "Name cannot be empty"],
    [{ loc: ["body", "smtp_port"], msg: "Input should be less than or equal to 65535" }, "Smtp port must be at most 65535"],
    [{ loc: ["body", "scopes"], msg: "Field required" }, "Scopes is required"],
    [{ loc: ["body", "days"], msg: "Input should be a valid integer, unable to parse string as an integer" }, "Days must be a whole number"],
    [{ loc: ["body", "email"], msg: "Input should be a valid email address, An email address must have an @-sign." }, "Email must be a valid email address"],
    [{ loc: ["body", "role"], msg: "Input should be 'OWNER', 'ADMIN' or 'MEMBER'" }, "Role must be OWNER, ADMIN or MEMBER"],
    [{ loc: ["body", "extra_thing"], msg: "Extra inputs are not permitted" }, "Extra thing is not an allowed field"],
    [{ loc: ["body", "expires_at"], msg: "Value error, The expiry must be in the future." }, "Expires at: The expiry must be in the future."],
    [{ loc: ["body", "settings", "retry_count"], msg: "Input should be greater than 0" }, "Settings › retry count must be more than 0"],
  ])("%j -> %s", (issue, wanted) => {
    expect(messageOf([issue])).toBe(wanted);
  });

  it("joins several issues and keeps an unknown sentence as it is", () => {
    expect(
      messageOf([
        { loc: ["body", "a_field"], msg: "Field required" },
        { loc: ["body", "b"], msg: "Something the library said that we have not seen" },
      ]),
    ).toBe("A field is required; B: Something the library said that we have not seen");
  });

  it("never shows the request part or an empty field", () => {
    expect(messageOf([{ loc: ["query", "limit"], msg: "Input should be less than or equal to 200" }])).toBe("Limit must be at most 200");
    expect(messageOf([{ loc: [], msg: "Value error, Choose at least one event type." }])).toBe("Choose at least one event type.");
  });
});
