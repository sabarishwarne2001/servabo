/**
 * GST Credit's test data: invented GSTINs with valid check characters, and a GSTR-2B download in the documented
 * shape (unverified against a real portal file; see docs/product/GST-CREDIT.md). Nothing here is a real taxpayer.
 */
const B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export function gstin(state: string, pan: string, entity = "1"): string {
  const first14 = `${state}${pan}${entity}Z`;
  let total = 0;
  [...first14].forEach((ch, index) => {
    const product = B36.indexOf(ch) * (index % 2 === 0 ? 1 : 2);
    total += Math.floor(product / 36) + (product % 36);
  });
  return first14 + B36[(36 - (total % 36)) % 36];
}

const two = (n: number): string => String(n).padStart(2, "0");
const ddmmyyyy = (iso: string): string => `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}`;

export interface Doc2B {
  readonly number: string;
  readonly date: string;
  readonly taxable: number;
  readonly note?: "C" | "D";
  readonly itcAvailable?: "Y" | "N";
}
export interface Supplier2B {
  readonly gstin: string;
  readonly name: string;
  readonly docs: readonly Doc2B[];
}

const round2 = (n: number): number => Math.round(n * 100) / 100;

function document(doc: Doc2B): Record<string, unknown> {
  const tax = round2(doc.taxable * 0.18);
  const half = round2(tax / 2);
  return {
    [doc.note ? "ntnum" : "inum"]: doc.number,
    typ: doc.note ?? "R",
    dt: ddmmyyyy(doc.date),
    val: round2(doc.taxable + half * 2),
    pos: "27",
    rev: "N",
    itcavl: doc.itcAvailable ?? "Y",
    items: [{ num: 1, rt: 18, txval: doc.taxable, igst: 0, cgst: half, sgst: half, cess: 0 }],
  };
}

/** A GSTR-2B for `period` ("2026-09") wrapped as the portal wraps it: {status, data: {chksum, data}}. */
export function gstr2b(recipient: string, period: string, suppliers: readonly Supplier2B[]): string {
  const year = Number(period.slice(0, 4));
  const month = Number(period.slice(5, 7));
  const body = {
    gstin: recipient,
    rtnprd: `${two(month)}${year}`,
    version: "1.0",
    gendt: `14-${two(month === 12 ? 1 : month + 1)}-${month === 12 ? year + 1 : year}`,
    itcsumm: {},
    docdata: {
      b2b: suppliers.map((s) => ({
        ctin: s.gstin, trdnm: s.name, supfildt: `09-${two(month === 12 ? 1 : month + 1)}-${month === 12 ? year + 1 : year}`,
        supprd: `${two(month)}${year}`, inv: s.docs.filter((d) => !d.note).map(document),
      })),
    },
  };
  return JSON.stringify({ status: 1, data: { chksum: "invented", data: body } });
}
