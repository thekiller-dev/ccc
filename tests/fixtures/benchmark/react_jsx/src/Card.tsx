interface CardProps {
  title: string;
}

export function Card({ title }: CardProps): JSX.Element {
  return <article>{title}</article>;
}
