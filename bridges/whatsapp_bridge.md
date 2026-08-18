# WhatsApp groups — read this before you build it

**There is no legitimate API for reading WhatsApp group messages.** This is not
a gap in this project; it is WhatsApp's position.

## What the official API does and does not do

The WhatsApp Business Platform (Cloud API) is built for a business messaging
its own customers, one conversation at a time. It **cannot join a group, cannot
read group messages, and cannot subscribe to one.** No tier, no plan, no
partner unlocks it. If someone tells you otherwise they are describing the
unofficial path below.

## The unofficial path, and its real cost

Libraries such as **Baileys** (Node) and **whatsmeow** (Go, with the `neonize`
Python binding) reimplement the WhatsApp Web protocol. You scan a QR code and
they run as a **linked device on your own account** — so they see everything you
see, groups included.

What you are accepting by using one:

- **It violates the WhatsApp Terms of Service.** Automated/unofficial clients
  are prohibited.
- **Account bans are real and can be permanent.** The ban lands on your phone
  number, not on a throwaway API key. Losing it means losing WhatsApp on that
  number — personal chats and all.
- **Use a secondary number.** If you do this at all, put it on a number you can
  afford to lose, not your main one.
- **It reads everything that account can see.** Every group, every private
  chat. Scope which chats you forward carefully — the filter belongs in the
  bridge, before the push, not after.
- **It breaks.** WhatsApp changes the protocol; the library catches up on its
  own schedule.

I have deliberately **not** written this bridge into the repository. It is your
account and your risk, and the decision should be explicit rather than
something that arrives switched on. What follows is enough to build it in an
hour if you decide to.

## If you decide to do it

The bridge is small — the ingest pipe does all the work. Roughly 40 lines of
Node with Baileys:

```js
// npm i @whiskeysockets/baileys @hapi/boom
import makeWASocket, { useMultiFileAuthState } from '@whiskeysockets/baileys'

const INGEST = 'http://127.0.0.1:8080/ingest'
const TOKEN  = process.env.INGEST_TOKEN

// Only forward these groups. Everything else this account can see is ignored
// and never leaves the machine — the allow-list is the privacy boundary.
const WATCH = new Set([
  '972500000000-1234567890@g.us',
])

const { state, saveCreds } = await useMultiFileAuthState('./wa-auth')
const sock = makeWASocket({ auth: state, printQRInTerminal: true })
sock.ev.on('creds.update', saveCreds)

sock.ev.on('messages.upsert', async ({ messages }) => {
  for (const m of messages) {
    const jid = m.key?.remoteJid
    if (!jid || !WATCH.has(jid)) continue          // allow-list, not block-list
    const text = m.message?.conversation
              ?? m.message?.extendedTextMessage?.text
    if (!text) continue

    await fetch(INGEST, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${TOKEN}`,
                 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: `וואטסאפ · ${m.pushName ?? jid.split('@')[0]}`,
        text,
        kind: 'whatsapp',
        id: m.key.id,                              // dedupe across restarts
        timestamp: Number(m.messageTimestamp),
      }),
    }).catch(e => console.error('ingest failed:', e.message))
  }
})
```

Run it under the same process supervisor as the monitor, on the same host, so
the ingest port never leaves localhost:

```yaml
# docker-compose.override.yml
services:
  whatsapp:
    image: node:22-slim
    restart: unless-stopped
    working_dir: /bridge
    volumes: ["./bridges/whatsapp:/bridge"]
    environment:
      INGEST_TOKEN: ${INGEST_TOKEN}
    network_mode: "service:alerts"   # shares localhost with the monitor
    command: sh -c "npm i && node bridge.js"
```

The first run prints a QR code in the logs; scan it once from WhatsApp →
Linked Devices. The `wa-auth` directory holds the session — back it up, and
treat it as a credential.

## The safer alternative worth considering first

If the groups you care about are neighbourhood or municipal alert groups, check
whether the same information reaches a **Telegram channel** or a website first.
Most Israeli emergency and municipal feeds publish to several places at once,
and this project already reads both of those with no account risk at all.
