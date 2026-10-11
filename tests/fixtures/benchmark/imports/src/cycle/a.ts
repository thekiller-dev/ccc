import { b } from "./b";

export function a(depth = 0): number {
  return depth > 0 ? b(depth - 1) : 1;
}
