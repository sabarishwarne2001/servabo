/** The React keys of the rows in a package verification's problem table. */
import type { VerifyResult } from "@/types/batches";

type Problem = VerifyResult["problems"][number];

export const problemRowKeys = (problems: readonly Problem[]): string[] =>
  problems.map((problem, index) => `${index}:${problem.path}:${problem.status}`);

/** Run by `npm run check:self`. */
export function runProblemKeySelfCheck(): string[] {
  const failures: string[] = [];
  // A file changed in the zip and also named by a manifest that disagrees is listed twice, MODIFIED both times.
  const twice = [
    { path: "data/extractions.csv", expected: "a", actual: "b", status: "MODIFIED" },
    { path: "data/extractions.csv", expected: "c", actual: "a", status: "MODIFIED" },
    { path: "notes.txt", expected: null, actual: null, status: "UNEXPECTED" },
  ] as unknown as readonly Problem[];
  const keys = problemRowKeys(twice);
  if (new Set(keys).size !== keys.length) {
    failures.push(`the problem rows share a key: ${JSON.stringify(keys)}`);
  }
  return failures;
}
