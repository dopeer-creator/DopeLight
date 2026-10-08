// Renders app/resources/logo.svg into the icon files the app and installer use:
//   app/resources/icon.png (1024 px) and app/resources/icon.ico (16..256 px).
// Runs inside Electron (it has a browser to draw the SVG):  npm run icons
const { app, BrowserWindow } = require('electron')
const { readFileSync, writeFileSync } = require('node:fs')
const { join } = require('node:path')

const resources = join(__dirname, '..', 'app', 'resources')
const SIZE = 1024
const ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]

/** An .ico file is a small table followed by one PNG per size. */
function buildIco(pngs) {
  const header = Buffer.alloc(6 + 16 * pngs.length)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: icon
  header.writeUInt16LE(pngs.length, 4)
  let offset = header.length
  pngs.forEach(({ size, data }, index) => {
    const entry = 6 + 16 * index
    header.writeUInt8(size === 256 ? 0 : size, entry) // 0 means 256
    header.writeUInt8(size === 256 ? 0 : size, entry + 1)
    header.writeUInt16LE(1, entry + 4) // colour planes
    header.writeUInt16LE(32, entry + 6) // bits per pixel
    header.writeUInt32LE(data.length, entry + 8)
    header.writeUInt32LE(offset, entry + 12)
    offset += data.length
  })
  return Buffer.concat([header, ...pngs.map((png) => png.data)])
}

app.whenReady().then(async () => {
  // Fill the window whatever the display scaling is (fixed pixel sizes get cropped at 125 %).
  const svg = readFileSync(join(resources, 'logo.svg'), 'utf8').replace(
    'width="512" height="512"',
    'style="display:block;width:100vw;height:100vh"'
  )
  const page = `<html><body style="margin:0;background:transparent;overflow:hidden">${svg}</body></html>`
  const window = new BrowserWindow({
    width: SIZE,
    height: SIZE,
    show: false,
    frame: false,
    transparent: true,
    webPreferences: { offscreen: true }
  })
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(page)}`)
  await new Promise((resolve) => setTimeout(resolve, 500))
  // The capture may be larger than asked for (display scaling) and not quite square.
  // The drawing is centred, so take the centre square, then bring it to the exact size.
  const shot = await window.webContents.capturePage()
  const { width, height } = shot.getSize()
  const side = Math.min(width, height)
  const square = shot.crop({
    x: Math.floor((width - side) / 2),
    y: Math.floor((height - side) / 2),
    width: side,
    height: side
  })
  const full = square.resize({ width: SIZE, height: SIZE, quality: 'best' })
  writeFileSync(join(resources, 'icon.png'), full.toPNG())
  const pngs = ICO_SIZES.map((size) => ({
    size,
    data: full.resize({ width: size, height: size, quality: 'best' }).toPNG()
  }))
  writeFileSync(join(resources, 'icon.ico'), buildIco(pngs))
  console.log(`wrote icon.png (${SIZE} px) and icon.ico (${ICO_SIZES.join(', ')} px)`)
  app.quit()
})
