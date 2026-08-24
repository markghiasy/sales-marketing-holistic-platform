/**
 * One-off: resolve a fixed list of @lid identifiers back to phone-number
 * jids, using the same Baileys session already paired for ingest.js.
 *
 * Not part of the running adapter — this exists to backfill the mapping
 * for @lid identities that landed in the store / queue before ingest.js
 * learned to resolve them at ingest time (see ingest.js's resolveJid).
 *
 * Run: node resolve_lids.js <input-jsonl>
 * Input: a file with one @lid identifier per line (plain text or JSON
 * lines with a "lid" field both work) — real contact identifiers, so this
 * input file is git-ignored, unlike this script.
 * Writes: lid_map.jsonl (one {lid, pn} per line; pn is null if unresolved)
 */

const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const fs = require('fs');
const path = require('path');

const AUTH_DIR = path.join(__dirname, '.auth_state');
const OUT_PATH = path.join(__dirname, 'lid_map.jsonl');

const inputPath = process.argv[2];
if (!inputPath) {
  console.error('usage: node resolve_lids.js <input-file-of-lids>');
  process.exit(1);
}
const LIDS = fs.readFileSync(inputPath, 'utf8')
  .split('\n')
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => {
    try {
      return JSON.parse(line).lid || line;
    } catch {
      return line;
    }
  });

async function main() {
  const { state } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  const sock = makeWASocket({ auth: state, version, logger: pino({ level: 'silent' }) });

  await new Promise((resolve, reject) => {
    sock.ev.on('connection.update', (u) => {
      if (u.connection === 'open') resolve();
      if (u.connection === 'close') reject(new Error('closed before opening — auth state may be stale'));
    });
  });

  const out = fs.createWriteStream(OUT_PATH);
  for (const lid of LIDS) {
    let pn = null;
    try {
      pn = await sock.signalRepository.lidMapping.getPNForLID(lid);
      // strip the ":<device>" suffix (e.g. ":0") so this matches the bare
      // phone-jid format already used everywhere else (contacts.jsonl,
      // existing identity rows) — same fix as ingest.js's resolveJid
      if (pn) pn = pn.replace(/:\d+@/, '@');
    } catch (e) {
      console.error(`lookup failed for ${lid}:`, e.message);
    }
    out.write(JSON.stringify({ lid, pn }) + '\n');
    console.log(lid, '->', pn);
  }
  out.end();
  sock.end();
  process.exit(0);
}

main().catch((e) => {
  console.error('FATAL', e);
  process.exit(1);
});
