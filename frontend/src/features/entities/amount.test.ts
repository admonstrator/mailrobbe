import { describe, expect, it } from "vitest";

import { amountParam, parseAmount } from "./amount";

describe("amounts typed by hand", () => {
  it("reads German notation, plain digits and the English decimal point", () => {
    expect(parseAmount("10.000")).toBe(10000);
    expect(parseAmount("10000")).toBe(10000);
    expect(parseAmount(" 10 000 ")).toBe(10000);
    expect(parseAmount("10 000")).toBe(10000);
    expect(parseAmount("1.234.567,89")).toBe(1234567.89);
    expect(parseAmount("1,5")).toBe(1.5);
    expect(parseAmount("2.5")).toBe(2.5);
    expect(parseAmount("0")).toBe(0);
  });

  it("ignores a currency around the number", () => {
    expect(parseAmount("5.000 EUR")).toBe(5000);
    expect(parseAmount("€ 250")).toBe(250);
    expect(parseAmount("20.000 DM")).toBe(20000);
  });

  it("is null for an empty field and undefined for anything else", () => {
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("   ")).toBeNull();
    expect(parseAmount("abc")).toBeUndefined();
    expect(parseAmount("-5")).toBeUndefined();
    expect(parseAmount("10.00.0")).toBeUndefined();
    expect(parseAmount("1,000.50")).toBeUndefined();
  });

  it("takes from the URL only what the API takes", () => {
    expect(amountParam("10000")).toBe(10000);
    expect(amountParam("2500.5")).toBe(2500.5);
    expect(amountParam("0")).toBe(0);
    expect(amountParam(null)).toBeNull();
    expect(amountParam("10.000,00")).toBeNull();
    expect(amountParam("-1")).toBeNull();
    expect(amountParam("1e5")).toBeNull();
  });
});
