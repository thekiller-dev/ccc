import { local } from "./local";
import { alias } from "@/local";

export function run(): number {
  return local() + alias();
}
