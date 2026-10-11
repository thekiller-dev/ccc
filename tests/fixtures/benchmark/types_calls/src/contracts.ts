export interface Contract {
  run(): number;
}

export interface Named extends Contract {
  name: string;
}
