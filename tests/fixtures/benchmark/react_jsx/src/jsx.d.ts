declare namespace JSX {
  interface Element {}
  interface ElementChildrenAttribute {
    children: {};
  }
  interface IntrinsicElements {
    main: Record<string, unknown>;
    article: Record<string, unknown>;
  }
}
