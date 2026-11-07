import { useSyncExternalStore } from "react";
import { getMicLevel, subscribeMicLevel } from "../state/micLevel";

export const useMicLevel = (): number => useSyncExternalStore(subscribeMicLevel, getMicLevel);
