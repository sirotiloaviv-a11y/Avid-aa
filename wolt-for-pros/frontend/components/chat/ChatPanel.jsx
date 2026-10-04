'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, MessageCircle, Send } from 'lucide-react';
import { api } from '@/lib/api';
import { getSocket, useSocketEvent } from '@/lib/socket';
import { useToast } from '@/components/ui/Toast';

const ACTIVE = ['assigned', 'in_progress'];

function timeOf(value) {
  return new Date(value).toLocaleTimeString('en-IL', { hour: '2-digit', minute: '2-digit' });
}

// Real-time chat between the client and the assigned pro. Sends over the
// socket (`send_message`) and falls back to REST when no socket is connected.
export default function ChatPanel({ job, me, otherName }) {
  const toast = useToast();
  const [messages, setMessages] = useState(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);
  const open = ACTIVE.includes(job.status);

  const add = useCallback((message) => {
    setMessages((list) => (list && !list.some((m) => m.id === message.id) ? [...list, message] : list));
  }, []);

  useEffect(() => {
    let alive = true;
    api(`/api/jobs/${job.id}/messages`)
      .then((d) => alive && setMessages(d.messages))
      .catch((err) => {
        if (alive) setMessages([]);
        toast(err.message, 'error');
      });
    return () => {
      alive = false;
    };
  }, [job.id, toast]);

  useSocketEvent('message:new', (message) => {
    if (message.jobId === job.id) add(message);
  });

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send(e) {
    e.preventDefault();
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      const socket = getSocket();
      const result = socket && socket.connected
        ? await new Promise((resolve) => {
          socket.emit('send_message', { jobId: job.id, body }, resolve);
        })
        : await api(`/api/jobs/${job.id}/messages`, { method: 'POST', body: { body } }).then((d) => ({ ok: true, message: d.message }));
      if (!result || !result.ok) throw new Error((result && result.error) || 'Could not send the message');
      add(result.message);
      setDraft('');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="card flex flex-col overflow-hidden" aria-label={`Chat with ${otherName}`}>
      <header className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
        <MessageCircle className="h-4 w-4 text-brand-600" />
        <h3 className="text-sm font-bold">Chat with {otherName}</h3>
        {!open && <span className="ml-auto text-xs text-slate-500">Closed</span>}
      </header>
      <div ref={listRef} className="flex max-h-72 min-h-[8rem] flex-col gap-2 overflow-y-auto bg-slate-50 px-3 py-3" aria-live="polite">
        {!messages && <Loader2 className="m-auto h-4 w-4 animate-spin text-slate-400" />}
        {messages && messages.length === 0 && (
          <p className="m-auto text-center text-xs text-slate-500">{open ? `Say hi to ${otherName}. Share gate codes, parking tips or extra details here.` : 'No messages.'}</p>
        )}
        {messages && messages.map((m) => {
          const mine = m.senderId === me.id;
          return (
            <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm shadow-sm ${mine ? 'rounded-br-md bg-brand-600 text-white' : 'rounded-bl-md bg-white text-slate-800 ring-1 ring-slate-200'}`}>
                <p className="whitespace-pre-wrap break-words">{m.body}</p>
                <p className={`mt-0.5 text-right text-[10px] ${mine ? 'text-brand-100' : 'text-slate-400'}`}>{timeOf(m.createdAt)}</p>
              </div>
            </div>
          );
        })}
      </div>
      {open ? (
        <form onSubmit={send} className="flex gap-2 border-t border-slate-100 p-2">
          <label htmlFor={`chat-${job.id}`} className="sr-only">Message</label>
          <input
            id={`chat-${job.id}`}
            className="input"
            placeholder="Write a message…"
            value={draft}
            maxLength={1000}
            onChange={(e) => setDraft(e.target.value)}
            autoComplete="off"
          />
          <button className="btn-primary shrink-0 px-3" disabled={sending || !draft.trim()} aria-label="Send">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </form>
      ) : (
        <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">Chat is open while a pro is assigned to the job.</p>
      )}
    </section>
  );
}
