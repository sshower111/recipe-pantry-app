"use client";

import { useState } from "react";

/** The video thumbnail, or a warm placeholder with the title's initial when there is none. */
export function Thumbnail({
  src,
  title,
  className = "",
  initialClassName = "text-3xl",
}: {
  src: string | null;
  title: string;
  className?: string;
  initialClassName?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div
        aria-hidden
        className={`flex items-center justify-center bg-gradient-to-br from-sand-soft to-sand font-serif text-muted ${initialClassName} ${className}`}
      >
        {title.trim().charAt(0).toUpperCase()}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- served by the local API, nothing to optimise
    <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} className={`object-cover ${className}`} />
  );
}
