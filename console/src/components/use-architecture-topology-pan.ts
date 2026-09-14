import type { JSX } from "preact";
import { useRef, useState } from "preact/hooks";

interface PanState {
  readonly pointerId: number;
  readonly clientX: number;
  readonly clientY: number;
  readonly scrollLeft: number;
  readonly scrollTop: number;
}

/** Owns drag-panning while preserving click selection on topology regions. */
export function useArchitectureTopologyPan() {
  const panRef = useRef<PanState | null>(null);
  const panMovedRef = useRef(false);
  const suppressRegionClickRef = useRef(false);
  const [panning, setPanning] = useState(false);

  const startPan = (event: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;
    if (event.target.closest(
      ".architecture-topology-node, .architecture-topology-node-target",
    )) return;
    panMovedRef.current = false;
    panRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      scrollLeft: event.currentTarget.scrollLeft,
      scrollTop: event.currentTarget.scrollTop,
    };
  };

  const movePan = (event: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    if (
      !panMovedRef.current
      && Math.hypot(event.clientX - pan.clientX, event.clientY - pan.clientY) > 4
    ) {
      panMovedRef.current = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      setPanning(true);
    }
    if (!panMovedRef.current) return;
    event.currentTarget.scrollLeft = pan.scrollLeft - (event.clientX - pan.clientX);
    event.currentTarget.scrollTop = pan.scrollTop - (event.clientY - pan.clientY);
    event.preventDefault();
  };

  const finishPan = (event: JSX.TargetedPointerEvent<HTMLDivElement>): void => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    suppressRegionClickRef.current = panMovedRef.current;
    window.setTimeout(() => {
      suppressRegionClickRef.current = false;
    }, 0);
    panRef.current = null;
    setPanning(false);
  };

  return {
    panning,
    suppressRegionClickRef,
    startPan,
    movePan,
    finishPan,
  };
}
