import { Card } from "@ui/Card";
import { indexed } from "@indexed";
import { ReExported } from "./barrel";
import { absent } from "./not-there";
import { missing } from "./ui/Card";
import external from "no-such-package-benchmark";
import { a } from "./cycle/a";
import { old } from "@legacy/old";

export function boot(): number {
  return (
    Card()
    + indexed()
    + ReExported()
    + absent()
    + missing()
    + external()
    + a()
    + old()
  );
}
