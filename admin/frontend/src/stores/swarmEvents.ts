import { create } from "zustand";
import { SwarmSSE } from "../lib/swarm-sse";
import { adminFetch } from "../lib/admin-api";
import { useSwarmRegistry } from "./swarmRegistry";

interface SwarmEventsState {
  connected: boolean;
  sse: SwarmSSE | null;
  connect: (baseUrl: string) => Promise<void>;
  disconnect: () => void;
}

export const useSwarmEvents = create<SwarmEventsState>((set, get) => ({
  connected: false,
  sse: null,

  connect: async (baseUrl: string) => {
    const existing = get().sse;
    if (existing) return;

    const sse = new SwarmSSE({
      baseUrl,
      getToken: async () => {
        // adminFetch<T> returns parsed JSON directly (not a Response)
        const data = await adminFetch<{ token: string }>("/swarm/events/token", {
          method: "POST",
        });
        return data.token;
      },
      onEvent: (type, data) => {
        useSwarmRegistry.getState().handleEvent(type, data);
      },
      onConnectionChange: (connected) => set({ connected }),
    });

    set({ sse });
    await sse.connect();
  },

  disconnect: () => {
    get().sse?.stop();
    set({ sse: null, connected: false });
  },
}));
