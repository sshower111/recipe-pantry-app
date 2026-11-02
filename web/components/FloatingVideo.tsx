"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, Maximize2, Minimize2, X } from "lucide-react";
import { useState } from "react";

import type { Recipe } from "@/lib/api";

const FRAME_WIDTH = 340;
const MINI_WIDTH = 176;
const MINI_HEIGHT = 312;
const EXPANDED_HEIGHT = 600;

/** A draggable picture-in-picture player that stays on screen while scrolling the steps. */
export function FloatingVideo({
  video,
  open,
  onClose,
}: {
  video: Recipe["video"];
  open: boolean;
  onClose: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!video.embed_url) return null;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          drag
          dragMomentum={false}
          dragElastic={0.1}
          initial={{ opacity: 0, scale: 0.9, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.9, y: 20 }}
          transition={{ type: "spring", stiffness: 380, damping: 32 }}
          className="fixed right-4 bottom-4 z-50 touch-none"
          role="dialog"
          aria-label="Recipe video"
        >
          <div className="mb-2 flex justify-end gap-2">
            <ControlButton label="Open original post" href={video.url}>
              <ExternalLink className="size-4" />
            </ControlButton>
            <ControlButton label={expanded ? "Shrink video" : "Enlarge video"} onClick={() => setExpanded((e) => !e)}>
              {expanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            </ControlButton>
            <ControlButton label="Close video" onClick={onClose}>
              <X className="size-4" />
            </ControlButton>
          </div>
          <motion.div
            animate={{ width: expanded ? FRAME_WIDTH : MINI_WIDTH, height: expanded ? EXPANDED_HEIGHT : MINI_HEIGHT }}
            initial={false}
            transition={{ type: "spring", stiffness: 300, damping: 32 }}
            className="max-h-[78vh] max-w-[92vw] overflow-hidden rounded-3xl border border-sand bg-white shadow-2xl shadow-ink/25"
          >
            {/* Instagram's embed needs ~326px of width, so the player is laid out at full
                size and scaled down for the mini view instead of being squeezed. */}
            <motion.div
              animate={{ scale: expanded ? 1 : MINI_WIDTH / FRAME_WIDTH }}
              initial={false}
              transition={{ type: "spring", stiffness: 300, damping: 32 }}
              style={{ width: FRAME_WIDTH, height: expanded ? EXPANDED_HEIGHT : MINI_HEIGHT * (FRAME_WIDTH / MINI_WIDTH) }}
              className="origin-top-left"
            >
              <iframe
                src={video.embed_url}
                title="Recipe video"
                className="size-full border-0"
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
              />
            </motion.div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function ControlButton({
  label,
  onClick,
  href,
  children,
}: {
  label: string;
  onClick?: () => void;
  href?: string;
  children: React.ReactNode;
}) {
  const className =
    "flex size-10 items-center justify-center rounded-2xl border border-sand bg-white/90 text-ink shadow-sm backdrop-blur transition-colors hover:bg-white";
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" aria-label={label} className={className}>
      {children}
    </a>
  ) : (
    <button type="button" onClick={onClick} aria-label={label} className={className}>
      {children}
    </button>
  );
}
