import { apiRequest } from '../api/client'
import type { Device, DeviceInput } from '../types/device'

const root = '/api/v1/devices'
export const deviceService = {
  list(token: string) { return apiRequest<Device[]>(root, {}, token) },
  create(token: string, data: DeviceInput) { return apiRequest<Device>(root, { method: 'POST', body: JSON.stringify(data) }, token) },
  update(token: string, id: string, data: Partial<DeviceInput>) { return apiRequest<Device>(`${root}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/${id}`, { method: 'DELETE' }, token) },
}
