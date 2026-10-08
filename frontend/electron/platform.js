const path = require('path')

function backendExecutable(resourcesPath, platform, packaged) {
  if (!packaged) return null
  return path.join(resourcesPath, 'backend', platform === 'win32' ? 'locwarp-backend.exe' : 'locwarp-backend')
}

async function locatePc(platform, windowsLocation, ipFallback) {
  const native = platform === 'win32' ? await windowsLocation() : null
  if (native?.ok) return { ...native, via: 'windows' }
  if (native?.code === 'DENIED') return native
  const ip = await ipFallback()
  if (ip) return ip
  return {
    ok: false,
    code: 'ALL_FAILED',
    message: native
      ? `Windows Location: ${native.code}${native.message ? ' (' + native.message + ')' : ''} | IP fallback: all 3 services unreachable`
      : 'Native desktop location is unavailable; IP geolocation failed. Select a location manually.',
  }
}

function macBackendError(locale, exe, detail) {
  const zh = locale.toLowerCase().startsWith('zh')
  return {
    title: zh ? 'LocWarp 無法啟動' : 'LocWarp cannot start',
    message: zh ? 'macOS 背景服務遺失或無法執行' : 'macOS backend is missing or cannot run',
    detail: (zh
      ? '請重新安裝符合此 Mac 架構的完整 LocWarp.app（Apple Silicon: arm64；Intel: x64）。開發者請在相同架構的 macOS 使用 build-macos.sh 重建 Python 3.13 背景服務。若 macOS 阻擋啟動，請使用可信任且已簽署／公證的版本；不要停用系統安全機制。\n\n預期路徑：\n'
      : 'Reinstall the complete LocWarp.app for this Mac (Apple Silicon: arm64; Intel: x64). Developers: rebuild the Python 3.13 backend with build-macos.sh on matching macOS architecture. If macOS blocks launch, use a trusted signed/notarized build; do not disable system security.\n\nExpected path:\n') + exe + (detail ? `\n\n${detail}` : ''),
    buttons: zh ? ['開啟服務資料夾', '關閉'] : ['Open backend folder', 'Close'],
  }
}

function applicationMenu(platform) {
  if (platform !== 'darwin') return null
  return [
    { role: 'appMenu' },
    { role: 'editMenu' },
    { role: 'viewMenu' },
    { role: 'windowMenu' },
  ]
}

module.exports = { backendExecutable, locatePc, macBackendError, applicationMenu }
