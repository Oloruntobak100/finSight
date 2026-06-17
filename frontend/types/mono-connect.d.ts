declare module "@mono.co/connect.js" {
  export interface MonoCustomer {
    id?: string;
    name: string;
    email: string;
    identity?: {
      type: string;
      number: string;
    };
  }

  export interface MonoConnectConfig {
    key: string;
    data?: { customer: MonoCustomer };
    onSuccess: (payload: { code: string }) => void;
    onClose?: () => void;
    onLoad?: () => void;
    onEvent?: (eventName: string, data: unknown) => void;
  }

  export default class Connect {
    constructor(config: MonoConnectConfig);
    setup(config?: Partial<MonoConnectConfig>): void;
    open(): void;
    close(): void;
    reauthorise(reauthToken: string): void;
    fetchInstitutions(): Promise<{ data: unknown[] }>;
  }
}
