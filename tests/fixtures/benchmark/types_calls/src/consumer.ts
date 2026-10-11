import * as util from "./util";
import { same as alphaSame } from "./alpha";
import { same as betaSame } from "./beta";
import { collide } from "./duplicates";
import { Worker } from "./worker";

export function invoke(): number {
  return util.normalize("x").length + alphaSame() + betaSame();
}

export function ambiguous(): number {
  return collide("benchmark").length;
}

export function viaInstance(): number {
  const worker = new Worker();
  return worker.run();
}

export function chooseAmbiguous(flag: boolean): number {
  const maybe = flag ? alphaSame : betaSame;
  return maybe();
}
