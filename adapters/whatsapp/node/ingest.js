/**
 * WhatsApp connection layer — the one piece of this project that has to be
 * Node, not Python (see runbook: no mature Python multi-device WhatsApp
 * protocol library exists; Baileys is the de facto one, Node-only).
 *
 * This file's only job is "stay connected, write every message to a
 * queue file as JSON lines." No store access, no envelope mapping — that
 * boundary is deliberate, matching §6: vendor payloads stop here.
 * sync.py (Python) reads the queue and does everything downstream.
 *
 * Run: node ingest.js
 */

const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } = require('@whiskeysockets/baileys');
const QRCode = require('qrcode');
const pino = require('pino');
const fs = require('fs');
const path = require('path');

const AUTH_DIR = path.join(__dirname, '.auth_state');
const QUEUE_PATH = path.join(__dirname, 'queue.jsonl');
const CONTACTS_PATH = path.join(__dirname, 'contacts.jsonl');
const SELF_JID_PATH = path.join(__dirname, 'self_jid.txt');
const QR_PATH = path.join(__dirname, 'qr.png');

function extractText(message) {
  if (!message) return null;
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    null
  );
}

function appendToQueue(record) {
  fs.appendFileSync(QUEUE_PATH, JSON.stringify(record) + '\n');
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    auth: state,
    version,
    logger: pino({ level: 'silent' }),
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      console.log('QR_UPDATED — scan via the viewer page');
      QRCode.toFile(QR_PATH, qr, { width: 500 }).catch((e) => console.error('qr write failed', e));
    }
    if (connection === 'open') {
      fs.writeFileSync(SELF_JID_PATH, sock.user.id);
      console.log('CONNECTED as', sock.user.id);
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      console.log(`CONNECTION_CLOSED code=${code} loggedOut=${loggedOut}`);
      if (loggedOut) {
        console.log('LOGGED_OUT — delete .auth_state and re-pair via login.js');
        return;
      }
      setTimeout(() => start(), 2000);
    }
  });

  // covers both the initial history backfill on first pairing and
  // ongoing live messages — same event, same handling, same queue
  sock.ev.on('messaging-history.set', ({ messages }) => {
    for (const m of messages || []) queueMessage(m);
  });

  sock.ev.on('messages.upsert', ({ messages }) => {
    for (const m of messages || []) queueMessage(m);
  });

  // real names, not just what a message happened to broadcast — id is the
  // jid, name is what's saved in your own phone contacts (best source),
  // notify is what the contact set for themselves
  sock.ev.on('contacts.upsert', (contacts) => {
    for (const c of contacts || []) {
      if (!c.id || (!c.name && !c.notify)) continue;
      fs.appendFileSync(
        CONTACTS_PATH,
        JSON.stringify({ jid: c.id, name: c.name || null, notify: c.notify || null }) + '\n'
      );
    }
  });

  function queueMessage(m) {
    const text = extractText(m.message);
    if (!text) return; // non-text (reactions, protocol messages, etc.) — skip for now
    // messageTimestamp is a Long (from the 'long' package) — JSON.stringify
    // on it produces {low, high, unsigned}, not a plain number, which broke
    // the Python side's int() call. toNumber() gives a real epoch second.
    const rawTs = m.messageTimestamp;
    const timestamp = rawTs && typeof rawTs.toNumber === 'function' ? rawTs.toNumber() : Number(rawTs);
    appendToQueue({
      id: m.key.id,
      remote_jid: m.key.remoteJid,
      from_me: !!m.key.fromMe,
      participant: m.key.participant || null, // set for group messages: actual sender
      timestamp,                               // epoch seconds, from the protocol itself
      push_name: m.pushName || null,
      text,
      is_group: (m.key.remoteJid || '').endsWith('@g.us'),
    });
  }
}

start().catch((e) => {
  console.error('FATAL', e);
  process.exit(1);
});

setInterval(() => console.log('HEARTBEAT', new Date().toISOString()), 60000);
