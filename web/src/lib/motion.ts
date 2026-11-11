import { cubicOut } from 'svelte/easing';
import type { TransitionConfig } from 'svelte/transition';
import type { ParamsType } from 'flowbite-svelte/types';

function reducedMotionRequested(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)')?.matches === true;
}

export function modalMotion(_node: Element, params: ParamsType = {}): TransitionConfig {
  const offset = params && 'y' in params && typeof params.y === 'number' ? params.y : 10;
  const requestedDuration = params && 'duration' in params ? params.duration : undefined;
  return {
    duration: reducedMotionRequested() ? 0 : requestedDuration ?? 220,
    easing: cubicOut,
    css: (t, u) => `opacity:${t};transform:translateY(${u * offset}px) scale(${0.98 + 0.02 * t})`
  };
}
