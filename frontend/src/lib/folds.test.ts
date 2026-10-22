import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { setFoldOpen, useFold } from "./folds";

describe("folds", () => {
  it("start as the block says and remember each block on its own", () => {
    const dkim = renderHook(() => useFold("mail.dkim", false));
    const thread = renderHook(() => useFold("mail.thread", true));
    expect(dkim.result.current[0]).toBe(false);
    expect(thread.result.current[0]).toBe(true);

    act(() => dkim.result.current[1](true));
    expect(dkim.result.current[0]).toBe(true);
    expect(thread.result.current[0]).toBe(true);
    act(() => thread.result.current[1](false));
    expect(localStorage.getItem("mailrobbe.folds")).toBe('{"mail.dkim":true,"mail.thread":false}');
  });

  it("let every block of the same id follow a change made elsewhere", () => {
    const { result } = renderHook(() => useFold("mail.dkim", false));
    act(() => setFoldOpen("mail.dkim", true));
    expect(result.current[0]).toBe(true);
  });

  it("fall back to the defaults when the stored value is unreadable", () => {
    localStorage.setItem("mailrobbe.folds", "[oops");
    expect(renderHook(() => useFold("mail.dkim", false)).result.current[0]).toBe(false);
    localStorage.setItem("mailrobbe.folds", '{"mail.dkim":"yes","mail.tech":true}');
    expect(renderHook(() => useFold("mail.dkim", false)).result.current[0]).toBe(false);
    expect(renderHook(() => useFold("mail.tech", false)).result.current[0]).toBe(true);
  });
});
