// Pull to refresh for the web build. React Native's RefreshControl does nothing on the web, and an
// app added to the home screen has no browser to pull either, so the gesture is made here from the
// scroll view's touch events: a pull down from the very top, past PULL_TRIGGER, refreshes.
import { type RefObject, useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';

export const PULL_TRIGGER = 70; // shown pixels past which letting go refreshes
const PULL_MAX = 110;

/** The finger's travel, damped so the page lags behind it the way native pulls do. */
export function pullDistance(travel: number): number {
  if (travel <= 0) return 0;
  return Math.min(PULL_MAX, travel * 0.5);
}

type Scrollable = { getScrollableNode?: () => HTMLElement | null };

/** The current pull, in pixels, for a scroll view on the web; always 0 on phones. */
export function useWebPull(ref: RefObject<unknown>, onPull: () => void): number {
  const [shown, setShown] = useState(0);
  const pull = useRef(onPull);
  useEffect(() => {
    pull.current = onPull;
  });

  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const node = (ref.current as Scrollable | null)?.getScrollableNode?.();
    if (!node) return;
    let start: number | null = null;
    let distance = 0;

    const begin = (event: TouchEvent) => {
      start = node.scrollTop <= 0 && event.touches.length === 1 ? event.touches[0].clientY : null;
      distance = 0;
    };
    const move = (event: TouchEvent) => {
      if (start === null) return;
      distance = pullDistance(event.touches[0].clientY - start);
      if (distance > 0 && event.cancelable) event.preventDefault(); // no page bounce meanwhile
      setShown(distance);
    };
    const end = () => {
      if (start !== null && distance >= PULL_TRIGGER) pull.current();
      start = null;
      distance = 0;
      setShown(0);
    };

    node.addEventListener('touchstart', begin, { passive: true });
    node.addEventListener('touchmove', move, { passive: false });
    node.addEventListener('touchend', end);
    node.addEventListener('touchcancel', end);
    return () => {
      node.removeEventListener('touchstart', begin);
      node.removeEventListener('touchmove', move);
      node.removeEventListener('touchend', end);
      node.removeEventListener('touchcancel', end);
    };
  }, [ref]);

  return shown;
}
