'use client';

import { authedFetch } from '@/lib/authedFetch';
import { fetchArray } from '@/lib/lists';
import type {
  AccountResponse,
  AgeingResponse,
  BalanceSheetResponse,
  BillCreateRequest,
  BillResponse,
  ContactErpSummary,
  DispatchResponse,
  GRNResponse,
  InvoiceCreateRequest,
  InvoiceResponse,
  ItemCreateRequest,
  ItemResponse,
  JournalEntryCreateRequest,
  JournalEntryResponse,
  PaymentCreateRequest,
  PaymentResponse,
  PLReportResponse,
  PurchaseOrderResponse,
  SalesOrderResponse,
  SerialLookupResponse,
  StockOnHandResponse,
  StockValuationResponse,
  SupplierPaymentCreateRequest,
  SupplierPaymentResponse,
  TrialBalanceResponse,
} from '@/types/api';

// ------------------------------------------------------------------------ Ledger

export function listAccounts(): Promise<AccountResponse[]> {
  return fetchArray<AccountResponse>('/ledger/accounts?limit=500');
}

export function createAccount(req: {
  code: string;
  name: string;
  type: string;
  normal_side?: string;
  description?: string | null;
}): Promise<AccountResponse> {
  return authedFetch<AccountResponse>('/ledger/accounts', {
    method: 'POST',
    json: req,
  });
}

export function getAccount(id: string): Promise<AccountResponse> {
  return authedFetch<AccountResponse>(`/ledger/accounts/${id}`);
}

export function listJournals(params?: {
  account_id?: string;
  limit?: number;
  offset?: number;
}): Promise<JournalEntryResponse[]> {
  const qs = new URLSearchParams();
  if (params?.account_id) qs.set('account_id', params.account_id);
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  return fetchArray<JournalEntryResponse>(`/ledger/journals?${qs.toString()}`);
}

export function createJournal(
  req: JournalEntryCreateRequest,
): Promise<JournalEntryResponse> {
  return authedFetch<JournalEntryResponse>('/ledger/journals', {
    method: 'POST',
    json: req,
  });
}

export function getJournal(id: string): Promise<JournalEntryResponse> {
  return authedFetch<JournalEntryResponse>(`/ledger/journals/${id}`);
}

export function reverseJournal(id: string): Promise<JournalEntryResponse> {
  return authedFetch<JournalEntryResponse>(`/ledger/journals/${id}/reverse`, {
    method: 'POST',
  });
}

// ------------------------------------------------------------- AR — Receivables

export function listInvoices(params?: {
  customer_id?: string;
  status?: string;
}): Promise<InvoiceResponse[]> {
  const qs = new URLSearchParams();
  qs.set('limit', '200');
  if (params?.customer_id) qs.set('customer_id', params.customer_id);
  if (params?.status) qs.set('status', params.status);
  return fetchArray<InvoiceResponse>(`/receivables/invoices?${qs.toString()}`);
}

export function createInvoice(
  req: InvoiceCreateRequest,
): Promise<InvoiceResponse> {
  return authedFetch<InvoiceResponse>('/receivables/invoices', {
    method: 'POST',
    json: req,
  });
}

export function getInvoice(id: string): Promise<InvoiceResponse> {
  return authedFetch<InvoiceResponse>(`/receivables/invoices/${id}`);
}

export function issueInvoice(id: string): Promise<InvoiceResponse> {
  return authedFetch<InvoiceResponse>(`/receivables/invoices/${id}/issue`, {
    method: 'POST',
  });
}

export function voidInvoice(id: string): Promise<InvoiceResponse> {
  return authedFetch<InvoiceResponse>(`/receivables/invoices/${id}/void`, {
    method: 'POST',
  });
}

export function listPayments(params?: {
  customer_id?: string;
}): Promise<PaymentResponse[]> {
  const qs = new URLSearchParams();
  qs.set('limit', '200');
  if (params?.customer_id) qs.set('customer_id', params.customer_id);
  return fetchArray<PaymentResponse>(`/receivables/payments?${qs.toString()}`);
}

export function createPayment(
  req: PaymentCreateRequest,
): Promise<PaymentResponse> {
  return authedFetch<PaymentResponse>('/receivables/payments', {
    method: 'POST',
    json: req,
  });
}

export function allocatePayment(
  paymentId: string,
  req: { invoice_id: string; amount: number }[],
): Promise<unknown> {
  return authedFetch(`/receivables/payments/${paymentId}/allocate`, {
    method: 'POST',
    json: req,
  });
}

export function getAgeing(customerId?: string): Promise<AgeingResponse> {
  const qs = customerId ? `?customer_id=${customerId}` : '';
  return authedFetch<AgeingResponse>(`/receivables/ageing${qs}`);
}

// -------------------------------------------------------------- AP — Payables

export function listBills(params?: {
  supplier_id?: string;
  status?: string;
}): Promise<BillResponse[]> {
  const qs = new URLSearchParams();
  qs.set('limit', '200');
  if (params?.supplier_id) qs.set('supplier_id', params.supplier_id);
  if (params?.status) qs.set('status', params.status);
  return fetchArray<BillResponse>(`/payables/bills?${qs.toString()}`);
}

export function createBill(req: BillCreateRequest): Promise<BillResponse> {
  return authedFetch<BillResponse>('/payables/bills', {
    method: 'POST',
    json: req,
  });
}

export function getBill(id: string): Promise<BillResponse> {
  return authedFetch<BillResponse>(`/payables/bills/${id}`);
}

export function issueBill(id: string): Promise<BillResponse> {
  return authedFetch<BillResponse>(`/payables/bills/${id}/issue`, {
    method: 'POST',
  });
}

export function voidBill(id: string): Promise<BillResponse> {
  return authedFetch<BillResponse>(`/payables/bills/${id}/void`, {
    method: 'POST',
  });
}

export function listSupplierPayments(params?: {
  supplier_id?: string;
}): Promise<SupplierPaymentResponse[]> {
  const qs = new URLSearchParams();
  qs.set('limit', '200');
  if (params?.supplier_id) qs.set('supplier_id', params.supplier_id);
  return fetchArray<SupplierPaymentResponse>(
    `/payables/payments?${qs.toString()}`,
  );
}

export function createSupplierPayment(
  req: SupplierPaymentCreateRequest,
): Promise<SupplierPaymentResponse> {
  return authedFetch<SupplierPaymentResponse>('/payables/payments', {
    method: 'POST',
    json: req,
  });
}

export function allocateBillPayment(
  paymentId: string,
  req: { bill_id: string; amount: number },
): Promise<unknown> {
  return authedFetch(`/payables/payments/${paymentId}/allocate`, {
    method: 'POST',
    json: req,
  });
}

export function getAPAgeing(supplierId?: string): Promise<AgeingResponse> {
  const qs = supplierId ? `?supplier_id=${supplierId}` : '';
  return authedFetch<AgeingResponse>(`/payables/ageing${qs}`);
}

// ------------------------------------------------------------------- Inventory Items

export function listItems(category?: string): Promise<ItemResponse[]> {
  const params = category ? `?category=${encodeURIComponent(category)}&limit=200` : '?limit=200';
  return fetchArray<ItemResponse>(`/inventory/items${params}`);
}

export function getItem(itemId: string): Promise<ItemResponse> {
  return authedFetch<ItemResponse>(`/inventory/items/${itemId}`);
}

export function createItem(req: ItemCreateRequest): Promise<ItemResponse> {
  return authedFetch<ItemResponse>('/inventory/items', {
    method: 'POST',
    json: req,
  });
}

// ------------------------------------------------------------------------ Stock

export function listStock(): Promise<StockOnHandResponse[]> {
  return authedFetch<StockOnHandResponse[]>('/inventory/stock?limit=500');
}

export function getStockValuation(): Promise<StockValuationResponse> {
  return authedFetch<StockValuationResponse>('/inventory/valuation');
}

export function getSerial(serialNo: string): Promise<SerialLookupResponse> {
  return authedFetch<SerialLookupResponse>(`/inventory/stock/serial/${serialNo}`);
}

// ---------------------------------------------------------------- Procurement

export function listPurchaseOrders(params?: {
  supplier_id?: string;
  status?: string;
}): Promise<PurchaseOrderResponse[]> {
  const sp = new URLSearchParams();
  sp.set('limit', '200');
  if (params?.supplier_id) sp.set('supplier_id', params.supplier_id);
  if (params?.status) sp.set('status', params.status);
  return authedFetch<PurchaseOrderResponse[]>(`/procurement/purchase-orders?${sp.toString()}`);
}

export function listGRNs(params?: {
  po_id?: string;
  status?: string;
}): Promise<GRNResponse[]> {
  const sp = new URLSearchParams();
  sp.set('limit', '200');
  if (params?.po_id) sp.set('po_id', params.po_id);
  if (params?.status) sp.set('status', params.status);
  return authedFetch<GRNResponse[]>(`/procurement/grns?${sp.toString()}`);
}

export function confirmGRN(grnId: string): Promise<GRNResponse> {
  return authedFetch<GRNResponse>(`/procurement/grns/${grnId}/confirm`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------- Fulfilment

export function listSalesOrders(params?: {
  customer_id?: string;
  status?: string;
}): Promise<SalesOrderResponse[]> {
  const sp = new URLSearchParams();
  sp.set('limit', '200');
  if (params?.customer_id) sp.set('customer_id', params.customer_id);
  if (params?.status) sp.set('status', params.status);
  return authedFetch<SalesOrderResponse[]>(`/fulfilment/sales-orders?${sp.toString()}`);
}

export function listDispatches(params?: {
  so_id?: string;
  status?: string;
}): Promise<DispatchResponse[]> {
  const sp = new URLSearchParams();
  sp.set('limit', '200');
  if (params?.so_id) sp.set('so_id', params.so_id);
  if (params?.status) sp.set('status', params.status);
  return authedFetch<DispatchResponse[]>(`/fulfilment/dispatches?${sp.toString()}`);
}

export function confirmDispatch(dispatchId: string): Promise<DispatchResponse> {
  return authedFetch<DispatchResponse>(`/fulfilment/dispatches/${dispatchId}/confirm`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------- Reports

// Uses the ledger endpoint, not /reports/trial-balance. The two return
// different shapes: /reports returns a flat `items` list of dr/cr totals,
// while /ledger returns `rows` with the opening/period/closing split plus the
// totals and difference that TrialBalanceResponse describes and the reports
// page renders. Pointing this at /reports left tbData.rows undefined, and the
// unguarded .length crashed the whole Reports page on its default tab.
export function getTrialBalance(asOfDate: string): Promise<TrialBalanceResponse> {
  return authedFetch<TrialBalanceResponse>(`/ledger/trial-balance?as_of_date=${asOfDate}`);
}

export function getPLReport(fiscalYear: number): Promise<PLReportResponse> {
  return authedFetch<PLReportResponse>(`/reports/profit-and-loss?fiscal_year=${fiscalYear}`);
}

export function getBalanceSheet(asOfDate: string): Promise<BalanceSheetResponse> {
  return authedFetch<BalanceSheetResponse>(`/reports/balance-sheet?as_of_date=${asOfDate}`);
}

// -------------------------------------------------------------- Contact ERP summary

export function getContactErpSummary(contactId: string): Promise<ContactErpSummary> {
  return authedFetch<ContactErpSummary>(`/contacts/${contactId}/erp-summary`);
}
