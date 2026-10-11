import type { GreetingOptions } from "../types";

export function greet(name: string, options: GreetingOptions = {}): string {
  return `Hello, ${name}${options.punctuation ?? "!"}`;
}
