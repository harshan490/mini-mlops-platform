import { useEffect, useRef, useState } from "react";
import { useUI } from "@/store/ui";

/** Subscribe to a backend WebSocket with automatic reconnect (exponential backoff). */
export function useSocket<T = unknown>(path: string | null, onMessage: (msg: T) => void): boolean {
  const handler = useRef(onMessage);
  handler.current = onMessage;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!path) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const token = useUI.getState().token;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${window.location.host}${path}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
      ws = new WebSocket(url);
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data?.type !== "ping") handler.current(data as T);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, Math.min(10_000, 500 * 2 ** retry++));
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [path]);

  return connected;
}
