const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const MAX_RECONNECT_ATTEMPTS = 10;
const HEARTBEAT_TIMEOUT_MS = 60000;
const TOKEN_REFRESH_MARGIN_MS = 60000;

export interface SwarmSSEConfig {
  baseUrl: string;
  getToken: () => Promise<string>;
  onEvent: (type: string, data: unknown) => void;
  onConnectionChange?: (connected: boolean) => void;
}

export class SwarmSSE {
  private es: EventSource | null = null;
  private config: SwarmSSEConfig;
  private token = "";
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private tokenRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private lastEventId = "";

  constructor(config: SwarmSSEConfig) {
    this.config = config;
  }

  async connect(): Promise<void> {
    this.stopped = false;
    await this.refreshToken();
    this.createEventSource();
  }

  stop(): void {
    this.stopped = true;
    this.cleanup();
  }

  private async refreshToken(): Promise<void> {
    this.token = await this.config.getToken();

    this.tokenRefreshTimer = setTimeout(async () => {
      if (!this.stopped) {
        await this.refreshToken();
        this.lastEventId = "";
        this.cleanup();
        this.createEventSource();
      }
    }, 1800 * 1000 - TOKEN_REFRESH_MARGIN_MS);
  }

  private createEventSource(): void {
    const url = new URL(`${this.config.baseUrl}/admin/api/swarm/events/stream`);
    url.searchParams.set("token", this.token);
    // NOTE: lastEventId is tracked for future use but not yet sent —
    // the backend does not currently support resume-from-last-event.

    this.es = new EventSource(url.toString());

    this.es.onopen = () => {
      this.reconnectAttempts = 0;
      this.config.onConnectionChange?.(true);
      this.resetHeartbeatTimeout();
    };

    this.es.onmessage = (e) => {
      this.lastEventId = e.lastEventId;
      try {
        const data = JSON.parse(e.data);
        this.config.onEvent(e.type || "message", data);
      } catch {
        // Malformed SSE data — skip this event
      }
      this.resetHeartbeatTimeout();
    };

    this.es.onerror = () => {
      this.config.onConnectionChange?.(false);
      this.es?.close();
      if (!this.stopped) {
        this.scheduleReconnect();
      }
    };
  }

  private resetHeartbeatTimeout(): void {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      if (!this.stopped) {
        this.es?.close();
        this.scheduleReconnect();
      }
    }, HEARTBEAT_TIMEOUT_MS);
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;
    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, this.reconnectAttempts),
      RECONNECT_MAX_DELAY,
    );
    this.reconnectAttempts++;
    setTimeout(() => {
      if (!this.stopped) this.connect();
    }, delay);
  }

  private cleanup(): void {
    this.es?.close();
    this.es = null;
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    if (this.tokenRefreshTimer) clearTimeout(this.tokenRefreshTimer);
  }
}
