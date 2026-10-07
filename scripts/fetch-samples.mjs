// Downloads the four benchmark photos into samples/ (not committed).
// All are public domain or CC0 on Wikimedia Commons. Run: npm run samples
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SAMPLES = [
  { file: 'portrait.jpg', license: 'Public domain (NASA)', title: 'File:Frank Rubio official portrait.jpg' },
  {
    file: 'product.jpg',
    license: 'CC0',
    title:
      'File:Technics U-38 RS-1500U Stereo Tape Deck (1976) Isolated Loop／Direct Drive／Quartz Lock／IC Logic Control／Tension Control (2016-01-22 10.52.32 piqsels.com en).jpg'
  },
  {
    file: 'interior.jpg',
    license: 'CC0',
    title: 'File:Living room in apartment of Condomínio do Edifício Zaher, Le Blond, Rio de Janeiro, Brazil.jpg'
  },
  {
    file: 'landscape.jpg',
    license: 'Public domain (US National Park Service)',
    title: 'File:Cub Lake at dawn in Rocky Mountain National Park. NPS-Debra Miller (18680833532).jpg'
  }
]

const WIDTH = 3840 // 4K-wide, the largest size the app must stay interactive at
const HEADERS = { 'User-Agent': 'relight-dev-samples/0.1 (local development script)' }
const outDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'samples')

async function imageUrl(title) {
  const api = new URL('https://commons.wikimedia.org/w/api.php')
  api.search = new URLSearchParams({
    action: 'query',
    format: 'json',
    titles: title,
    prop: 'imageinfo',
    iiprop: 'url',
    iiurlwidth: String(WIDTH)
  }).toString()
  const response = await fetch(api, { headers: HEADERS })
  if (!response.ok) throw new Error(`Commons API returned HTTP ${response.status}`)
  const pages = Object.values((await response.json()).query.pages)
  const info = pages[0]?.imageinfo?.[0]
  if (!info) throw new Error(`Not found on Commons: ${title}`)
  return info.thumburl ?? info.url
}

mkdirSync(outDir, { recursive: true })
for (const sample of SAMPLES) {
  const target = join(outDir, sample.file)
  if (existsSync(target)) {
    console.log(`have   ${sample.file}`)
    continue
  }
  const response = await fetch(await imageUrl(sample.title), { headers: HEADERS })
  if (!response.ok) throw new Error(`Download of ${sample.file} returned HTTP ${response.status}`)
  const bytes = Buffer.from(await response.arrayBuffer())
  writeFileSync(target, bytes)
  console.log(`saved  ${sample.file}  ${(bytes.length / 1e6).toFixed(1)} MB  [${sample.license}]`)
}
