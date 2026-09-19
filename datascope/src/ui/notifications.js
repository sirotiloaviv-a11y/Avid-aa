/**
 * Desktop notifications and the alert sound.
 *
 * The point of this module is that an alert reaches the user when the dashboard
 * is *not* the tab they are looking at. Two facts shape it:
 *
 *   1. The Notifications API only grants permission from a user gesture, and
 *      only in a secure context. `http://127.0.0.1` counts as secure, which is
 *      why the local server works without TLS.
 *   2. The `silent`/sound behaviour of notifications is inconsistent across
 *      platforms - on several, a notification makes no sound at all. So the
 *      sound is generated here with Web Audio instead of relying on it, and the
 *      AudioContext is unlocked during the same gesture that grants permission,
 *      because an AudioContext created without one starts suspended.
 *
 * Nothing is downloaded: the chime is two oscillator notes, so the promise that
 * the page loads no external asset still holds.
 */

export const PERMISSION = Object.freeze({
  GRANTED: 'granted',
  DENIED: 'denied',
  DEFAULT: 'default',
  UNSUPPORTED: 'unsupported',
});

export class Notifier {
  /**
   * @param {{
   *   NotificationImpl?: any,
   *   AudioContextImpl?: any,
   *   onFallback?: (event: any) => void,
   *   soundEnabled?: boolean,
   * }} [options]
   */
  constructor(options = {}) {
    this.NotificationImpl = options.NotificationImpl ?? globalThis.Notification;
    this.AudioContextImpl =
      options.AudioContextImpl ?? globalThis.AudioContext ?? globalThis.webkitAudioContext;
    this.onFallback = options.onFallback ?? null;
    this.soundEnabled = options.soundEnabled !== false;
    this.audioContext = null;
    /** @type {any[]} Notifications kept alive so they are not garbage collected. */
    this.open = [];
  }

  get supported() {
    return Boolean(this.NotificationImpl);
  }

  /** @returns {string} */
  get permission() {
    if (!this.supported) return PERMISSION.UNSUPPORTED;
    return this.NotificationImpl.permission ?? PERMISSION.DEFAULT;
  }

  /**
   * Must be called from a click handler. Also unlocks audio, because that is the
   * same gesture requirement.
   * @returns {Promise<string>}
   */
  async requestPermission() {
    this.unlockAudio();
    if (!this.supported) return PERMISSION.UNSUPPORTED;
    if (this.NotificationImpl.permission === PERMISSION.GRANTED) return PERMISSION.GRANTED;
    if (this.NotificationImpl.permission === PERMISSION.DENIED) return PERMISSION.DENIED;
    try {
      const result = await this.NotificationImpl.requestPermission();
      return result ?? PERMISSION.DEFAULT;
    } catch {
      return PERMISSION.DENIED;
    }
  }

  /** Creates or resumes the AudioContext. Safe to call repeatedly. */
  unlockAudio() {
    if (!this.AudioContextImpl) return false;
    try {
      if (!this.audioContext) this.audioContext = new this.AudioContextImpl();
      if (this.audioContext.state === 'suspended') this.audioContext.resume?.();
      return true;
    } catch {
      this.audioContext = null;
      return false;
    }
  }

  /**
   * A short two-note chime. Deliberately brief and quiet: this can fire while
   * someone is in a meeting.
   * @param {{urgent?: boolean}} [options]
   */
  playChime(options = {}) {
    if (!this.soundEnabled) return false;
    if (!this.audioContext && !this.unlockAudio()) return false;
    const context = this.audioContext;
    if (!context || typeof context.createOscillator !== 'function') return false;

    try {
      const now = context.currentTime;
      const notes = options.urgent ? [880, 1174.7] : [659.3, 880];
      notes.forEach((frequency, index) => {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = frequency;

        const start = now + index * 0.16;
        const end = start + 0.18;
        // A short attack and exponential decay: a raw square start clicks.
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.18, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, end);

        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start(start);
        oscillator.stop(end + 0.02);
      });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Shows one desktop notification for an alert event.
   *
   * The title carries the full asset name and the symbol together, which is the
   * whole point when this appears over another application: "Apple Inc. / AAPL"
   * is identifiable at a glance, "AAPL" alone often is not.
   *
   * @param {import('../lib/alerts.js').AlertEvent} event
   * @returns {{shown: boolean, reason?: string}}
   */
  notify(event) {
    this.playChime({ urgent: event.type === 'price' });

    if (!this.supported) {
      this.onFallback?.(event);
      return { shown: false, reason: PERMISSION.UNSUPPORTED };
    }
    if (this.NotificationImpl.permission !== PERMISSION.GRANTED) {
      this.onFallback?.(event);
      return { shown: false, reason: this.NotificationImpl.permission };
    }

    try {
      const notification = new this.NotificationImpl(event.title, {
        body: event.body,
        // One notification per rule: a rule that fires again replaces its own
        // previous notification instead of stacking another copy.
        tag: `datascope-${event.ruleId}`,
        renotify: true,
        timestamp: event.ts,
        lang: 'he',
        dir: 'rtl',
        silent: false,
        icon: NOTIFICATION_ICON,
        badge: NOTIFICATION_ICON,
        data: { assetKey: event.assetKey, ruleId: event.ruleId },
      });

      notification.onclick = () => {
        try {
          globalThis.focus?.();
          notification.close();
        } catch {
          /* the tab may be gone */
        }
      };
      notification.onclose = () => {
        this.open = this.open.filter((entry) => entry !== notification);
      };
      this.open.push(notification);
      if (this.open.length > 12) this.open.shift();

      return { shown: true };
    } catch (error) {
      this.onFallback?.(event);
      return { shown: false, reason: error instanceof Error ? error.message : 'שגיאה' };
    }
  }

  closeAll() {
    for (const notification of this.open) {
      try {
        notification.close();
      } catch {
        /* already closed */
      }
    }
    this.open = [];
  }
}

/**
 * The notification icon, inline as a data URI so the page still fetches nothing
 * from the network.
 */
const NOTIFICATION_ICON =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
      '<rect width="64" height="64" rx="12" fill="#2a78d6"/>' +
      '<path d="M12 44 L26 26 L38 36 L52 16" stroke="#fff" stroke-width="6" fill="none" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
  );
