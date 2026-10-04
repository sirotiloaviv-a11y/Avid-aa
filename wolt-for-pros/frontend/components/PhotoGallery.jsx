'use client';

import { useState } from 'react';
import { ChevronLeft, ChevronRight, ImageIcon, X } from 'lucide-react';
import { mediaUrl } from '@/lib/images';

// Thumbnails that open a full-screen viewer.
export default function PhotoGallery({ photos = [], size = 'h-20 w-20', emptyLabel = null }) {
  const [open, setOpen] = useState(-1);
  if (!photos.length) {
    return emptyLabel ? (
      <p className="flex items-center gap-1.5 text-xs text-slate-500"><ImageIcon className="h-3.5 w-3.5" /> {emptyLabel}</p>
    ) : null;
  }
  const step = (d) => setOpen((i) => (i + d + photos.length) % photos.length);

  return (
    <>
      <ul className="flex flex-wrap gap-2">
        {photos.map((url, i) => (
          <li key={`${i}-${url.slice(0, 40)}`}>
            <button type="button" onClick={() => setOpen(i)} className={`${size} overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200 hover:ring-brand-400`} aria-label={`Open photo ${i + 1} of ${photos.length}`}>
              <img src={mediaUrl(url)} alt={`Problem photo ${i + 1}`} className="h-full w-full object-cover" loading="lazy" />
            </button>
          </li>
        ))}
      </ul>
      {open >= 0 && (
        <div
          className="fixed inset-0 z-[950] flex items-center justify-center bg-slate-950/90 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Photo viewer"
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(-1);
            if (e.key === 'ArrowRight') step(1);
            if (e.key === 'ArrowLeft') step(-1);
          }}
        >
          <button type="button" className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20" onClick={() => setOpen(-1)} aria-label="Close" autoFocus>
            <X className="h-5 w-5" />
          </button>
          {photos.length > 1 && (
            <button type="button" className="absolute left-3 rounded-full bg-white/10 p-2 text-white hover:bg-white/20" onClick={() => step(-1)} aria-label="Previous photo">
              <ChevronLeft className="h-6 w-6" />
            </button>
          )}
          <img src={mediaUrl(photos[open])} alt={`Problem photo ${open + 1}`} className="max-h-[85vh] max-w-full rounded-xl object-contain" />
          {photos.length > 1 && (
            <button type="button" className="absolute right-3 rounded-full bg-white/10 p-2 text-white hover:bg-white/20" onClick={() => step(1)} aria-label="Next photo">
              <ChevronRight className="h-6 w-6" />
            </button>
          )}
          <p className="absolute bottom-4 text-sm text-white/70">{open + 1} / {photos.length}</p>
        </div>
      )}
    </>
  );
}
