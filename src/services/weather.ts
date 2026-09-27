export interface LocationWeather {
  city: string
  temperature: number | null
  condition: string
  approximate?: boolean
}

const cacheKey = 'nexa.location-weather'
const failureKey = 'nexa.location-weather-failure'
const cacheAge = 30 * 60 * 1000

function conditionFor(code: number): string {
  if (code === 0) return '晴朗'
  if (code <= 3) return '多云'
  if (code <= 48) return '有雾'
  if (code <= 67) return '有雨'
  if (code <= 77) return '有雪'
  if (code <= 82) return '阵雨'
  if (code <= 86) return '阵雪'
  if (code <= 99) return '雷雨'
  return '天气未知'
}

function currentPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('浏览器不支持定位')); return }
    navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 })
  })
}

export async function getLocationWeather(force = false): Promise<LocationWeather> {
  if (!force) {
    let failure: { timestamp: number; message: string } | null = null
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) || 'null') as { timestamp: number; value: LocationWeather } | null
      if (cached && Date.now() - cached.timestamp < cacheAge && cached.value.city) return cached.value
      failure = JSON.parse(localStorage.getItem(failureKey) || 'null') as { timestamp: number; message: string } | null
    } catch { /* Ignore damaged local cache. */ }
    if (failure && Date.now() - failure.timestamp < cacheAge) throw new Error(failure.message)
  }
  try {
    let coordinates: GeolocationCoordinates | null = null
    try {
      const permission = await navigator.permissions?.query({ name: 'geolocation' })
      if (permission?.state !== 'denied') coordinates = (await currentPosition()).coords
    } catch { /* Location may be denied or unavailable; use an approximate city. */ }
    const cityUrl = new URL('https://api.bigdatacloud.net/data/reverse-geocode-client')
    if (coordinates) {
      cityUrl.searchParams.set('latitude', String(coordinates.latitude))
      cityUrl.searchParams.set('longitude', String(coordinates.longitude))
    }
    cityUrl.searchParams.set('localityLanguage', 'zh')
    const cityResponse = await fetch(cityUrl)
    if (!cityResponse.ok) throw new Error('城市服务暂时不可用')
    const place = await cityResponse.json() as { city?: string; locality?: string; principalSubdivision?: string; latitude?: number; longitude?: number }
    const city = place.city || place.locality || place.principalSubdivision
    if (!city) throw new Error('无法识别城市')
    const latitude = coordinates?.latitude ?? place.latitude
    const longitude = coordinates?.longitude ?? place.longitude
    let temperature: number | null = null
    let condition = '天气不可用'
    if (typeof latitude === 'number' && typeof longitude === 'number') {
      const weatherUrl = new URL('https://api.open-meteo.com/v1/forecast')
      weatherUrl.searchParams.set('latitude', String(latitude))
      weatherUrl.searchParams.set('longitude', String(longitude))
      weatherUrl.searchParams.set('current', 'temperature_2m,weather_code')
      const weatherResponse = await fetch(weatherUrl).catch(() => null)
      if (weatherResponse?.ok) {
        const report = await weatherResponse.json() as { current?: { temperature_2m?: number; weather_code?: number } }
        if (typeof report.current?.temperature_2m === 'number') temperature = Math.round(report.current.temperature_2m)
        if (typeof report.current?.weather_code === 'number') condition = conditionFor(report.current.weather_code)
      }
    }
    const value = { city, temperature, condition, approximate: !coordinates }
    try {
      localStorage.setItem(cacheKey, JSON.stringify({ timestamp: Date.now(), value }))
      localStorage.removeItem(failureKey)
    } catch { /* Weather still works when storage is unavailable. */ }
    return value
  } catch (error) {
    const message = error instanceof Error ? error.message : '位置服务暂时不可用'
    try { localStorage.setItem(failureKey, JSON.stringify({ timestamp: Date.now(), message })) }
    catch { /* The retry button remains available. */ }
    throw new Error(message)
  }
}
