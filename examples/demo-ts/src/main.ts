import { Greeter } from "./greeter";
import { greet } from "./utils/greet";
import { missingFeature } from "./missing";

export function main(): string {
  const greeter = new Greeter();
  return greet(greeter.greet("CodeGraph"));
}

main();
