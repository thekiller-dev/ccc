import { Base } from "./base";
import { Contract } from "./contracts";
import { normalize } from "./util";

export class Worker extends Base implements Contract {
  run(): number {
    return normalize("worker").length;
  }

  step(): number {
    return this.finish();
  }

  private finish(): number {
    return 1;
  }
}
