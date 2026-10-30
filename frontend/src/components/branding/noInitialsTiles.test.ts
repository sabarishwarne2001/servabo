/**
 * The organization console's header and the workspace switcher drew the first letter of a name in a coloured square
 * where every other place shows the Servabo logo (or the customer's own). No component may build a logo from a name's
 * first letter: use ServaboMark or WorkspaceLogo.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "../..");
const INITIALS = /(organization_name|workspace_name)\.charAt\(0\)/;

const files = (dir: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {return files(full);}
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [full] : [];
  });

describe("brand tiles", () => {
  it("never draw a name's first letter in place of the logo", () => {
    const offenders = files(SRC)
      .filter((file) => INITIALS.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(SRC, file));
    expect(offenders).toEqual([]);
  });
});
