// Read-only decoder for the current local 精彩时刻 database format.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const file = process.argv[2];
const account = path.basename(file).replace(/\.bak$/, '');
if (!/^\d+$/.test(account)) throw new Error('Unexpected database filename');
const hash = crypto.createHash('sha256').update(account).digest('hex');
const decoder = crypto.createDecipheriv('aes-256-cbc', Buffer.from(hash.slice(0, 32)), Buffer.from(hash.slice(0, 16)));
const raw = fs.readFileSync(file, 'utf8').trim();
const encoding = raw.startsWith('base64:') ? 'base64' : raw.startsWith('hex:') ? 'hex' : null;
if (!encoding) throw new Error('Unknown database encoding');
const prefix = encoding === 'base64' ? 7 : 4;
const plain = decoder.update(raw.slice(prefix), encoding, 'utf8') + decoder.final('utf8');
const data = JSON.parse(plain.replace(/\u0000+$/, ''));
if (!Array.isArray(data)) throw new Error('Unexpected database schema');
process.stdout.write(JSON.stringify(data));
