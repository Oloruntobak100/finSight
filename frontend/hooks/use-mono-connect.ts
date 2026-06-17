"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type Connect from "@mono.co/connect.js";

export interface MonoCustomer {
  name: string;
  email: string;
}

interface UseMonoConnectOptions {
  publicKey: string | null;
  customer: MonoCustomer | null;
  onSuccess: (code: string) => void;
  onClose?: () => void;
}

export function useMonoConnect({
  publicKey,
  customer,
  onSuccess,
  onClose,
}: UseMonoConnectOptions) {
  const connectRef = useRef<Connect | null>(null);
  const [ready, setReady] = useState(false);
  const onSuccessRef = useRef(onSuccess);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onSuccessRef.current = onSuccess;
  }, [onSuccess]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!publicKey || !customer) {
      connectRef.current = null;
      setReady(false);
      return;
    }

    let cancelled = false;

    async function init() {
      const { default: MonoConnect } = await import("@mono.co/connect.js");
      if (cancelled) return;

      const connect = new MonoConnect({
        key: publicKey!,
        data: { customer: customer! },
        onSuccess: ({ code }) => onSuccessRef.current(code),
        onClose: () => onCloseRef.current?.(),
        onLoad: () => {
          if (!cancelled) setReady(true);
        },
      });

      connect.setup();
      connectRef.current = connect;
      setReady(true);
    }

    init().catch(() => {
      if (!cancelled) setReady(false);
    });

    return () => {
      cancelled = true;
      connectRef.current = null;
      setReady(false);
    };
  }, [publicKey, customer?.email, customer?.name]);

  const open = useCallback(() => {
    connectRef.current?.open();
  }, []);

  return { open, ready: ready && Boolean(publicKey && customer) };
}
