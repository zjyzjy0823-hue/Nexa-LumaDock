import { apiRequest } from '../api/client'
import type { LedgerCategory, LedgerCategoryInput, LedgerTransaction, LedgerTransactionInput, LedgerSummary } from '../types/ledger'
const root = '/api/v1/ledger'
export const ledgerService = {
  categories(token: string) { return apiRequest<LedgerCategory[]>(`${root}/categories`, {}, token) },
  createCategory(token: string, data: LedgerCategoryInput) { return apiRequest<LedgerCategory>(`${root}/categories`, { method: 'POST', body: JSON.stringify(data) }, token) },
  updateCategory(token: string, id: string, data: Partial<LedgerCategoryInput>) { return apiRequest<LedgerCategory>(`${root}/categories/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  removeCategory(token: string, id: string) { return apiRequest<void>(`${root}/categories/${id}`, { method: 'DELETE' }, token) },
  transactions(token: string, month?: string) { return apiRequest<LedgerTransaction[]>(`${root}/transactions${month ? `?month=${month}` : ''}`, {}, token) },
  createTransaction(token: string, data: LedgerTransactionInput) { return apiRequest<LedgerTransaction>(`${root}/transactions`, { method: 'POST', body: JSON.stringify(data) }, token) },
  updateTransaction(token: string, id: string, data: Partial<LedgerTransactionInput>) { return apiRequest<LedgerTransaction>(`${root}/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  removeTransaction(token: string, id: string) { return apiRequest<void>(`${root}/transactions/${id}`, { method: 'DELETE' }, token) },
  summary(token: string, month?: string) { return apiRequest<LedgerSummary>(`${root}/summary${month ? `?month=${month}` : ''}`, {}, token) },
}
