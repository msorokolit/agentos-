// AgenticOS TypeScript SDK — Phase 0 placeholder.

export interface ClientOptions {
  baseUrl: string;
  token?: string;
}

export class AgenticOSClient {
  constructor(public readonly options: ClientOptions) {}

  async health(): Promise<{ status: string; service: string }> {
    const res = await fetch(`${this.options.baseUrl}/healthz`, {
      headers: this.options.token
        ? { Authorization: `Bearer ${this.options.token}` }
        : undefined,
    });
    if (!res.ok) throw new Error(`health check failed: ${res.status}`);
    return res.json();
  }
}
