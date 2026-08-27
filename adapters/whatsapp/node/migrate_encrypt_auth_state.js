/**
 * One-off: encrypts the existing plaintext .auth_state files in place, so
 * switching ingest.js to useEncryptedMultiFileAuthState doesn't force an
 * unnecessary re-pair (the session is still good, it was just sitting in
 * plaintext). Safe to re-run — skips any file that's already encrypted
 * (JSON with the {iv, authTag, ciphertext} shape) instead of double
 * encrypting it.
 *
 * Run once: node migrate_encrypt_auth_state.js
 */

const fs = require('fs');
const path = require('path');
const { encrypt, loadKey } = require('./encrypted_auth_state.js');

const AUTH_DIR = path.join(__dirname, '.auth_state');

if (!process.env.WHATSAPP_AUTH_ENCRYPTION_KEY) {
  const envPath = path.join(__dirname, '..', '..', '..', '.env');
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, 'utf-8').split('\n')) {
      const match = line.match(/^WHATSAPP_AUTH_ENCRYPTION_KEY=(.*)$/);
      if (match) process.env.WHATSAPP_AUTH_ENCRYPTION_KEY = match[1].trim();
    }
  }
}

function looksAlreadyEncrypted(raw) {
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null
      && 'iv' in parsed && 'authTag' in parsed && 'ciphertext' in parsed;
  } catch {
    return false;
  }
}

function main() {
  const key = loadKey(); // throws early with a clear message if unset
  const files = fs.readdirSync(AUTH_DIR).filter((f) => f.endsWith('.json'));

  let encrypted = 0;
  let skipped = 0;
  for (const file of files) {
    const filePath = path.join(AUTH_DIR, file);
    const raw = fs.readFileSync(filePath, 'utf-8');
    if (looksAlreadyEncrypted(raw)) {
      skipped += 1;
      continue;
    }
    fs.writeFileSync(filePath, encrypt(key, raw));
    encrypted += 1;
  }

  console.log(`encrypted ${encrypted} files, skipped ${skipped} already-encrypted files (${files.length} total)`);
}

main();
