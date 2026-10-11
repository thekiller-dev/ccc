export interface Greeting {
  greet(name: string): string;
}

export type GreetingOptions = {
  punctuation?: string;
};
