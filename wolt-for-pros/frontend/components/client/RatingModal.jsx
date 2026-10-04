'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import StarRating from '@/components/ui/StarRating';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';

export default function RatingModal({ open, onClose, job, onRated }) {
  const toast = useToast();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const name = job.tradesperson ? job.tradesperson.name : 'your pro';

  async function submit(e) {
    e.preventDefault();
    if (!rating) return;
    setBusy(true);
    try {
      const data = await api(`/api/jobs/${job.id}/review`, { method: 'POST', body: { rating, comment: comment.trim() || undefined } });
      toast('Thanks for your review!', 'success');
      onRated(data.review);
    } catch (err) {
      toast(err.message, 'error');
      if (err.code === 'ALREADY_REVIEWED') onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={`How was ${name}?`}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-600">Your rating helps other clients choose and keeps pros accountable.</p>
        <StarRating value={rating} onChange={setRating} />
        <div>
          <label className="label" htmlFor="review-comment">Comment (optional)</label>
          <textarea
            id="review-comment"
            className="input min-h-[84px]"
            maxLength={1000}
            placeholder="On time? Clean work? Fair price?"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary flex-1" onClick={onClose}>Not now</button>
          <button className="btn-primary flex-1" disabled={!rating || busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} Submit review
          </button>
        </div>
      </form>
    </Modal>
  );
}
