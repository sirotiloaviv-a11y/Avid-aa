/**
 * A minimal RFC 6455 WebSocket server, enough to run the mock market feed.
 *
 * This project has no dependencies, so the handshake and framing are done here.
 * It is intentionally small: text frames, ping/pong and close, no extensions, no
 * permessage-deflate, no fragmentation of outgoing messages. That covers what
 * the mock feed and the tests need and nothing more.
 *
 * It is a test fixture. It is never served to users and never handles untrusted
 * traffic - it listens on the loopback interface only.
 */

import { createHash } from 'node:crypto';

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

const OPCODE = { CONTINUATION: 0x0, TEXT: 0x1, BINARY: 0x2, CLOSE: 0x8, PING: 0x9, PONG: 0xa };

/** Frames one outgoing text message. Server frames are never masked. */
export function encodeTextFrame(text) {
  const payload = Buffer.from(text, 'utf8');
  const length = payload.length;

  let header;
  if (length < 126) {
    header = Buffer.alloc(2);
    header[1] = length;
  } else if (length < 65_536) {
    header = Buffer.alloc(4);
    header[1] = 126;
    header.writeUInt16BE(length, 2);
  } else {
    header = Buffer.alloc(10);
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(length), 2);
  }
  header[0] = 0x80 | OPCODE.TEXT; // FIN + text

  return Buffer.concat([header, payload]);
}

/**
 * Pulls one frame off the front of a buffer.
 * @returns {{frame: {opcode: number, payload: Buffer}, rest: Buffer}|null}
 *   Null when the buffer does not yet hold a whole frame.
 */
export function decodeFrame(buffer) {
  if (buffer.length < 2) return null;

  const opcode = buffer[0] & 0x0f;
  const masked = (buffer[1] & 0x80) === 0x80;
  let length = buffer[1] & 0x7f;
  let offset = 2;

  if (length === 126) {
    if (buffer.length < offset + 2) return null;
    length = buffer.readUInt16BE(offset);
    offset += 2;
  } else if (length === 127) {
    if (buffer.length < offset + 8) return null;
    const big = buffer.readBigUInt64BE(offset);
    // A frame this large is a client bug; the mock refuses rather than allocating.
    if (big > 1_000_000n) throw new Error('frame too large');
    length = Number(big);
    offset += 8;
  }

  let mask = null;
  if (masked) {
    if (buffer.length < offset + 4) return null;
    mask = buffer.subarray(offset, offset + 4);
    offset += 4;
  }

  if (buffer.length < offset + length) return null;

  const payload = Buffer.from(buffer.subarray(offset, offset + length));
  if (mask) {
    for (let i = 0; i < payload.length; i += 1) payload[i] ^= mask[i % 4];
  }

  return { frame: { opcode, payload }, rest: buffer.subarray(offset + length) };
}

/** @param {string} key The client's Sec-WebSocket-Key header. */
export function acceptKey(key) {
  return createHash('sha1').update(key + GUID).digest('base64');
}

/**
 * One connected client.
 */
export class WsConnection {
  /**
   * @param {import('node:net').Socket} socket
   * @param {import('node:http').IncomingMessage} request
   */
  constructor(socket, request) {
    this.socket = socket;
    this.request = request;
    this.url = new URL(request.url ?? '/', 'http://localhost');
    this.closed = false;
    /** @type {((text: string) => void)[]} */
    this.messageHandlers = [];
    /** @type {(() => void)[]} */
    this.closeHandlers = [];

    let buffer = Buffer.alloc(0);
    socket.on('data', (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      try {
        for (;;) {
          const decoded = decodeFrame(buffer);
          if (!decoded) break;
          buffer = decoded.rest;
          this.handleFrame(decoded.frame);
        }
      } catch {
        this.close();
      }
    });
    socket.on('close', () => this.markClosed());
    socket.on('error', () => this.markClosed());
  }

  handleFrame(frame) {
    switch (frame.opcode) {
      case OPCODE.TEXT: {
        const text = frame.payload.toString('utf8');
        for (const handler of this.messageHandlers) handler(text);
        break;
      }
      case OPCODE.PING: {
        const header = Buffer.from([0x80 | OPCODE.PONG, frame.payload.length]);
        this.writeRaw(Buffer.concat([header, frame.payload]));
        break;
      }
      case OPCODE.CLOSE:
        this.close();
        break;
      default:
        break;
    }
  }

  /** @param {(text: string) => void} handler */
  onMessage(handler) {
    this.messageHandlers.push(handler);
  }

  /** @param {() => void} handler */
  onClose(handler) {
    this.closeHandlers.push(handler);
  }

  /** @param {string} text */
  send(text) {
    if (this.closed) return false;
    return this.writeRaw(encodeTextFrame(text));
  }

  writeRaw(buffer) {
    try {
      this.socket.write(buffer);
      return true;
    } catch {
      this.markClosed();
      return false;
    }
  }

  close() {
    if (this.closed) return;
    try {
      this.socket.end(Buffer.from([0x80 | OPCODE.CLOSE, 0]));
    } catch {
      /* already gone */
    }
    this.markClosed();
  }

  markClosed() {
    if (this.closed) return;
    this.closed = true;
    for (const handler of this.closeHandlers) handler();
  }
}

/**
 * Attaches WebSocket handling to an http server.
 * @param {import('node:http').Server} server
 * @param {(connection: WsConnection) => void} onConnection
 */
export function attachWebSocket(server, onConnection) {
  server.on('upgrade', (request, socket) => {
    const key = request.headers['sec-websocket-key'];
    if (request.headers.upgrade?.toLowerCase() !== 'websocket' || typeof key !== 'string') {
      socket.destroy();
      return;
    }
    socket.write(
      [
        'HTTP/1.1 101 Switching Protocols',
        'Upgrade: websocket',
        'Connection: Upgrade',
        `Sec-WebSocket-Accept: ${acceptKey(key)}`,
        '\r\n',
      ].join('\r\n'),
    );
    socket.setNoDelay(true);
    onConnection(new WsConnection(socket, request));
  });
}
