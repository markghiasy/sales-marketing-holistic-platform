/**
 * Same on-disk shape and API as Baileys' own `useMultiFileAuthState`, but
 * every file's contents are AES-256-GCM encrypted before hitting disk.
 *
 * Why not just wrap the folder in OS-level disk encryption instead: that
 * protects against someone stealing the drive, not against someone who
 * already has filesystem access on this machine (a shared machine, a
 * backup that leaves the machine, a misconfigured cloud volume once this
 * gets re-hosted) — which is the actual threat `creds.json` sitting in
 * plaintext exposes. Encrypting the file contents themselves covers that
 * case too.
 *
 * Key comes from WHATSAPP_AUTH_ENCRYPTION_KEY (.env, gitignored — never
 * committed), 32 bytes as base64. `openssl rand -base64 32` to generate
 * one. Lost key = lost session, same as losing the phone pairing; there's
 * nothing sensitive enough here to warrant a recovery path more elaborate
 * than "re-scan the QR code."
 */

const { Mutex } = require('async-mutex');
const { mkdir, readFile, stat, unlink, writeFile } = require('fs/promises');
const { join } = require('path');
const crypto = require('crypto');
const { proto, initAuthCreds, BufferJSON } = require('@whiskeysockets/baileys');

const ALGORITHM = 'aes-256-gcm';
const IV_LENGTH = 12; // recommended nonce length for GCM

function loadKey() {
  const raw = process.env.WHATSAPP_AUTH_ENCRYPTION_KEY;
  if (!raw) {
    throw new Error(
      'WHATSAPP_AUTH_ENCRYPTION_KEY is not set. Generate one with ' +
      '`openssl rand -base64 32` and add it to .env — the WhatsApp auth ' +
      'state is no longer stored in plaintext, so this is required to run.'
    );
  }
  const key = Buffer.from(raw, 'base64');
  if (key.length !== 32) {
    throw new Error(
      `WHATSAPP_AUTH_ENCRYPTION_KEY must decode to exactly 32 bytes, got ${key.length}. ` +
      'Generate one with `openssl rand -base64 32`.'
    );
  }
  return key;
}

function encrypt(key, plaintext) {
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
  const encrypted = Buffer.concat([cipher.update(plaintext, 'utf-8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  // iv and authTag travel alongside the ciphertext — neither is secret on
  // its own, both are required to decrypt, GCM's whole design assumes this
  return JSON.stringify({
    iv: iv.toString('base64'),
    authTag: authTag.toString('base64'),
    ciphertext: encrypted.toString('base64'),
  });
}

function decrypt(key, fileContents) {
  const { iv, authTag, ciphertext } = JSON.parse(fileContents);
  const decipher = crypto.createDecipheriv(ALGORITHM, key, Buffer.from(iv, 'base64'));
  decipher.setAuthTag(Buffer.from(authTag, 'base64'));
  const decrypted = Buffer.concat([
    decipher.update(Buffer.from(ciphertext, 'base64')),
    decipher.final(),
  ]);
  return decrypted.toString('utf-8');
}

const fileLocks = new Map();
function getFileLock(path) {
  let mutex = fileLocks.get(path);
  if (!mutex) {
    mutex = new Mutex();
    fileLocks.set(path, mutex);
  }
  return mutex;
}

const fixFileName = (file) => file?.replace(/\//g, '__')?.replace(/:/g, '-');

async function useEncryptedMultiFileAuthState(folder) {
  const key = loadKey();

  const writeData = async (data, file) => {
    const filePath = join(folder, fixFileName(file));
    const mutex = getFileLock(filePath);
    return mutex.acquire().then(async (release) => {
      try {
        const plaintext = JSON.stringify(data, BufferJSON.replacer);
        await writeFile(filePath, encrypt(key, plaintext));
      } finally {
        release();
      }
    });
  };

  const readData = async (file) => {
    const filePath = join(folder, fixFileName(file));
    const mutex = getFileLock(filePath);
    let raw;
    try {
      raw = await mutex.acquire().then(async (release) => {
        try {
          return await readFile(filePath, { encoding: 'utf-8' });
        } finally {
          release();
        }
      });
    } catch (err) {
      if (err.code === 'ENOENT') return null; // genuinely first run — fine
      throw err;
    }
    // File exists but won't decrypt — wrong key, or a stale plaintext
    // file from before this migration. Baileys' own reference
    // implementation treats *any* read failure here as "missing," which
    // would silently downgrade this to a blank session (forcing a re-pair
    // with no explanation why). Wrong-key is a configuration mistake, not
    // a missing-file case — fail loud instead of quietly discarding a
    // real session.
    try {
      const plaintext = decrypt(key, raw);
      return JSON.parse(plaintext, BufferJSON.reviver);
    } catch (err) {
      throw new Error(
        `failed to decrypt ${filePath} — WHATSAPP_AUTH_ENCRYPTION_KEY is ` +
        `wrong, or this file predates encryption. If this is a fresh ` +
        `re-pair, delete .auth_state and start over. (${err.message})`
      );
    }
  };

  const removeData = async (file) => {
    try {
      const filePath = join(folder, fixFileName(file));
      const mutex = getFileLock(filePath);
      return mutex.acquire().then(async (release) => {
        try {
          await unlink(filePath);
        } catch {
          // already gone — fine
        } finally {
          release();
        }
      });
    } catch {
      // lock/path setup itself failed — nothing to clean up
    }
  };

  const folderInfo = await stat(folder).catch(() => undefined);
  if (folderInfo) {
    if (!folderInfo.isDirectory()) {
      throw new Error(`found something that is not a directory at ${folder}, either delete it or specify a different location`);
    }
  } else {
    await mkdir(folder, { recursive: true });
  }

  const creds = (await readData('creds.json')) || initAuthCreds();

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const data = {};
          await Promise.all(ids.map(async (id) => {
            let value = await readData(`${type}-${id}.json`);
            if (type === 'app-state-sync-key' && value) {
              value = proto.Message.AppStateSyncKeyData.fromObject(value);
            }
            data[id] = value;
          }));
          return data;
        },
        set: async (data) => {
          const tasks = [];
          for (const category in data) {
            for (const id in data[category]) {
              const value = data[category][id];
              const file = `${category}-${id}.json`;
              tasks.push(value ? writeData(value, file) : removeData(file));
            }
          }
          await Promise.all(tasks);
        },
      },
    },
    saveCreds: async () => {
      return writeData(creds, 'creds.json');
    },
  };
}

module.exports = { useEncryptedMultiFileAuthState, encrypt, decrypt, loadKey };
