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

const { default: makeWASocket, fetchLatestBaileysVersion, DisconnectReason } = require('@whiskeysockets/baileys');
const { useEncryptedMultiFileAuthState } = require('./encrypted_auth_state.js');
const QRCode = require('qrcode');
const pino = require('pino');
const fs = require('fs');
const path = require('path');

// no dotenv dependency in this Node project — the repo's real .env lives
// three levels up (repo/.env); read WHATSAPP_AUTH_ENCRYPTION_KEY straight
// off it if it's not already in the process environment (e.g. python's
// side already loaded it and re-exported, or this is run some other way)
if (!process.env.WHATSAPP_AUTH_ENCRYPTION_KEY) {
  const envPath = path.join(__dirname, '..', '..', '..', '.env');
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, 'utf-8').split('\n')) {
      const match = line.match(/^WHATSAPP_AUTH_ENCRYPTION_KEY=(.*)$/);
      if (match) process.env.WHATSAPP_AUTH_ENCRYPTION_KEY = match[1].trim();
    }
  }
}

const AUTH_DIR = path.join(__dirname, '.auth_state');
const QUEUE_PATH = path.join(__dirname, 'queue.jsonl');
const CONTACTS_PATH = path.join(__dirname, 'contacts.jsonl');
const CHATS_PATH = path.join(__dirname, 'chats.jsonl');
const SELF_JID_PATH = path.join(__dirname, 'self_jid.txt');
const QR_PATH = path.join(__dirname, 'qr.png');
const HEARTBEAT_PATH = path.join(__dirname, '.heartbeat.txt');
const STATUS_PATH = path.join(__dirname, '.status.json');
const PID_PATH = path.join(__dirname, '.pid');
const EVENT_LOG_PATH = path.join(__dirname, '.connection_log.txt');

// The heartbeat alone can't tell a caller (monitor.py, or a human staring
// at a stale heartbeat) *what's actually going on* — found the hard way
// 2026-08-27, when a dead-in-practice process was still alive in the OS
// process list with no record anywhere of why it had stopped doing
// anything. These two together close that gap: .status.json is the
// current, single-fact answer ("what state is this in right now"); the
// event log is the history, so a future incident is diagnosable instead
// of guessed at from a stale timestamp alone.
function logEvent(message) {
  const line = `${new Date().toISOString()} ${message}\n`;
  console.log(message);
  fs.appendFileSync(EVENT_LOG_PATH, line);
}

function writeStatus(state, detail) {
  fs.writeFileSync(STATUS_PATH, JSON.stringify({ state, detail, at: new Date().toISOString() }));
}

// written once at process start, independent of connection state — this
// is what lets a caller tell "the process itself is gone" (down, needs
// restarting) apart from "the process is alive but stuck" (zombie, needs
// killing before restarting), which a heartbeat-only check can't do.
fs.writeFileSync(PID_PATH, String(process.pid));
logEvent(`PROCESS_START pid=${process.pid}`);

// an uncaught error used to just crash silently (or, worse, leave the
// process alive with a dead event loop depending on what threw) with
// nothing persisted anywhere about what happened — exactly the kind of
// gap that made 2026-08-27's incident undiagnosable after the fact.
// Log first, then exit with the same non-zero code Node's own default
// handler would have used, so failure behaviour is unchanged, only now
// it leaves evidence.
process.on('uncaughtException', (e) => {
  logEvent(`FATAL uncaughtException: ${e.stack || e}`);
  writeStatus('crashed', String(e.message || e));
  process.exit(1);
});
process.on('unhandledRejection', (e) => {
  logEvent(`FATAL unhandledRejection: ${e && e.stack ? e.stack : e}`);
  writeStatus('crashed', String(e));
  process.exit(1);
});

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
  const { state, saveCreds } = await useEncryptedMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    auth: state,
    version,
    logger: pino({ level: 'silent' }),
    // default is a "RECENT"-only history sync, which silently excludes
    // less-active chats (found while chasing down two contacts — Ram,
    // Thomas — that showed up in the phone's own contact list but never
    // synced a single message). This asks for full history instead.
    syncFullHistory: true,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      logEvent('QR_UPDATED — scan qr.png to pair');
      writeStatus('qr_pending', `scan ${QR_PATH} to pair — the app was logged out or this is a fresh setup`);
      QRCode.toFile(QR_PATH, qr, { width: 500 }).catch((e) => console.error('qr write failed', e));
    }
    if (connection === 'open') {
      fs.writeFileSync(SELF_JID_PATH, sock.user.id);
      fs.writeFileSync(HEARTBEAT_PATH, new Date().toISOString());
      logEvent(`CONNECTED as ${sock.user.id}`);
      writeStatus('connected', `connected as ${sock.user.id}`);
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      logEvent(`CONNECTION_CLOSED code=${code} loggedOut=${loggedOut}`);
      if (loggedOut) {
        // no separate "re-pair" script exists — .auth_state itself is
        // now invalid, so the fix is deleting it and starting fresh:
        // the next run has no valid session, generates a QR (see the
        // qr branch above), and re-pairing happens the same way initial
        // setup did.
        logEvent('LOGGED_OUT — delete .auth_state and run `node ingest.js` again to re-pair via a fresh QR');
        writeStatus('logged_out', 'session invalidated by WhatsApp — delete .auth_state and run `node ingest.js` again, then scan the new qr.png');
        return; // deliberately no auto-restart — a fresh QR needs a human, retrying would just loop
      }
      writeStatus('reconnecting', `connection dropped (code ${code}), retrying in 2s`);
      setTimeout(() => start(), 2000);
    }
  });

  // WhatsApp is mid-rollout of an opaque "@lid" identifier that can stand
  // in for a contact's phone-number jid on some events (notably active,
  // recently-synced chats — found while chasing why a contact we message
  // constantly showed zero synced messages: they were syncing fine, just
  // under a second, unrecognised identity). Baileys already has to resolve
  // lid<->phone internally to decrypt anything, so the mapping exists;
  // this just asks for it before a message ever hits the queue, so
  // everything downstream keys on one identity per person, not two.
  async function resolveJid(jid) {
    if (!jid || !jid.endsWith('@lid')) return jid;
    try {
      const pn = await sock.signalRepository.lidMapping.getPNForLID(jid);
      if (!pn) return jid; // unresolved — queue the raw lid rather than drop the message
      // resolved jids carry a ":<device>" suffix (e.g. ":0" for the primary
      // device) that the phone-number jids already stored everywhere else
      // (contacts.jsonl, existing identity rows) don't have — strip it so
      // this doesn't just create a third, still-mismatched identity
      return pn.replace(/:\d+@/, '@');
    } catch {
      return jid;
    }
  }

  // covers both the initial history backfill on first pairing and
  // ongoing live messages — same event, same handling, same queue
  sock.ev.on('messaging-history.set', async ({ chats, messages }) => {
    for (const c of chats || []) await queueChat(c, 'history.set');
    for (const m of messages || []) await queueMessage(m);
  });

  // diagnostic-only: which chats WhatsApp told this device about at all,
  // independent of whether any of their messages made it through
  // extractText(). Answers "did the chat sync but get filtered" vs "the
  // chat never synced" for a chat that shows zero messages downstream.
  sock.ev.on('chats.upsert', async (chats) => {
    for (const c of chats || []) await queueChat(c, 'chats.upsert');
  });

  async function queueChat(c, source) {
    if (!c.id) return;
    const jid = await resolveJid(c.id);
    fs.appendFileSync(
      CHATS_PATH,
      JSON.stringify({ jid, name: c.name || null, source }) + '\n'
    );
  }

  sock.ev.on('messages.upsert', async ({ messages }) => {
    for (const m of messages || []) await queueMessage(m);
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

  async function queueMessage(m) {
    const text = extractText(m.message);
    if (!text) return; // non-text (reactions, protocol messages, etc.) — skip for now
    // messageTimestamp is a Long (from the 'long' package) — JSON.stringify
    // on it produces {low, high, unsigned}, not a plain number, which broke
    // the Python side's int() call. toNumber() gives a real epoch second.
    const rawTs = m.messageTimestamp;
    const timestamp = rawTs && typeof rawTs.toNumber === 'function' ? rawTs.toNumber() : Number(rawTs);
    const remoteJid = await resolveJid(m.key.remoteJid);
    const participant = m.key.participant ? await resolveJid(m.key.participant) : null;
    appendToQueue({
      id: m.key.id,
      remote_jid: remoteJid,
      from_me: !!m.key.fromMe,
      participant,                             // set for group messages: actual sender
      timestamp,                               // epoch seconds, from the protocol itself
      push_name: m.pushName || null,
      text,
      is_group: (m.key.remoteJid || '').endsWith('@g.us'),
    });
  }
}

start().catch((e) => {
  logEvent(`FATAL start() failed: ${e.stack || e}`);
  writeStatus('crashed', String(e.message || e));
  process.exit(1);
});

// message volume alone can't tell monitoring "is the connector alive" —
// a quiet chat looks identical to a dead socket if all you check is "when
// did the last message arrive." This is the actual liveness signal:
// as long as this process is running its event loop at all, the file's
// mtime stays fresh, independent of whether anyone happens to be messaging.
setInterval(() => {
  const now = new Date().toISOString();
  console.log('HEARTBEAT', now);
  fs.writeFileSync(HEARTBEAT_PATH, now);
}, 60000);
