import { useCallback, useRef, useState } from 'react';
import type { NativeScrollEvent, NativeSyntheticEvent, ScrollViewInstance } from 'react-native';

/** Within this of the end, the chat counts as "at the bottom" and follows what arrives. */
export const PINNED_WITHIN = 80;
/** Further up than this, a button offers to jump back to the latest message. */
export const JUMP_AFTER = 240;

/** How far the view is from the end of its content, never negative. */
export function distanceFromBottom(content: number, view: number, offset: number): number {
  return Math.max(0, content - view - offset);
}

/**
 * A chat that stays at its latest message while that message grows (evidence chips, cards and
 * slow answers arrive after the text), until the person scrolls up to read; then it stays put and
 * offers a button back down. `pin` is for opening a chat or sending: both mean "show the end".
 */
export function useStickToBottom() {
  const ref = useRef<ScrollViewInstance>(null);
  const pinned = useRef(true);
  const opened = useRef(false); // the first jump on opening is instant, later ones glide
  const [showJump, setShowJump] = useState(false);

  const toEnd = useCallback((animated: boolean) => {
    ref.current?.scrollToEnd({ animated });
  }, []);

  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentSize, layoutMeasurement, contentOffset } = event.nativeEvent;
    const distance = distanceFromBottom(
      contentSize.height,
      layoutMeasurement.height,
      contentOffset.y,
    );
    pinned.current = distance <= PINNED_WITHIN;
    setShowJump(distance > JUMP_AFTER);
  }, []);

  const onContentSizeChange = useCallback(() => {
    if (!pinned.current) return;
    toEnd(opened.current);
    opened.current = true;
  }, [toEnd]);

  // The visible area shrinks too, when the composer grows or the keyboard opens: keep the end shown.
  const onLayout = useCallback(() => {
    if (pinned.current) toEnd(false);
  }, [toEnd]);

  const pin = useCallback(
    (animated = true) => {
      pinned.current = true;
      setShowJump(false);
      toEnd(animated);
    },
    [toEnd],
  );

  /** A newly opened chat starts at its end, without gliding through it. */
  const reset = useCallback(() => {
    pinned.current = true;
    opened.current = false;
    setShowJump(false);
  }, []);

  return { ref, onScroll, onContentSizeChange, onLayout, showJump, pin, reset };
}
