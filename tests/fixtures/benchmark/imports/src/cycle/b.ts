import { a } from "./a";

export function b(depth = 0): number {
  return depth > 0 ? a(depth - 1) : 2;
}
