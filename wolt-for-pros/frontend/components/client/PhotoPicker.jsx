'use client';

import { useRef, useState } from 'react';
import { Camera, Link2, Loader2, X } from 'lucide-react';
import { uploadImage } from '@/lib/api';
import { ACCEPTED_TYPES, mediaUrl, resizeImage } from '@/lib/images';
import { useToast } from '@/components/ui/Toast';

const MAX_PHOTOS = 5;

// Photos of the problem: take or pick files (resized, then uploaded right
// away) or paste an https image link. `value` is the list of photo URLs.
export default function PhotoPicker({ value, onChange, onBusyChange = null }) {
  const toast = useToast();
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(0);
  const [link, setLink] = useState('');
  const [showLink, setShowLink] = useState(false);
  const room = MAX_PHOTOS - value.length - uploading;

  function setBusy(delta) {
    setUploading((n) => {
      const next = n + delta;
      if (onBusyChange) onBusyChange(next > 0);
      return next;
    });
  }

  async function onFiles(fileList) {
    const files = Array.from(fileList || []).slice(0, Math.max(0, room));
    if (fileList && fileList.length > files.length) toast(`Up to ${MAX_PHOTOS} photos per request`, 'info');
    for (const file of files) {
      if (!file.type.startsWith('image/')) {
        toast(`${file.name} is not an image`, 'error');
        continue;
      }
      setBusy(1);
      try {
        const blob = await resizeImage(file);
        const url = await uploadImage(blob);
        onChange((list) => [...list, url].slice(0, MAX_PHOTOS));
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        setBusy(-1);
      }
    }
    if (inputRef.current) inputRef.current.value = '';
  }

  function addLink(e) {
    e.preventDefault();
    let url;
    try {
      url = new URL(link.trim());
    } catch {
      toast('Paste a full image link starting with https://', 'error');
      return;
    }
    if (url.protocol !== 'https:') {
      toast('Only https:// image links are accepted', 'error');
      return;
    }
    onChange((list) => [...list, url.href].slice(0, MAX_PHOTOS));
    setLink('');
    setShowLink(false);
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {value.map((url, i) => (
          <div key={`${i}-${url.slice(0, 40)}`} className="relative h-20 w-20 overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200">
            <img src={mediaUrl(url)} alt={`Photo ${i + 1}`} className="h-full w-full object-cover" />
            <button
              type="button"
              onClick={() => onChange((list) => list.filter((_, j) => j !== i))}
              className="absolute right-1 top-1 rounded-full bg-slate-900/70 p-0.5 text-white hover:bg-slate-900"
              aria-label={`Remove photo ${i + 1}`}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        {Array.from({ length: uploading }).map((_, i) => (
          <div key={`up-${i}`} className="flex h-20 w-20 items-center justify-center rounded-xl bg-slate-100 ring-1 ring-slate-200">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ))}
        {room > 0 && (
          <button
            type="button"
            onClick={() => inputRef.current && inputRef.current.click()}
            className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-slate-300 text-xs font-semibold text-slate-500 hover:border-brand-400 hover:text-brand-700"
          >
            <Camera className="h-5 w-5" /> Add photo
          </button>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES.join(',')}
        multiple
        className="hidden"
        onChange={(e) => onFiles(e.target.files)}
      />
      {room > 0 && (showLink ? (
        <div className="mt-2 flex gap-2">
          <label htmlFor="photo-link" className="sr-only">Image link</label>
          <input id="photo-link" className="input" placeholder="https://… image link" value={link} onChange={(e) => setLink(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addLink(e)} />
          <button type="button" className="btn-secondary shrink-0" onClick={addLink}>Add</button>
        </div>
      ) : (
        <button type="button" onClick={() => setShowLink(true)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-brand-700">
          <Link2 className="h-3.5 w-3.5" /> Add an image link instead
        </button>
      ))}
    </div>
  );
}
