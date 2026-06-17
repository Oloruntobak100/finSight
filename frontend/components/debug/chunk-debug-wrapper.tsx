"use client";

import { ChunkDebugMonitor } from "./chunk-debug";

export function ChunkDebugWrapper({ children }: { children: React.ReactNode }) {
  return (
    <>
      <ChunkDebugMonitor />
      {children}
    </>
  );
}
