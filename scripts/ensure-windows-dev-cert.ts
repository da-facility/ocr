import { existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const certPath = resolve('build/certs/windows-dev-signing.p12')
const keyPath = resolve('build/certs/windows-dev-signing.key')
const crtPath = resolve('build/certs/windows-dev-signing.crt')

if (existsSync(certPath)) {
  console.log(`Windows dev signing certificate already exists: ${certPath}`)
  process.exit(0)
}

mkdirSync(dirname(certPath), { recursive: true })

const subject = '/CN=OCR Console Local Dev/O=Local Untrusted Development/C=US'
const openssl = spawnSync(
  'openssl',
  [
    'req',
    '-x509',
    '-newkey',
    'rsa:4096',
    '-sha256',
    '-nodes',
    '-days',
    '3650',
    '-subj',
    subject,
    '-keyout',
    keyPath,
    '-out',
    crtPath,
  ],
  { stdio: 'inherit' },
)

if (openssl.status !== 0) {
  process.exit(openssl.status ?? 1)
}

const pkcs12 = spawnSync(
  'openssl',
  [
    'pkcs12',
    '-export',
    '-inkey',
    keyPath,
    '-in',
    crtPath,
    '-out',
    certPath,
    '-passout',
    'pass:',
  ],
  { stdio: 'inherit' },
)

if (pkcs12.status !== 0) {
  process.exit(pkcs12.status ?? 1)
}

console.log(`Created local untrusted Windows signing certificate: ${certPath}`)
