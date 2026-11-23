import { get, writable } from 'svelte/store';

export type GatewayMode = 'full' | 'lite';

export const gatewayMode = writable<GatewayMode | null>(null);

export function getGatewayMode(): GatewayMode | null {
  return get(gatewayMode);
}

export function setGatewayMode(mode: unknown): void {
  gatewayMode.set(mode === 'lite' || mode === 'full' ? mode : null);
}
