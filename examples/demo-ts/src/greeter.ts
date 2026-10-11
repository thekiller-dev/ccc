import { BaseThing } from "./base.js";
import type { Greeting } from "./types";

export class Greeter extends BaseThing implements Greeting {
  greet(name: string): string {
    return `${this.prefix}, ${name}`;
  }
}
