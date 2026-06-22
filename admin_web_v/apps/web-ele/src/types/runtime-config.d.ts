export {};

declare global {
  interface Window {
    __APP_CONFIG__?: {
      VITE_ADMIN_API_BASE?: string;
    };
  }
}
